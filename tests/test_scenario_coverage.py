import pytest

from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestType, Workspace
from spec_to_test.rtm import Coverage, build_rtm
from spec_to_test.scenario_coverage import ScenarioCategory as C
from spec_to_test.scenario_coverage import categories_of_test_case, scenario_coverage
from spec_to_test.test_generator import _short


def req(text: str) -> Requirement:
    return Requirement(id="REQ-1", text=text)


def tc(
    test_type: TestType, title: str = "Check", expected: str = "Works", n: int = 1,
    status: ReviewStatus = ReviewStatus.APPROVED,
) -> TestCase:
    return TestCase(
        id=f"TC-{n}", requirement_id="REQ-1", title=title, test_type=test_type,
        steps=["Do it"], expected_result=expected, review_status=status,
    )


def test_applicability_comes_from_requirement_text():
    sc = scenario_coverage(req("Only administrators can delete accounts. Locked accounts must stay locked."), [])
    assert sc.applicable == [C.HAPPY_PATH, C.PERMISSIONS, C.STATE_TRANSITIONS]
    assert sc.reasons[C.PERMISSIONS] == "administrators"


def test_happy_path_alone_is_not_full_coverage():
    r = req("The password must be at least 8 characters long.")
    sc = scenario_coverage(r, [tc(TestType.POSITIVE)])
    assert sc.applicable == [C.HAPPY_PATH, C.BOUNDARY]
    assert sc.covered == [C.HAPPY_PATH]
    assert sc.missing == [C.BOUNDARY]
    assert sc.percent == 50.0
    sc = scenario_coverage(r, [tc(TestType.POSITIVE), tc(TestType.BOUNDARY, n=2)])
    assert sc.percent == 100.0


def test_not_applicable_categories_do_not_lower_percent():
    sc = scenario_coverage(req("The system must send a confirmation email."), [tc(TestType.POSITIVE)])
    assert sc.applicable == [C.HAPPY_PATH]
    assert sc.percent == 100.0


def test_uncertainty_is_unknown_not_coverage():
    # No stated behavior: nothing is known to apply, even with a test case.
    sc = scenario_coverage(req("Fast and friendly login page."), [tc(TestType.POSITIVE)])
    assert sc.applicable == [] and sc.covered == []
    assert C.HAPPY_PATH in sc.unknown
    assert sc.percent is None
    # A limit without a value: boundary is Unknown, not applicable or covered.
    sc = scenario_coverage(req("The username length must be limited."), [tc(TestType.BOUNDARY)])
    assert C.BOUNDARY in sc.unknown and C.BOUNDARY not in sc.covered


def test_restating_the_requirement_is_not_coverage():
    r = req("Only administrators can delete accounts.")
    positive = tc(TestType.POSITIVE, title="Admin deletes", expected=r.text)
    assert categories_of_test_case(positive, r) == {C.HAPPY_PATH}
    table = tc(TestType.DECISION_TABLE, expected=f"As stated: {r.text}")
    assert categories_of_test_case(table, r) == set()  # unclassified covers nothing
    denied = tc(TestType.NEGATIVE, title="Guest cannot delete", expected="Access denied")
    assert categories_of_test_case(denied, r) == {C.NEGATIVE, C.PERMISSIONS}


def test_rtm_row_keeps_approved_coverage_and_adds_scenarios():
    ws = Workspace(
        requirements=[req("The password must be at least 8 characters long.")],
        test_cases=[tc(TestType.POSITIVE)],
    )
    row = build_rtm(ws)[0]
    assert row.coverage == Coverage.COVERED
    assert row.scenarios.percent == 50.0


def test_only_approved_test_cases_count_as_covered():
    r = req("The password must be at least 8 characters long.")
    sc = scenario_coverage(r, [tc(TestType.POSITIVE), tc(TestType.BOUNDARY, n=2, status=ReviewStatus.DRAFT)])
    assert sc.covered == [C.HAPPY_PATH] and sc.percent == 50.0
    ws = Workspace(requirements=[r], test_cases=[tc(TestType.POSITIVE, status=ReviewStatus.REVIEWED)])
    row = build_rtm(ws)[0]
    assert row.coverage == Coverage.PARTIAL  # main Coverage column unchanged
    assert row.scenarios.covered == [] and row.scenarios.percent == 0.0


def test_login_and_password_alone_are_not_negative():
    sc = scenario_coverage(req("The user must enter login and password."), [])
    assert C.NEGATIVE not in sc.applicable + sc.unknown


def test_counted_limits_are_boundary_but_plain_numbers_are_not():
    for text, phrase in [
        ("After 5 failed login attempts the account must be locked.", "5 failed login attempts"),
        ("The system must allow maximum 3 retries.", "3 retries"),
        ("Пользователь может сделать не более 10 попыток входа.", "не более 10 попыток"),
    ]:
        sc = scenario_coverage(req(text), [])
        assert C.BOUNDARY in sc.applicable and sc.reasons[C.BOUNDARY] == phrase
    for text in ("Step 2 of the wizard must show the summary.", "The system must support version 3 of the API."):
        sc = scenario_coverage(req(text), [])
        assert C.BOUNDARY not in sc.applicable + sc.unknown


def test_unknown_is_left_out_of_the_percent():
    sc = scenario_coverage(req("The username length must be limited."), [tc(TestType.POSITIVE)])
    assert sc.unknown == [C.BOUNDARY]
    assert sc.applicable == [C.HAPPY_PATH] and sc.percent == 100.0


def test_limit_with_a_value_but_no_known_unit_is_boundary_not_unknown():
    for text, phrase in [
        ("The user can attach up to 3 files.", "up to 3"),
        ("A user can upload at most 5 photos.", "at most 5"),
        ("The value must be between 1 and 10.", "between 1 and 10"),
        ("Пользователь может загрузить не более 5 фотографий.", "не более 5"),
        ("Користувач може додати не більше 3 файлів.", "не більше 3"),
    ]:
        sc = scenario_coverage(req(text), [tc(TestType.POSITIVE)])
        assert C.BOUNDARY in sc.applicable and C.BOUNDARY not in sc.unknown, text
        assert sc.reasons[C.BOUNDARY] == phrase
        assert sc.percent == 50.0  # a happy path alone is not full coverage


COMPOUND = "The new password must be at least 8 characters long and contain one digit."


def test_condition_no_test_case_names_is_listed_without_changing_coverage():
    r = req(COMPOUND)
    cases = [tc(TestType.POSITIVE, title=f"REQ-1: {_short(COMPOUND)}", expected=COMPOUND),
             tc(TestType.BOUNDARY, title="REQ-1: boundary values for “at least 8 characters”",
                expected="7 characters → rejected (invalid)\n8 characters → accepted (valid)", n=2)]
    sc = scenario_coverage(r, cases)
    # Lengths vary, the digit does not: the boundary values say nothing about it.
    assert sc.unchecked_conditions == ["contain one digit"]
    # Statuses stay as they were: the condition is listed, not counted.
    assert (sc.applicable, sc.covered, sc.percent) == ([C.HAPPY_PATH, C.BOUNDARY], [C.HAPPY_PATH, C.BOUNDARY], 100.0)
    # A test case that names the digit (in any status) clears the line; wording only, not meaning.
    digit = tc(TestType.NEGATIVE, title="Password of 9 characters without digits is rejected", n=3,
               status=ReviewStatus.DRAFT)
    assert scenario_coverage(r, [*cases, digit]).unchecked_conditions == []


@pytest.mark.parametrize("text", [
    "The new password must be at least 8 characters long.",
    "The new password must be between 8 and 64 characters.",
])
def test_plain_numeric_requirement_has_no_unchecked_condition(text):
    assert scenario_coverage(req(text), [tc(TestType.BOUNDARY)]).unchecked_conditions == []


def test_no_unchecked_condition_without_test_cases():
    assert scenario_coverage(req(COMPOUND), []).unchecked_conditions == []
