"""QA tasks: plain-text tasks routed to the existing Critic, Coverage, Change Impact,
Traceability and Suite Planner, with status changes only after confirmation."""

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto, home
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import ChangeImpact, ReviewStatus, TestCaseImpact, Workspace
from spec_to_test.qa_agent import tasks
from spec_to_test.qa_agent.tasks import ProposedAction, apply_action, plan_task, run_task
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.test_critic import critique
from spec_to_test.test_generator import generate_test_cases

APP_PATH = str(PROJECT_ROOT / "app.py")


@pytest.fixture
def ws(example_text) -> Workspace:
    result = analyze_requirements(extract_requirements(example_text))
    workspace = Workspace(document_hash="doc", title="Password reset", requirements=result.requirements,
                          findings=result.findings)
    workspace.test_cases = generate_test_cases(workspace, "en")
    return workspace


# --- Planning ----------------------------------------------------------------

@pytest.mark.parametrize(("task", "tools"), [
    ("Check the quality of the test cases", ["critic"]),
    ("Какие сценарии не покрыты?", ["coverage"]),
    ("Що змінилося з попередньої версії?", ["impact"]),
    ("Show traceability gaps", ["traceability"]),
    ("Спланируй smoke-набор", ["suites"]),
    ("Check coverage and plan a regression suite", ["coverage", "suites"]),
    ("Full audit before release", list(tasks.TOOLS)),
])
def test_task_picks_the_matching_tools(ws, task, tools):
    assert plan_task(task, ws).tools == tools


def test_ids_scope_the_task_and_alone_pick_a_tool(ws):
    plan = plan_task("What about tc-002 and REQ-1?", ws)
    assert plan.test_case_ids == ["TC-002"]
    assert plan.requirement_ids == ["REQ-1"]
    assert plan.tools == ["critic"]
    assert plan_task("REQ-3", ws).tools == ["coverage"]


def test_unknown_ids_are_reported_not_replaced_by_the_whole_document(ws):
    result = run_task("check TC-999", ws)
    assert result.status == "error"
    assert result.error == "qatask.error.unknown_ids"
    assert result.plan.unknown_ids == ["TC-999"]
    assert not result.steps
    # Words with digits that are not ID-like are not flagged.
    assert plan_task("check quality of mp3 uploads", ws).unknown_ids == []


def test_step_limit_cuts_the_plan(ws):
    plan = plan_task("full audit", ws, max_steps=2)
    assert plan.tools == ["critic", "coverage"]
    assert plan.skipped_tools == ["impact", "traceability", "suites"]
    assert len(run_task("full audit", ws, max_steps=2).steps) == 2


# --- Unsupported and invalid tasks -------------------------------------------

def test_unsupported_task_runs_nothing(ws):
    result = run_task("write me a poem", ws)
    assert result.status == "unsupported"
    assert result.steps == []
    assert result.plan.unsupported_terms == ["write"]


@pytest.mark.parametrize("task", ["Delete everything", "Delete TC-001", "Удали REQ-1"])
def test_unsupported_action_is_not_turned_into_checks(ws, task):
    assert run_task(task, ws).status == "unsupported"


def test_unsupported_part_is_reported_and_the_rest_is_done(ws):
    result = run_task("Plan a smoke suite and run it", ws)
    assert result.status == "done"
    assert [s.tool for s in result.steps] == ["suites"]
    assert result.plan.unsupported_terms == ["run"]


@pytest.mark.parametrize(("task", "error"), [
    ("   ", "qatask.error.empty"),
    ("x" * (tasks.MAX_TASK_LENGTH + 1), "qatask.error.too_long"),
])
def test_invalid_task(ws, task, error):
    result = run_task(task, ws)
    assert (result.status, result.error) == ("error", error)


# --- Results come from the existing tools ------------------------------------

def test_critic_step_reports_the_critic_issues(ws):
    tc = ws.test_cases[0]
    expected = critique(tc, ws)
    step = run_task(f"review {tc.id}", ws).steps[0]
    assert step.tool == "critic"
    assert [i.key for i in step.problems] == [f"critic.{i.code}" for i in expected if not i.unknown]
    assert [i.key for i in step.unknowns] == [f"critic.{i.code}" for i in expected if i.unknown]
    assert {i.ref for i in step.problems + step.unknowns} <= {tc.id}
    assert step.summary.params["checked"] == "1"


def test_full_run_combines_every_tool_and_never_changes_the_workspace(ws):
    before = ws.model_dump()
    result = run_task("full audit", ws)
    assert result.status == "done"
    assert [s.tool for s in result.steps] == list(tasks.TOOLS)
    assert all(s.summary is not None for s in result.steps)
    # Generated test cases are Draft: suites and traceability ask to approve.
    keys = {i.key for i in result.recommendations}
    assert {"qatask.rec.suites_approve", "qatask.rec.trace_approve"} <= keys
    assert ws.model_dump() == before


def test_impact_uses_the_stored_impact_or_computes_it(ws):
    assert run_task("what changed?", ws).steps[0].summary.key == "qatask.summary.impact_none"
    impact = ChangeImpact(previous_title="Password reset", test_cases=[
        TestCaseImpact(test_case_id="TC-001", requirement_id="REQ-1", review_status=ReviewStatus.APPROVED,
                       reason="modified"),
    ])
    calls = []
    step = run_task("what changed?", ws, previous_impact=lambda w: calls.append(w) or impact).steps[0]
    assert len(calls) == 1
    assert [(i.key, i.ref) for i in step.problems] == [("qatask.impact.test_case", "TC-001")]
    assert step.recommendations[0].params == {"ids": "TC-001"}
    ws.change_impact = impact
    assert run_task("what changed?", ws, previous_impact=lambda w: pytest.fail("not needed")).steps[0].problems


def test_traceability_follows_the_scope(ws):
    whole = run_task("traceability gaps", ws).steps[0]
    scoped = run_task("traceability gaps for REQ-1", ws).steps[0]
    assert {i.ref for i in scoped.problems} == {"REQ-1"}
    assert len(whole.problems) > len(scoped.problems)


def test_a_failing_tool_does_not_lose_the_others(ws, monkeypatch):
    def broken(*_args):
        raise RuntimeError("boom")

    monkeypatch.setitem(tasks._RUNNERS, "coverage", broken)
    result = run_task("check coverage and plan suites", ws)
    assert result.status == "partial"
    assert [(s.tool, s.status, s.error) for s in result.steps] == [
        ("coverage", "error", "RuntimeError"), ("suites", "ok", ""),
    ]
    assert run_task("check coverage", ws).status == "error"


# --- Status changes need confirmation ----------------------------------------

def test_approval_is_only_proposed_and_checked_by_the_critic(ws):
    result = run_task("Утверди TC-003", ws)
    assert result.action == ProposedAction(test_case_ids=["TC-003"], status=ReviewStatus.APPROVED)
    assert [s.tool for s in result.steps] == ["critic"]
    assert all(tc.review_status == ReviewStatus.DRAFT for tc in ws.test_cases)


def test_status_change_without_ids_is_not_proposed(ws):
    result = run_task("approve the test cases and check their quality", ws)
    assert result.action is None
    assert result.plan.action_needs_ids


def test_apply_action_changes_only_the_named_test_cases(ws):
    changed = apply_action(ws, ProposedAction(test_case_ids=["TC-001", "TC-002"], status=ReviewStatus.APPROVED))
    assert changed == ["TC-001", "TC-002"]
    assert [tc.id for tc in ws.test_cases if tc.review_status == ReviewStatus.APPROVED] == ["TC-001", "TC-002"]
    assert apply_action(ws, ProposedAction(test_case_ids=["TC-001"], status=ReviewStatus.APPROVED)) == []
    with pytest.raises(ValueError, match="TC-999"):
        apply_action(ws, ProposedAction(test_case_ids=["TC-001", "TC-999"], status=ReviewStatus.DRAFT))
    assert ws.test_cases[0].review_status == ReviewStatus.APPROVED  # nothing changed on error


# --- Page ---------------------------------------------------------------------

def _task_mode(example_text: str) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    goto(at, "qa_agent")
    at.segmented_control(key="qa_mode").set_value("task").run()
    assert not at.exception
    return at


def _button(at: AppTest, key: str):
    return next(b for b in at.button if b.key == key)


def test_page_runs_a_task_and_applies_a_confirmed_change(example_text):
    at = _task_mode(example_text)
    at.text_area(key="qa_task_text").input("Approve TC-001 and plan a smoke suite").run()
    _button(at, "qa_task_run").click().run()
    assert not at.exception
    subheaders = [s.value for s in at.subheader]
    assert "Conclusions" in subheaders and "Recommendations" in subheaders
    assert any("Test Case Critic" in m.value for m in at.markdown)
    assert any("Set TC-001 to **Approved**" in m.value for m in at.markdown)

    assert _button(at, "qa_task_apply").disabled  # nothing changes before the confirmation
    assert at.session_state["workspace"].test_cases[0].review_status == ReviewStatus.DRAFT
    at.checkbox(key="qa_task_confirm").check().run()
    _button(at, "qa_task_apply").click().run()
    assert not at.exception
    assert at.session_state["workspace"].test_cases[0].review_status == ReviewStatus.APPROVED
    assert any("Status changed to Approved: TC-001" in s.value for s in at.success)
    assert not any(b.key == "qa_task_apply" for b in at.button)  # applied once


def test_page_reports_an_unsupported_task(example_text):
    at = _task_mode(example_text)
    at.text_area(key="qa_task_text").input("Delete everything").run()
    _button(at, "qa_task_run").click().run()
    assert not at.exception
    assert any("not supported" in w.value for w in at.warning)
