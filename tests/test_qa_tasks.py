"""QA tasks: plain-text tasks routed to the existing Critic, Coverage, Change Impact,
Traceability and Suite Planner, with status changes only after confirmation."""

import json

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto, home
from spec_to_test.evaluation.cases import FIXTURES_DIR
from spec_to_test.evaluation.qa_agent_eval import load_gold
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import ChangeImpact, ClarificationStatus, ReviewStatus, Source, TestCaseImpact, Workspace
from spec_to_test.qa_agent import tasks
from spec_to_test.qa_agent.on_change import build_workspace
from spec_to_test.qa_agent.tasks import AgentResult, Item, ProposedAction, apply_action, plan_task, run_task
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
    ("Find contradictions", ["requirements"]),
    ("Найди противоречия", ["requirements"]),
    ("Знайди суперечності", ["requirements"]),
    ("Check the requirements", ["requirements"]),
    ("Проверь требования", ["requirements"]),
    ("Перевір вимоги", ["requirements"]),
    ("Is the document ready for testing?", ["requirements"]),
    ("Готов ли документ к тестированию?", ["requirements"]),
    ("Чи готовий документ до тестування?", ["requirements"]),
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
    assert plan.tools == ["requirements", "critic"]
    assert plan.skipped_tools == ["coverage", "impact", "traceability", "suites"]
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
    # Generated test cases are Draft: one summary asks to approve them, apart from the problems.
    assert result.approval is not None and result.approval.key == "qatask.approval.summary_ids"
    assert ws.model_dump() == before


def _requirement_problems(result) -> list[tuple[str, str]]:
    """(ID, topic) per affected requirement; a merged line names several IDs."""
    [step] = [s for s in result.steps if s.tool == "requirements"]
    return [(ref, i.topic) for i in step.problems for ref in i.ids]


def test_full_check_reports_the_rule_engine_findings_once(ws):
    result = run_task("Full check", ws)
    assert _requirement_problems(result) == [
        # One line for both: the same finding, nothing else differs. REQ-9 "is able to set a new password".
        ("REQ-1", "finding.missing_expected_result"), ("REQ-9", "finding.missing_expected_result"),
        ("REQ-1", "finding.missing_error_handling"),
        ("REQ-4", "finding.contradiction"),  # REQ-4 vs REQ-7: one line, not one per requirement
        ("REQ-5", "finding.ambiguous_wording"),  # other terms: a line of its own
        ("REQ-6", "finding.ambiguous_wording"),
    ]
    step = result.steps[0]
    assert step.problems[2].params == {"related": "REQ-7", "terms": "“at least 8 characters” ↔ “at least 10 characters”"}
    assert step.summary.params == {"checked": "9", "contradiction": "1", "ambiguous_wording": "2",
                                   "missing_error_handling": "1", "missing_expected_result": "2"}
    assert step.recommendations[0].params == {"ids": "REQ-1, REQ-4, REQ-5, REQ-6, REQ-7, REQ-9"}
    # The same findings stored twice are not reported twice.
    doubled = ws.model_copy(update={"findings": ws.findings + ws.findings})
    assert _requirement_problems(run_task("Full check", doubled)) == _requirement_problems(result)


def test_requirement_findings_follow_status_source_and_scope(ws):
    resolved = [f.model_copy(update={"status": ClarificationStatus.RESOLVED}) if f.requirement_id == "REQ-5"
                else f.model_copy(update={"source": Source.AI}) if f.requirement_id == "REQ-6" else f
                for f in ws.findings]
    result = run_task("find contradictions and ambiguities", ws.model_copy(update={"findings": resolved}))
    assert [ref for ref, _ in _requirement_problems(result)] == ["REQ-1", "REQ-9", "REQ-1", "REQ-4"]
    # A contradiction belongs to both requirements of the pair.
    assert _requirement_problems(run_task("Найди противоречия в REQ-7", ws)) == [("REQ-4", "finding.contradiction")]
    assert _requirement_problems(run_task("Перевір вимоги REQ-2", ws)) == []


@pytest.mark.parametrize(("fixture", "expected"), [
    # Known examples of the QA agent evaluation (2026-10-16).
    ("03_checkout_ru", [("REQ-1", "finding.missing_expected_result"), ("REQ-5", "finding.missing_expected_result"),
                        ("REQ-2", "finding.ambiguous_wording"), ("REQ-3", "finding.contradiction"),
                        ("REQ-5", "finding.missing_error_handling")]),
    ("24_uk_units_ranges", [("REQ-1", "finding.contradiction")]),
])
def test_full_check_reports_findings_of_known_documents(fixture, expected):
    text = json.loads((FIXTURES_DIR / f"{fixture}.json").read_text(encoding="utf-8"))["requirements"]
    result = analyze_requirements(extract_requirements(text))
    workspace = Workspace(document_hash="doc", requirements=result.requirements, findings=result.findings)
    assert _requirement_problems(run_task("Полная проверка", workspace)) == expected


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
    # Draft test cases only: traceability has nothing but "not Approved" lines.
    assert scoped.problems == [] and {i.ref for i in scoped.approval} == {"REQ-1"}
    assert len(whole.approval) > len(scoped.approval)


# --- One line per problem, "not Approved" apart -------------------------------

def test_merge_drops_mirror_lines_and_joins_identical_remarks():
    items = [
        Item(key="critic.step_generic", params={"steps": "1, 2"}, ref="TC-1", topic="critic.criterion.steps"),
        Item(key="critic.expectation_conflict", params={"ids": "TC-3", "values": "9"}, ref="TC-2"),
        Item(key="critic.step_generic", params={"steps": "2"}, ref="TC-3", topic="critic.criterion.steps"),
        Item(key="critic.expectation_conflict", params={"ids": "TC-2", "values": "9"}, ref="TC-3"),
        Item(key="critic.expectation_conflict", params={"ids": "TC-2", "values": "10"}, ref="TC-3"),
        Item(key="critic.step_generic", params={"steps": "1, 2"}, ref="TC-4", topic="critic.criterion.steps"),
    ]
    before = [i.model_copy(deep=True) for i in items]
    merged = tasks._merge(items)
    assert [(i.key, i.ids, i.params) for i in merged] == [
        ("critic.step_generic", ["TC-1", "TC-4"], {"steps": "1, 2"}),  # same remark: one line, both IDs
        ("critic.expectation_conflict", ["TC-2"], {"ids": "TC-3", "values": "9"}),  # names both sides
        ("critic.step_generic", ["TC-3"], {"steps": "2"}),  # other steps: another remark
        ("critic.expectation_conflict", ["TC-3"], {"ids": "TC-2", "values": "10"}),  # another value
    ]
    assert merged[1].mentions == {"TC-2", "TC-3"}
    assert items == before  # the tools' own lines are not changed


def _atoms(tool: str, items: list[Item]) -> set[tuple]:
    """One entry per affected ID: tool (the source), key (the type), topic, terms, params, IDs named."""
    out = set()
    for item in items:
        named = {i.strip() for i in item.params.get("ids", "").split(",") if i.strip()}
        rest = tuple(sorted((k, v) for k, v in item.params.items() if k != "ids"))
        out |= {(tool, item.key, item.topic, tuple(item.terms), rest, frozenset({ref, *named}))
                for ref in item.ids or [""]}
    return out


@pytest.mark.parametrize("name", [d.name for d in load_gold().documents])
def test_merging_keeps_every_unique_finding_with_its_type_ids_and_source(name):
    gold = load_gold()
    doc = next(d for d in gold.documents if d.name == name)
    workspace = build_workspace(doc.text(), doc.name, doc.language)
    result = run_task(gold.task, workspace)
    lines = 0
    for step in result.steps:
        raw = tasks._RUNNERS[step.tool](result.plan, workspace.model_copy(deep=True), None)
        for kind in ("problems", "unknowns"):
            before, after = getattr(raw, kind), getattr(step, kind)
            assert _atoms(step.tool, after) == _atoms(step.tool, before)
            assert {i for item in after for i in item.mentions} == {i for item in before for i in item.mentions}
            assert len(after) <= len(before)
            lines += len(before) - len(after)
        assert step.approval == raw.approval and step.recommendations == raw.recommendations
    assert lines > 0  # every document repeats some remark


def test_not_approved_lines_are_summed_up_apart_from_the_problems(ws):
    result = run_task("Full check", ws)
    status_keys = {"qatask.coverage.missing", "qatask.trace.not_approved", "qatask.suites.no_approved"}
    assert not status_keys & {i.key for i in result.problems}
    approval = [(step.tool, item) for step in result.steps for item in step.approval]
    assert {item.key for _, item in approval} == status_keys
    # The summary names the source tools and every requirement of the "not Approved" lines.
    summary = result.approval
    assert summary is not None and summary.key == "qatask.approval.summary_ids"
    assert summary.terms == ["qatask.tool.coverage", "qatask.tool.traceability", "qatask.tool.suites"]
    assert summary.params["ids"].split(", ") == [r.id for r in ws.requirements]
    assert (summary.params["draft"], summary.params["total"]) == (str(len(ws.test_cases)),) * 2
    # A scenario no test case covers, not even a Draft, is still a problem, and stays one after approval.
    gaps = [(i.ids, i.terms) for i in result.problems if i.key == "qatask.coverage.no_test_case"]
    assert gaps
    approved = ws.model_copy(update={"test_cases": [
        tc.model_copy(update={"review_status": ReviewStatus.APPROVED}) for tc in ws.test_cases]})
    after = run_task("Full check", approved)
    assert after.approval is None and not any(step.approval for step in after.steps)
    assert [(i.ids, i.terms) for i in after.problems if i.key == "qatask.coverage.no_test_case"] == gaps
    # Approving hides no problem; Smoke can then name a requirement without a Positive test case.
    assert all(i in after.problems for i in result.problems)
    assert {i.key for i in after.problems if i not in result.problems} == {"qatask.suites.smoke_missing"}


def test_the_page_shows_merged_ids_and_the_summary_apart(ws):
    from qa_task_ui import _line

    item = Item(key="critic.step_generic", params={"steps": "1"}, ref="TC-001", refs=["TC-002"],
                topic="critic.criterion.steps")
    assert _line("en", item).startswith("- **TC-001, TC-002 · ")


def test_a_contradiction_quotes_both_requirements_with_their_lines(ws):
    [line] = [i for i in run_task("Find contradictions", ws).problems if i.key == "qatask.requirements.contradiction"]
    refs = tasks.references(line, ws)
    assert [(r.id, r.kind, r.line) for r in refs] == [("REQ-4", "requirement", 12), ("REQ-7", "requirement", 15)]
    assert tasks.reference_lines("en", line, ws) == [
        "  - REQ-4 (line 12): “The new password must be at least 8 characters long and contain one digit.”",
        "  - REQ-7 (line 15): “The new password must be at least 10 characters long.”",
    ]
    assert tasks.reference_lines("ru", line, ws)[0].startswith("  - REQ-4 (строка 12): «The new password")


def test_vague_wording_and_contradictions_get_a_next_step(ws):
    from qa_task_ui import _lines_with_references

    problems = {i.key: i for i in reversed(run_task("Find contradictions", ws).problems)}  # the first of each
    vague = problems["qatask.requirements.ambiguous_wording"]
    assert tasks.next_step_lines("en", vague) == [
        "  - **Next step:** ask the document author: “What measurable criteria replace: fast, user-friendly?”",
    ]
    # Neither requirement of a contradiction is picked: both have to be agreed on one wording.
    contradiction = problems["qatask.requirements.contradiction"]
    assert tasks.next_step_lines("ru", contradiction) == [
        "  - **Следующий шаг:** согласуйте с автором документа единую формулировку REQ-4, REQ-7; "
        "утверждайте их тест-кейсы только после этого.",
    ]
    # The line itself already says what is missing: no next step that would only repeat it.
    assert tasks.next_step_lines("en", problems["qatask.requirements.missing_expected_result"]) == []
    page = _lines_with_references("en", [contradiction], ws).splitlines()
    assert page[0].startswith("- **REQ-4 · ") and page[1].startswith("  - REQ-4 (line 12)")
    assert page[-1].startswith("  - **Next step:** agree on one wording of REQ-4, REQ-7")


def _result(titles, *steps):
    return tasks.AgentResult(task="Full check", status="done", test_case_titles=titles,
                             steps=[tasks.StepResult(tool=tool, problems=problems) for tool, problems in steps])


def test_compare_problems_matches_test_cases_by_title_not_by_moved_ids():
    vague = Item(key="qatask.requirements.ambiguous_wording", ref="REQ-5", params={"terms": "fast"})
    steps = Item(key="critic.step_generic", ref="TC-014", refs=["TC-015"], params={"steps": "2"})
    impact = Item(key="qatask.impact.test_case", ref="TC-003")
    previous = _result({"TC-014": "decision table R1", "TC-015": "REQ-9: set a new password"},
                       ("requirements", [vague]), ("critic", [steps]), ("impact", [impact]))
    # REQ-5 is fixed and got two more test cases: "decision table R1" is TC-016 now.
    moved = Item(key="critic.step_generic", ref="TC-016", params={"steps": "2"})
    unclear = Item(key="critic.expected_vague", ref="TC-017")
    current = _result({"TC-016": "decision table R1", "TC-017": "REQ-9: set a new password"},
                      ("requirements", []), ("critic", [moved, unclear]), ("impact", []))

    comparison = tasks.compare_problems(previous, current)
    assert [(i.key, i.ids) for i in comparison.resolved] == [
        ("qatask.requirements.ambiguous_wording", ["REQ-5"]), ("critic.step_generic", ["TC-015"]),
    ]
    assert comparison.previous_titles == {"TC-015": "REQ-9: set a new password"}
    assert comparison.still_open == 1 and comparison.new == [unclear]
    assert _counts(comparison) == (2, 1, 1, 0, 0)  # REQ-5, TC-014, TC-015 before; TC-016, TC-017 now
    assert comparison.not_compared == ["impact"]  # its lines are about one pair of versions


def _counts(comparison):
    return (comparison.resolved_count, comparison.still_open, comparison.new_count,
            comparison.unmatched_before_count, comparison.unmatched_now_count)


def test_compare_problems_counts_each_test_case_of_a_grouped_line():
    titles = {"TC-001": "a", "TC-002": "b", "TC-003": "c", "TC-004": "d"}
    previous = _result(titles, ("critic", [Item(key="critic.step_generic", ref="TC-001", refs=["TC-002", "TC-003"])]))
    current = _result(titles, ("critic", [Item(key="critic.step_generic", ref="TC-002", refs=["TC-004"])]))

    comparison = tasks.compare_problems(previous, current)
    # 3 problems before = 2 resolved + 1 still open; 2 now = 1 still open + 1 new.
    assert _counts(comparison) == (2, 1, 1, 0, 0)
    assert [i.ids for i in comparison.resolved] == [["TC-001", "TC-003"]]
    assert [i.ids for i in comparison.new] == [["TC-004"]]  # not hidden in the still open line


def test_compare_problems_does_not_guess_between_test_cases_of_the_same_title():
    titles = {"TC-001": "Login", "TC-002": "Login", "TC-003": "Logout"}
    vague = Item(key="critic.expected_vague", ref="TC-003")
    previous = _result(titles, ("critic", [Item(key="critic.step_generic", ref="TC-001", refs=["TC-002"]), vague]))
    current = _result(titles, ("critic", [Item(key="critic.step_generic", ref="TC-002")]))

    comparison = tasks.compare_problems(previous, current)
    # TC-001 is not reported as fixed: by title it cannot be told apart from TC-002.
    assert _counts(comparison) == (1, 0, 0, 2, 1)
    assert comparison.resolved == [vague]
    assert [i.ids for i in comparison.unmatched_before] == [["TC-001", "TC-002"]]
    assert [i.ids for i in comparison.unmatched_now] == [["TC-002"]]
    assert comparison.current_titles == {"TC-002": "Login"}


def test_compare_problems_with_a_result_saved_without_test_case_titles():
    vague = Item(key="qatask.requirements.ambiguous_wording", ref="REQ-5")
    previous = tasks.AgentResult.model_validate({
        "task": "Full check", "status": "done",  # result.json written before test_case_titles
        "steps": [{"tool": "requirements", "problems": [vague.model_dump()]},
                  {"tool": "critic", "problems": [{"key": "critic.step_generic", "ref": "TC-014"}]}],
    })
    current = _result({"TC-016": "decision table R1"},
                      ("requirements", []), ("critic", [Item(key="critic.step_generic", ref="TC-016")]))

    comparison = tasks.compare_problems(previous, current)
    # Requirements are still compared; test cases are unmatched instead of "TC-014 resolved, TC-016 new".
    assert _counts(comparison) == (1, 0, 0, 1, 1)
    assert comparison.resolved == [vague]
    assert [i.ids for i in comparison.unmatched_before + comparison.unmatched_now] == [["TC-014"], ["TC-016"]]


def test_references_name_test_cases_and_skip_what_the_document_lacks(ws):
    ws.test_cases[0].title = "Reset *link* " + "x" * 300
    item = Item(key="critic.step_generic", ref="TC-001", params={"related": "REQ-99, REQ-1"})
    [tc, req] = tasks.references(item, ws)
    assert (tc.id, tc.requirement_id, tc.status) == ("TC-001", "REQ-1", ReviewStatus.DRAFT)
    assert len(tc.text) == tasks.REFERENCE_TEXT_LENGTH and tc.text.endswith("…")
    assert req.id == "REQ-1"
    first = tasks.reference_lines("en", item, ws)[0]
    assert first.startswith("  - TC-001 (Draft, tests REQ-1): “Reset \\*link\\* xxx")  # shown as written
    # Change Impact names IDs of the previous version: nothing is quoted for them.
    assert tasks.references(Item(key="qatask.impact.test_case", ref="TC-001"), ws) == []


def test_a_line_on_many_test_cases_quotes_only_the_first_ones(ws):
    ids = [tc.id for tc in ws.test_cases[:tasks.MAX_REFERENCES + 3]]
    lines = tasks.reference_lines("en", Item(key="critic.step_generic", ref=ids[0], refs=ids[1:]), ws)
    assert len(lines) == tasks.MAX_REFERENCES + 1
    assert lines[-1] == "  - …and 3 more"


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


def test_approval_of_conflicting_test_cases_is_not_proposed(ws):
    # TC-007 (REQ-4, at least 8) accepts 9 characters, TC-012 (REQ-7, at least 10) rejects them.
    result = run_task("Approve TC-007 and TC-012", ws)
    assert result.action is None
    assert result.plan.action_conflicts == ["TC-007", "TC-012"]
    [critic] = result.steps
    # One line for the pair, naming both test cases.
    [conflict] = [i for i in critic.problems if i.topic == "critic.criterion.conflict"]
    assert (conflict.key, conflict.ref, conflict.mentions) == ("critic.expectation_conflict", "TC-007",
                                                               {"TC-007", "TC-012"})
    # Other test cases of the task are still proposed; returning to Draft is not held back.
    result = run_task("approve TC-001 and TC-007", ws)
    assert result.action == ProposedAction(test_case_ids=["TC-001"], status=ReviewStatus.APPROVED)
    assert result.plan.action_conflicts == ["TC-007"]
    result = run_task("TC-007 back to draft", ws)
    assert result.action == ProposedAction(test_case_ids=["TC-007"], status=ReviewStatus.DRAFT)
    assert result.plan.action_conflicts == []


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


def test_page_quotes_the_requirements_under_a_problem(example_text):
    at = _task_mode(example_text)
    at.text_area(key="qa_task_text").input("Find contradictions").run()
    _button(at, "qa_task_run").click().run()
    assert not at.exception
    assert any("possible contradiction" in m.value.lower()
               and "  - REQ-7 (line 15): “The new password must be at least 10 characters long.”" in m.value
               for m in at.markdown)


def test_page_reports_an_unsupported_task(example_text):
    at = _task_mode(example_text)
    at.text_area(key="qa_task_text").input("Delete everything").run()
    _button(at, "qa_task_run").click().run()
    assert not at.exception
    assert any("not supported" in w.value for w in at.warning)


def _rerun(at: AppTest, task: str) -> AppTest:
    """Back on the task mode (leaving the page clears its widgets), the same or another task is run."""
    goto(at, "qa_agent")
    at.segmented_control(key="qa_mode").set_value("task").run()
    at.text_area(key="qa_task_text").input(task).run()
    _button(at, "qa_task_run").click().run()
    assert not at.exception
    return at


def _analyze(at: AppTest, text: str) -> None:
    home(at).text_area(key="requirements_text").input(text).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception


def test_page_shows_what_an_edit_of_the_document_resolved(example_text):
    at = _task_mode(example_text)
    at.text_area(key="qa_task_text").input("Full check").run()
    _button(at, "qa_task_run").click().run()
    assert "Since the previous run" not in [s.value for s in at.subheader]  # nothing to compare with yet
    assert not any("previous check" in c.value for c in at.caption)

    # The contradiction REQ-4 ↔ REQ-7 fixed, a vague requirement added; the title (first line) stays.
    edited = example_text.replace("at least 10 characters", "at least 8 characters").replace(
        "set a new password.", "set a new password.\n- REQ-10: The page should be fast.")
    _analyze(at, edited)
    _rerun(at, "  Full   check ")  # the same task, spaced differently
    assert "Since the previous run" in [s.value for s in at.subheader]
    summary = next(w.value for w in at.warning if "previous check" in w.value)  # warning: there are new problems
    assert "resolved 2, still open 16, new 2; could not be compared 1 before / 1 now" in summary
    lines = next(m.value for m in at.markdown if m.value.startswith("**Resolved (2)**"))
    resolved, new = lines.split("**New (2)**")
    assert "**REQ-4 · Possible contradiction**: conflicts with REQ-7" in resolved
    assert "  - TC-007 at the previous check: “REQ-4: boundary values for “at least 8 characters””" in resolved
    assert "**REQ-10 · Ambiguous wording**: vague wording: fast" in new
    # TC-011 got another title (REQ-7 was reworded): neither resolved nor new, but listed as not comparable.
    assert "TC-011" not in lines
    assert any(e.label == "Could not be compared (1 before, 1 now)" for e in at.expander)
    assert any("TC-011 now: “REQ-7: The new password must be at least 8 characters long.”" in m.value
               for m in at.markdown)
    assert any(c.value == "Not compared: Change Impact." for c in at.caption)


def test_page_compares_only_the_same_document_and_task(example_text):
    at = _task_mode(example_text)
    at.text_area(key="qa_task_text").input("Find contradictions").run()
    _button(at, "qa_task_run").click().run()
    _rerun(at, "Find contradictions")  # nothing changed
    summary = next(i.value for i in at.info if "previous check" in i.value)
    assert "resolved 0, still open 6, new 0; could not be compared 0 before / 0 now" in summary

    _rerun(at, "Full check")
    assert "Since the previous run" not in [s.value for s in at.subheader]
    assert any(c.value == "Not compared with the previous check: it had another task." for c in at.caption)

    _analyze(at, example_text.replace("# Password Reset", "# Account Recovery"))  # another title: another document
    _rerun(at, "Full check")
    assert "Since the previous run" not in [s.value for s in at.subheader]
    assert any(c.value == "Not compared with the previous check: it was of another document or project."
               for c in at.caption)


def test_rerun_identity_of_document_and_task():
    from qa_task_ui import PreviousCheck, _same_document, _same_task

    result = AgentResult(task="Full check", document_hash="h1", status="done")
    titled = PreviousCheck("default", "Spec", result, "10:00:00")
    assert _same_document(titled, "default", Workspace(document_hash="h2", title="Spec"))  # a new version
    assert not _same_document(titled, "default", Workspace(document_hash="h1", title="Other"))
    assert not _same_document(titled, "other-project", Workspace(document_hash="h2", title="Spec"))
    untitled = PreviousCheck("default", "", result, "10:00:00")
    assert _same_document(untitled, "default", Workspace(document_hash="h1"))
    assert not _same_document(untitled, "default", Workspace(document_hash="h2"))
    assert _same_task("Full check", " Full\n check ")
    assert not _same_task("Full check", "full check of REQ-1")
