from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import ReviewStatus, Source, TestType, Workspace
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.test_generator import generate_test_cases, next_test_case_id


def workspace_for(text: str) -> Workspace:
    result = analyze_requirements(extract_requirements(text))
    return Workspace(requirements=result.requirements, findings=result.findings)


def test_every_requirement_gets_draft_test_cases(example_text):
    ws = workspace_for(example_text)
    cases = generate_test_cases(ws)
    assert {tc.requirement_id for tc in cases} == {r.id for r in ws.requirements}
    assert all(tc.review_status == ReviewStatus.DRAFT and tc.source == Source.RULE for tc in cases)
    ids = [tc.id for tc in cases]
    assert len(ids) == len(set(ids))
    assert ids[0] == "TC-001"


def test_positive_case_quotes_requirement():
    ws = workspace_for("REQ-1: The system must send a reset link to the registered email address.")
    [case] = generate_test_cases(ws)
    assert case.test_type == TestType.POSITIVE
    assert "The system must send a reset link to the registered email address." in case.expected_result
    assert case.clarification_questions == []


def test_open_findings_become_questions_and_assumptions():
    ws = workspace_for("REQ-1: The reset page should load fast.")
    [case] = generate_test_cases(ws)
    assert any('"fast"' in q for q in case.clarification_questions)
    assert case.assumptions


def test_boundary_and_equivalence_cases_from_numbers():
    ws = workspace_for("REQ-1: The new password must be at least 8 characters long.")
    types = [tc.test_type for tc in generate_test_cases(ws)]
    assert types == [TestType.POSITIVE, TestType.BOUNDARY, TestType.EQUIVALENCE]
    boundary = generate_test_cases(ws)[1]
    assert "7 characters → rejected (invalid)" in boundary.expected_result


def test_decision_table_cases_only_for_specified_outcomes():
    ws = workspace_for("REQ-8: If the email address is not registered, the system shows a generic message.")
    cases = generate_test_cases(ws)
    assert [tc.test_type for tc in cases] == [TestType.DECISION_TABLE]
    assert cases[0].expected_result == "the system shows a generic message"
    assert any("1" in q for q in cases[0].clarification_questions)  # one unspecified combination


def test_generated_text_follows_language():
    ws = workspace_for("REQ-1: The system must save drafts.")
    [case] = generate_test_cases(ws, "uk")
    assert "Система поводиться" in case.expected_result


def test_next_id_continues_after_existing():
    ws = workspace_for("REQ-1: The system must save drafts.")
    ws.test_cases = generate_test_cases(ws)
    assert next_test_case_id(ws.test_cases) == "TC-002"
    ws.test_cases[0].id = "TC-041"
    assert next_test_case_id(ws.test_cases) == "TC-042"
