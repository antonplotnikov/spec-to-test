"""Regressions found by the pre-commit audit: score arithmetic, RTM bounds, one recommendation per
requirement, and test case IDs that test runs still refer to."""

from spec_to_test.change_impact import recommend
from spec_to_test.execution import case_ids_in_runs, new_run
from spec_to_test.i18n import t
from spec_to_test.models import (
    ChangeImpact,
    Requirement,
    RequirementChange,
    ReviewStatus,
    TestCase,
    TestType,
    Workspace,
)
from spec_to_test.quality import CRITERIA
from spec_to_test.rtm import build_rtm, coverage_levels
from spec_to_test.test_critic import PENALTIES, score_test_case
from spec_to_test.test_generator import generate_test_cases, next_test_case_id

REQ1 = Requirement(id="REQ-1", text="The password must be at least 8 characters long.")
REQ2 = Requirement(id="REQ-2", text="The session must expire after 30 minutes.")
STEPS = ["Open the registration form.", "Enter a password of 8 characters and submit."]


def case(n: int, requirement: str, steps=STEPS, expected="The account is created.") -> TestCase:
    return TestCase(id=f"TC-{n}", requirement_id=requirement, title="Valid password", test_type=TestType.POSITIVE,
                    steps=list(steps), expected_result=expected)


def test_the_score_is_exactly_one_hundred_minus_the_points_found():
    placeholder_step = t("tests.new_step", "en")  # the placeholder the editor inserts
    placeholder_result = t("tests.new_expected", "en")
    tc = case(1, "REQ-1", steps=[placeholder_step, *STEPS], expected=placeholder_result)
    score = score_test_case(tc, Workspace(requirements=[REQ1], test_cases=[tc]))
    found = sum(d.points for d in score.deductions)
    assert found == PENALTIES["step_placeholder"] + PENALTIES["expected_placeholder"]
    assert score.score == 100 - found == 55


def test_a_duplicate_in_another_requirement_is_not_a_duplicate():
    first = case(1, "REQ-1")
    twin = case(2, "REQ-2")  # identical steps and result, but a different requirement
    ws = Workspace(requirements=[REQ1, REQ2], test_cases=[first, twin])
    assert not [d for d in score_test_case(first, ws).deductions if d.code == "duplicate"]


def test_the_criteria_of_the_requirement_score_still_add_up_to_one_hundred():
    assert sum(CRITERIA.values()) == 100


def test_execution_and_the_other_levels_stay_within_zero_and_one_hundred(example_text):
    from spec_to_test.input_parser import extract_requirements
    from spec_to_test.rule_engine import analyze_requirements

    result = analyze_requirements(extract_requirements(example_text))
    ws = Workspace(requirements=result.requirements, findings=result.findings)
    ws.test_cases = generate_test_cases(ws)
    rows = build_rtm(ws)
    every = {r.requirement_id for r in rows} | {"REQ-404"}  # an executed ID that is not in the document
    levels = coverage_levels(rows, every)
    assert 0.0 <= levels.review <= levels.design <= 100.0
    assert levels.execution == 100.0  # the unknown requirement does not inflate the share


def test_each_requirement_gets_at_most_one_recommendation():
    impact = ChangeImpact(changes=[
        RequirementChange(kind="modified", old_id="REQ-1", new_id="REQ-1", old_text="a", new_text="b"),
        RequirementChange(kind="added", new_id="REQ-3", new_text="c"),
    ], test_cases=[])
    recs = recommend(impact, ["REQ-1", "REQ-2", "REQ-3"])
    ids = [r.requirement_id for r in recs]
    assert len(ids) == len(set(ids)) == 3


def test_an_id_of_a_deleted_case_that_a_run_refers_to_is_never_handed_out_again():
    kept = [case(1, "REQ-1"), case(2, "REQ-1")]
    run = new_run("RUN-001", "Smoke", "smoke", "", "", "doc1", [kept[0].id, "TC-3"], "t")
    reserved = case_ids_in_runs([run], "doc1")
    assert next_test_case_id(kept) == "TC-003"  # without the run's reference, TC-003 would be reused
    assert next_test_case_id(kept, reserved=reserved) == "TC-004"


def test_generated_cases_skip_reserved_ids():
    ws = Workspace(requirements=[REQ1])
    created = generate_test_cases(ws, "en", reserved=["TC-001", "TC-002"])
    assert created[0].id == "TC-003"
    assert ReviewStatus.DRAFT == created[0].review_status
