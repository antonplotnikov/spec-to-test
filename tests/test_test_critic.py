import json

import pytest

from conftest import PROJECT_ROOT
from spec_to_test.i18n import t
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import Finding, FindingType, Requirement, Severity, TestCase, TestType, Workspace
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.test_critic import critique, expectation_conflicts
from spec_to_test.test_generator import generate_test_cases

REQ = Requirement(id="REQ-1", text="The password must be at least 8 characters long.")
GOOD_STEPS = ["Open the registration form.", "Enter a password of 8 characters and submit."]


def tc(n: int = 1, steps=None, expected="The account is created.", test_type=TestType.POSITIVE,
       requirement_id="REQ-1") -> TestCase:
    return TestCase(id=f"TC-{n}", requirement_id=requirement_id, title="Valid password", test_type=test_type,
                    steps=steps or GOOD_STEPS, expected_result=expected)


def codes(case: TestCase, *others: TestCase, findings=()) -> dict[str, bool]:
    ws = Workspace(requirements=[REQ], test_cases=[case, *others], findings=list(findings))
    return {i.code: i.unknown for i in critique(case, ws)}


def test_concrete_test_case_has_no_issues():
    assert codes(tc()) == {}


def test_steps_must_be_concrete():
    assert "step_placeholder" in codes(tc(steps=[t("tests.new_step", "ru"), *GOOD_STEPS]))
    assert "step_vague" in codes(tc(steps=["Enter an appropriate password.", *GOOD_STEPS]))
    assert "step_too_short" in codes(tc(steps=["Submit", *GOOD_STEPS]))
    generic = [t("tc.step_prepare", req="REQ-1"), t("tc.step_perform"), t("tc.step_observe")]
    ws = Workspace(requirements=[REQ], test_cases=[tc(steps=generic)])
    [issue] = [i for i in critique(ws.test_cases[0], ws) if i.criterion == "steps"]
    assert issue.code == "step_generic" and issue.params == {"steps": "1, 2, 3"}


def test_quoted_capability_step_is_not_generic():
    stated = t("tc.step_perform_stated", req="REQ-1", action="request a password reset from the login page")
    ws = Workspace(requirements=[REQ], test_cases=[tc(steps=[t("tc.step_prepare", req="REQ-1"), stated])])
    [issue] = [i for i in critique(ws.test_cases[0], ws) if i.criterion == "steps"]
    assert issue.code == "step_generic" and issue.params == {"steps": "1"}


def test_expected_result_must_be_checkable():
    assert "expected_placeholder" in codes(tc(expected=t("tests.new_expected")))
    assert "expected_vague" in codes(tc(expected="The form works properly."))
    assert "expected_not_observable" in codes(tc(expected="Everything is fine."))


def test_open_outcomes_and_missing_data_are_unknown():
    assert codes(tc(expected=f"7 characters → {t('design.unspecified')}", test_type=TestType.BOUNDARY)) == {
        "expected_unspecified": True
    }
    assert codes(tc(requirement_id="REQ-9"))["requirement_missing"] is True
    finding = Finding(requirement_id="REQ-1", type=FindingType.MISSING_EXPECTED_RESULT, severity=Severity.HIGH)
    assert codes(tc(), findings=[finding])["requirement_no_expected"] is True


def test_test_case_about_something_else_is_flagged():
    other = TestCase(id="TC-1", requirement_id="REQ-1", title="Export report", test_type=TestType.POSITIVE,
                     steps=["Open the reports page.", "Click Export."], expected_result="A PDF file is downloaded.")
    assert "requirement_mismatch" in codes(other)


def test_duplicates_are_reported_with_ids():
    ws = Workspace(requirements=[REQ], test_cases=[tc(1), tc(2), tc(3, expected="The account is not created.")])
    [issue] = critique(ws.test_cases[0], ws)
    assert issue.code == "duplicate" and issue.params == {"ids": "TC-2"}


def test_invented_values_and_messages_are_flagged():
    result = codes(tc(expected="The account is created within 5 seconds and “Welcome!” is shown."))
    assert set(result) == {"invented_value", "invented_text"}
    # Probe values of a boundary test are derived by the test design, not invented.
    assert codes(tc(expected="7 characters → rejected", test_type=TestType.BOUNDARY)) == {}


def test_generated_cases_only_get_honest_findings():
    ws = Workspace(requirements=[REQ])
    ws.test_cases = generate_test_cases(ws)
    for case in ws.test_cases:
        found = {i.code for i in critique(case, ws)}
        assert found <= {"step_generic", "expected_unspecified"}, (case.id, found)


def test_probe_values_differing_by_sign_or_comparator_are_not_duplicates():
    def case(n: int, step: str) -> TestCase:
        return TestCase(id=f"TC-{n}", requirement_id="REQ-1", title="Temperature", test_type=TestType.BOUNDARY,
                        steps=[step], expected_result="The value is rejected.")

    for a, b in [("Set the temperature to -6 degrees.", "Set the temperature to 6 degrees."),
                 ("Enter a temperature > 5 degrees.", "Enter a temperature < 5 degrees.")]:
        assert "duplicate" not in codes(case(1, a), case(2, b))
    assert "duplicate" in codes(case(1, "Set the temperature to −6 degrees."), case(2, "Set the temperature to -6 degrees."))


def test_generated_cases_quoting_the_requirement_match_it():
    for text in ("The upload size must not exceed 10 MB.", "The order total must be at most 1,000 USD."):
        ws = Workspace(requirements=[Requirement(id="REQ-1", text=text)])
        ws.test_cases = generate_test_cases(ws)
        for case in ws.test_cases:
            assert "requirement_mismatch" not in {i.code for i in critique(case, ws)}, (text, case.title)


def test_hidden_is_an_observable_expected_result():
    for text in ("If the user is an administrator, the system must show the Delete button, "
                 "otherwise the button must be hidden.",
                 "Если пользователь администратор, система должна показать кнопку удаления, "
                 "иначе кнопка должна быть скрыта.",
                 "Якщо користувач адміністратор, система повинна показати кнопку видалення, "
                 "інакше кнопка має бути прихована."):
        ws = Workspace(requirements=[Requirement(id="REQ-1", text=text)])
        ws.test_cases = generate_test_cases(ws)
        assert [c.test_type for c in ws.test_cases] == [TestType.DECISION_TABLE] * 2
        for case in ws.test_cases:
            assert "expected_not_observable" not in {i.code for i in critique(case, ws)}, case.expected_result
    assert "expected_not_observable" in codes(tc(expected="Everything is fine."))


# --- Conflicting expectations --------------------------------------------------

def _analyzed(text: str, lang: str = "en") -> Workspace:
    result = analyze_requirements(extract_requirements(text))
    ws = Workspace(requirements=result.requirements, findings=result.findings)
    ws.test_cases = generate_test_cases(ws, lang)
    return ws


def _conflicts(ws: Workspace) -> dict[str, dict[str, list[str]]]:
    return {case.id: found for case in ws.test_cases if (found := expectation_conflicts(case, ws))}


@pytest.mark.parametrize(("source", "pair", "value"), [
    ("password_reset.md", ("TC-007", "TC-012"), "9 characters"),
    ("03_checkout_ru", ("TC-004", "TC-008"), "500 рублей"),
    ("24_uk_units_ranges", ("TC-002", "TC-005"), "9 символів"),
])
def test_conflicts_from_the_evaluation_are_found(source, pair, value):
    if source.endswith(".md"):
        ws = _analyzed((PROJECT_ROOT / "examples" / source).read_text(encoding="utf-8"))
    else:
        fixture = PROJECT_ROOT / "src" / "spec_to_test" / "evaluation" / "fixtures" / f"{source}.json"
        data = json.loads(fixture.read_text(encoding="utf-8"))
        ws = _analyzed(data["requirements"], data["language"])
    a, b = pair
    assert _conflicts(ws) == {a: {b: [value]}, b: {a: [value]}}
    case = next(c for c in ws.test_cases if c.id == a)
    [issue] = [i for i in critique(case, ws) if i.criterion == "conflict"]
    assert issue.code == "expectation_conflict" and not issue.unknown
    assert issue.params == {"ids": b, "values": value}


def test_partial_check_keeps_the_conflict_with_another_requirement():
    # The partial-check note is an assumption, not a precondition, so the cases stay comparable.
    ws = _analyzed("REQ-1: The new password must be at least 8 characters long and contain one digit.\n"
                   "REQ-2: The new password must be at most 7 characters long.")
    assert [f for f in ws.findings if f.type == FindingType.CONTRADICTION]
    assert any(c.assumptions for c in ws.test_cases if c.requirement_id == "REQ-1")
    assert _conflicts(ws)["TC-002"] == {"TC-005": ["7 characters", "8 characters"]}


def _probe(n: int, expected: str, requirement_id: str = "REQ-1", preconditions=()) -> TestCase:
    return TestCase(id=f"TC-{n}", requirement_id=requirement_id, title="Password length", test_type=TestType.BOUNDARY,
                    preconditions=list(preconditions), steps=["Enter a password of the given length and submit."],
                    expected_result=expected)


def test_opposite_outcomes_for_one_requirement_conflict():
    ws = Workspace(requirements=[REQ], test_cases=[
        _probe(1, "7 characters → rejected (invalid)\n8 characters → accepted (valid)"),
        _probe(2, "8 characters → rejected (invalid)"),
    ])
    assert _conflicts(ws) == {"TC-1": {"TC-2": ["8 characters"]}, "TC-2": {"TC-1": ["8 characters"]}}


def test_no_conflict_without_the_same_input_and_conditions():
    ws = Workspace(requirements=[REQ], test_cases=[
        # Positive and negative tests of other values.
        _probe(1, "8 characters → accepted (valid)"),
        _probe(2, "7 characters → rejected (invalid)"),
        # The same outcome is agreement, not a conflict.
        _probe(3, "8 characters → accepted (valid)"),
        # The same value under another precondition is another condition.
        _probe(4, "8 characters → rejected (invalid)", preconditions=["The user is blocked."]),
        # Outcomes not written as "value → accepted / rejected" are not guessed.
        _probe(5, "A password of 8 characters is not accepted."),
    ])
    assert _conflicts(ws) == {}


def test_requirements_not_reported_as_contradicting_are_not_compared():
    # Different contexts (wholesale buyers, administrators) are not a contradiction of the analyzer.
    for text in ("REQ-1: The order total must be at least 500 USD.\n"
                 "REQ-2: For wholesale buyers the order total must be at least 1000 USD.",
                 "REQ-1: The session ends after 15 minutes of inactivity.\n"
                 "REQ-2: The administrator session ends after 5 minutes of inactivity."):
        ws = _analyzed(text)
        assert not [f for f in ws.findings if f.type == FindingType.CONTRADICTION]
        assert _conflicts(ws) == {}
    # Unrelated requirements with the same probe value.
    ws = Workspace(requirements=[REQ, Requirement(id="REQ-2", text="The nickname must be at most 8 characters.")],
                   test_cases=[_probe(1, "9 characters → accepted (valid)"),
                               _probe(2, "9 characters → rejected (invalid)", requirement_id="REQ-2")])
    assert _conflicts(ws) == {}
