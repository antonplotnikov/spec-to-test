"""Quality score of a test case: 100 minus the points of each problem the critic finds."""

import pytest

from spec_to_test.i18n import TRANSLATIONS, t
from spec_to_test.models import Requirement, TestCase, TestType, Workspace
from spec_to_test.test_critic import PENALTIES, UNKNOWN_CODES, TestCaseScore, score_test_case

REQ = Requirement(id="REQ-1", text="The password must be at least 8 characters long.")
GOOD_STEPS = ["Open the registration form.", "Enter a password of 8 characters and submit."]


def tc(n: int = 1, steps=None, expected: str = "The account is created.", requirement_id: str = "REQ-1",
       test_type: TestType = TestType.POSITIVE) -> TestCase:
    return TestCase(id=f"TC-{n}", requirement_id=requirement_id, title="Valid password", test_type=test_type,
                    steps=steps or GOOD_STEPS, expected_result=expected)


def workspace(*cases: TestCase) -> Workspace:
    return Workspace(requirements=[REQ], test_cases=list(cases))


def test_concrete_test_case_scores_full_points():
    case = tc()
    score = score_test_case(case, workspace(case))
    assert (score.score, score.deductions, score.unknown, score.grade) == (100, [], [], "good")


def test_placeholder_step_costs_its_points_and_is_explained():
    case = tc(steps=[t("tests.new_step", "en"), *GOOD_STEPS])
    score = score_test_case(case, workspace(case))
    assert score.score == 100 - PENALTIES["step_placeholder"]
    [deduction] = score.deductions
    assert (deduction.criterion, deduction.code, deduction.points) == ("steps", "step_placeholder", 20)
    assert deduction.params == {"step": "1"}


def test_unknown_items_cost_nothing_but_are_listed():
    case = tc(requirement_id="REQ-404")  # the requirement is not in the document
    score = score_test_case(case, workspace(case))
    assert score.score == 100 and score.deductions == []
    assert [(i.code, i.unknown) for i in score.unknown] == [("requirement_missing", True)]


def test_score_never_goes_below_zero():
    case = tc(steps=[t("tests.new_step", "en")] * 6, expected=t("tests.new_expected", "en"))
    score = score_test_case(case, workspace(case))
    assert len(score.deductions) >= 6
    assert score.score == 0


def test_conflicting_test_cases_both_lose_points():
    steps = ["Enter a password of 8 characters and submit."]
    accepted = tc(1, steps=steps, expected="8 characters → accepted (valid)")
    rejected = tc(2, steps=steps, expected="8 characters → rejected (invalid)")
    ws = workspace(accepted, rejected)
    for case in (accepted, rejected):
        score = score_test_case(case, ws)
        assert [(d.code, d.points) for d in score.deductions] == [
            ("expectation_conflict", PENALTIES["expectation_conflict"]),
        ]
        assert score.score == 100 - PENALTIES["expectation_conflict"]


def test_duplicate_test_cases_are_scored_with_their_penalty():
    first, second = tc(1), tc(2)
    score = score_test_case(first, workspace(first, second))
    assert [(d.code, d.points) for d in score.deductions] == [("duplicate", PENALTIES["duplicate"])]


@pytest.mark.parametrize(("points", "grade"), [(100, "good"), (80, "good"), (79, "fair"), (50, "fair"), (49, "poor")])
def test_grade_follows_the_requirement_thresholds(points, grade):
    assert TestCaseScore(test_case_id="TC-1", score=points).grade == grade


def test_every_critic_code_has_a_penalty_or_is_unknown():
    # A new critic code must be given a penalty here, or it would silently cost nothing.
    codes = {
        key.removeprefix("critic.") for key in TRANSLATIONS
        if key.startswith("critic.") and not key.startswith("critic.criterion.") and key != "critic.unknown"
    }
    assert codes == set(PENALTIES) | UNKNOWN_CODES
    assert all(points > 0 for points in PENALTIES.values())
    assert not set(PENALTIES) & UNKNOWN_CODES
