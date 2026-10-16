"""Generate missing test cases: the existing generator fills only the gaps a QA task found,
as Drafts, without duplicates, without changing existing test cases and without guessing
expected results of requirements that need clarification."""

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto, home
from spec_to_test.evaluation.qa_agent_eval import load_gold
from spec_to_test.i18n import clarification_question
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import (
    ClarificationStatus,
    FindingType,
    ReviewStatus,
    Source,
    TestType,
    Workspace,
)
from spec_to_test.qa_agent import missing_cases
from spec_to_test.qa_agent.missing_cases import gap_requirements, generate_missing
from spec_to_test.qa_agent.on_change import build_workspace
from spec_to_test.qa_agent.tasks import StepResult, run_task
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.scenario_coverage import ScenarioCategory
from spec_to_test.test_generator import generate_test_cases

APP_PATH = str(PROJECT_ROOT / "app.py")


@pytest.fixture
def ws(example_text) -> Workspace:
    """password_reset.md with only its positive and decision table cases, none for REQ-2."""
    result = analyze_requirements(extract_requirements(example_text))
    workspace = Workspace(document_hash="doc", title="Password reset", requirements=result.requirements,
                          findings=result.findings)
    workspace.test_cases = [tc for tc in generate_test_cases(workspace, "en")
                            if tc.test_type in (TestType.POSITIVE, TestType.DECISION_TABLE)
                            and tc.requirement_id != "REQ-2"]
    return workspace


def _of(generation, req_id):
    return next(r for r in generation.requirements if r.requirement_id == req_id)


def test_the_gaps_come_from_the_check_result(ws):
    result = run_task("Full check", ws)
    assert gap_requirements(result, ws) == ["REQ-2", "REQ-3", "REQ-4", "REQ-6", "REQ-7", "REQ-8"]
    # A failed step's lines are not used, and IDs are in document order.
    failed = result.model_copy(update={"steps": [StepResult(tool="coverage", status="error")]})
    assert gap_requirements(failed, ws) == []
    assert gap_requirements(run_task("Check the quality of the test cases", ws), ws) == []


def test_a_requirement_without_test_cases_gets_what_the_generator_makes(ws):
    generation = generate_missing(ws, ["REQ-2"])
    expected = generate_test_cases(Workspace(requirements=[ws.requirement("REQ-2")], findings=ws.findings))
    assert [(tc.title, tc.steps, tc.expected_result) for tc in generation.created] == \
        [(tc.title, tc.steps, tc.expected_result) for tc in expected]
    [case] = generation.created
    assert case.id == "TC-016"  # after the last existing ID (TC-015)
    assert case.requirement_id == "REQ-2"
    assert case.review_status == ReviewStatus.DRAFT
    assert case.source == Source.RULE
    assert case.expected_result.startswith("The system behaves as stated in the requirement: “The system must send")
    report = _of(generation, "REQ-2")
    assert (report.tests_before, report.tests_after) == (0, 1)
    assert report.missing_before == [ScenarioCategory.HAPPY_PATH] and report.missing_after == []
    assert report.approved_percent == 0.0  # a Draft is not coverage until it is Approved


def test_only_the_missing_categories_are_filled(ws):
    generation = generate_missing(ws, ["REQ-3"])
    # REQ-3 has its positive case: only a boundary case is added, not another positive or equivalence case.
    [case] = generation.created
    assert case.test_type == TestType.BOUNDARY
    assert case.title == "REQ-3: boundary values for “30 minutes”"
    report = _of(generation, "REQ-3")
    assert report.missing_before == [ScenarioCategory.BOUNDARY, ScenarioCategory.STATE_TRANSITIONS]
    # State transitions: the generator has no case for them; reported, not invented.
    assert report.missing_after == [ScenarioCategory.STATE_TRANSITIONS]


def test_categories_the_generator_cannot_make_are_reported_not_invented(ws):
    generation = generate_missing(ws, ["REQ-6", "REQ-8"])
    assert generation.created == []
    assert _of(generation, "REQ-6").missing_after == [ScenarioCategory.NEGATIVE, ScenarioCategory.STATE_TRANSITIONS]
    assert _of(generation, "REQ-8").missing_after == [ScenarioCategory.HAPPY_PATH]


def test_a_second_run_adds_nothing(ws):
    ids = gap_requirements(run_task("Full check", ws), ws)
    first = generate_missing(ws, ids)
    assert len(first.created) == 4
    assert len({tc.id for tc in first.created}) == 4
    assert {tc.id for tc in first.created}.isdisjoint(tc.id for tc in ws.test_cases)
    ws.test_cases += first.created
    assert generate_missing(ws, ids).created == []
    assert gap_requirements(run_task("Full check", ws), ws) == ["REQ-3", "REQ-6", "REQ-8"]  # by hand only


def test_a_case_already_written_under_another_type_is_not_added_again(ws):
    boundary = next(tc for tc in generate_test_cases(ws) if tc.title == "REQ-3: boundary values for “30 minutes”")
    # The same title, written as a positive case: it does not exercise the boundary, yet it is that case.
    ws.test_cases.append(boundary.model_copy(update={"id": "TC-050", "test_type": TestType.POSITIVE,
                                                     "steps": ["Wait.", "Open the link."]}))
    assert generate_missing(ws, ["REQ-3"]).created == []
    # The same steps and expected result under another title is a duplicate as well.
    ws.test_cases[-1] = boundary.model_copy(update={"id": "TC-050", "title": "Link expiry"})
    assert generate_missing(ws, ["REQ-3"]).created == []


def test_existing_and_approved_test_cases_are_not_changed(ws):
    ws.test_cases[0] = ws.test_cases[0].model_copy(update={"review_status": ReviewStatus.APPROVED,
                                                           "reviewer_comment": "checked"})
    before = ws.model_copy(deep=True)
    generation = generate_missing(ws, [r.id for r in ws.requirements])
    assert generation.created
    assert ws == before  # the caller adds the new cases; nothing else is touched


def test_a_contradiction_leaves_the_expected_result_to_clarify(ws):
    generation = generate_missing(ws, ["REQ-4", "REQ-7"])
    assert [tc.requirement_id for tc in generation.created] == ["REQ-4", "REQ-7"]
    for case in generation.created:
        assert case.expected_result == (f"Not defined yet: {case.requirement_id} needs clarification first "
                                        "(Possible contradiction). Answer the clarification questions, then "
                                        "write the expected result.")
        assert "accepted" not in case.expected_result and "rejected" not in case.expected_result
        finding = next(f for f in ws.open_findings_for(case.requirement_id) if f.type == FindingType.CONTRADICTION)
        assert clarification_question(finding, "en") in case.clarification_questions
        assert case.review_status == ReviewStatus.DRAFT
    assert _of(generation, "REQ-4").unclear == [FindingType.CONTRADICTION]


def test_a_resolved_finding_no_longer_holds_the_expected_result_back(ws):
    ws.findings = [f.model_copy(update={"status": ClarificationStatus.RESOLVED})
                   if f.type == FindingType.CONTRADICTION else f for f in ws.findings]
    [case, _] = generate_missing(ws, ["REQ-4", "REQ-7"]).created
    assert "8 characters → accepted" in case.expected_result


@pytest.mark.parametrize(("text", "kind"), [
    ("REQ-1: The reset page should load fast.", FindingType.AMBIGUOUS_WORDING),
    ("REQ-1: The user is able to set a new password.", FindingType.MISSING_EXPECTED_RESULT),
])
def test_vague_or_resultless_requirements_get_no_guessed_result(text, kind):
    result = analyze_requirements(extract_requirements(text))
    workspace = Workspace(requirements=result.requirements, findings=result.findings)
    [case] = generate_missing(workspace, ["REQ-1"]).created
    assert case.expected_result.startswith("Not defined yet: REQ-1 needs clarification first")
    assert case.clarification_questions  # what to ask, from the generator
    assert kind in _of(generate_missing(workspace, ["REQ-1"]), "REQ-1").unclear


def test_cases_are_written_in_the_requested_language():
    result = analyze_requirements(extract_requirements("REQ-1: Пароль должен содержать не менее 8 символов."))
    workspace = Workspace(requirements=result.requirements, findings=result.findings)
    created = generate_missing(workspace, ["REQ-1"], "ru").created
    assert [tc.test_type for tc in created] == [TestType.POSITIVE, TestType.BOUNDARY, TestType.EQUIVALENCE]
    assert created[0].expected_result.startswith("Система ведёт себя так, как указано в требовании")


def test_freshly_generated_eval_documents_need_nothing_more():
    """Every gap a Full check reports on the eval documents is one the generator cannot fill."""
    for doc in load_gold().documents:
        workspace = build_workspace(doc.text(), doc.name, doc.language)
        ids = gap_requirements(run_task("Full check", workspace), workspace)
        assert generate_missing(workspace, ids, doc.language).created == [], doc.name


def test_unknown_requirement_ids_are_ignored(ws):
    assert generate_missing(ws, ["REQ-99"]) == missing_cases.MissingGeneration()


# --- Page ---------------------------------------------------------------------

def _button(at: AppTest, key: str):
    return next(b for b in at.button if b.key == key)


def test_page_generates_the_missing_cases_and_shows_coverage(example_text):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    workspace: Workspace = at.session_state["workspace"]
    workspace.test_cases = [tc for tc in workspace.test_cases if tc.requirement_id != "REQ-2"]
    goto(at, "qa_agent")
    at.segmented_control(key="qa_mode").set_value("task").run()
    at.text_area(key="qa_task_text").input("Full check").run()
    _button(at, "qa_task_run").click().run()
    assert not at.exception
    assert any("REQ-2" in c.value and "Draft" in c.value for c in at.caption)

    _button(at, "qa_task_generate").click().run()
    assert not at.exception
    created = [tc for tc in at.session_state["workspace"].test_cases if tc.requirement_id == "REQ-2"]
    assert [tc.review_status for tc in created] == [ReviewStatus.DRAFT]
    assert any(f"Created 1 test case(s) as Draft: {created[0].id}" in s.value for s in at.success)
    assert any("REQ-2: test cases 0 → 1" in m.value for m in at.markdown)
    assert any("REQ-3: the generator has no case for State Transitions" in m.value for m in at.markdown)
    assert not any(b.key == "qa_task_generate" for b in at.button)  # done for this result


def test_page_says_when_there_is_nothing_to_add(example_text):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    count = len(at.session_state["workspace"].test_cases)
    goto(at, "qa_agent")
    at.segmented_control(key="qa_mode").set_value("task").run()
    at.text_area(key="qa_task_text").input("Full check").run()
    _button(at, "qa_task_run").click().run()
    _button(at, "qa_task_generate").click().run()
    assert not at.exception
    assert any("Nothing added" in i.value for i in at.info)
    assert len(at.session_state["workspace"].test_cases) == count
