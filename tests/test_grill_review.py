"""QA Review content checks: clarity, consistency with the source, executability."""

import pytest

from spec_to_test.grill.models import (
    AnswerStatus,
    ArtifactType,
    BugReportDraft,
    FindingLevel,
    GrillKind,
    Priority,
    Provenance,
    Reproducibility,
    RequirementsDraft,
    ReviewCategory,
    ReviewFinding,
    Statement,
    TestCaseDraft,
)
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.grill.text import render_finding
from spec_to_test.grill.validation import check_bug_report, check_requirements, check_test_case
from spec_to_test.i18n import LANGUAGES
from spec_to_test.models import Requirement, Severity, TestType

MIN_8 = Requirement(id="REQ-1", text="The password must be at least 8 characters.")
SESSION = Requirement(id="REQ-2", text="The session expires after 30 minutes of inactivity.")


def codes(findings: list[ReviewFinding]) -> dict[str, ReviewFinding]:
    return {f.message_key.removeprefix("grill.check."): f for f in findings}


def tc(**changes) -> TestCaseDraft:
    fields = dict(
        title="Password with 8 characters is accepted", objective="Verify the minimum length", requirement_id="REQ-1",
        test_type=TestType.POSITIVE, preconditions=["The registration page is open"],
        test_data=["Password: abcdefgh"], steps=["Enter the password", "Click Register"],
        expected_result="The account is created",
    )
    return TestCaseDraft(**{**fields, **changes})


def bug(**changes) -> BugReportDraft:
    fields = dict(
        summary="Session expires too early", environment="Chrome 140", app_version="1.0.0",
        steps=["Log in", "Stay idle for 10 minutes"], actual_result="The session expires after 10 minutes",
        expected_result="The session stays active until 30 minutes of inactivity",
        reproducibility=Reproducibility.ALWAYS,
        evidence=["Screen recording"], severity=Severity.HIGH, priority=Priority.HIGH, requirement_id="REQ-2",
    )
    return BugReportDraft(**{**fields, **changes})


def test_clean_drafts_have_no_findings():
    assert check_test_case(tc(), {"REQ-1"}, MIN_8) == []
    assert check_bug_report(bug(), {"REQ-2"}, SESSION) == []


# --- Clarity ------------------------------------------------------------------------

def test_vague_expected_result_is_a_warning_and_vague_steps_a_suggestion():
    found = check_test_case(
        tc(expected_result="The page loads fast", steps=["Enter some data", "Click Register"]), {"REQ-1"}, MIN_8
    )
    vague = {f.field: f for f in found if f.message_key == "grill.check.vague_wording"}
    assert vague["expected_result"].level == FindingLevel.WARNING
    assert vague["expected_result"].category == ReviewCategory.CLARITY
    assert "“fast”" in vague["expected_result"].params["terms"]
    assert vague["steps"].level == FindingLevel.SUGGESTION


def test_placeholders_are_not_double_reported_as_vague():
    found = codes(check_test_case(tc(expected_result="TBD"), {"REQ-1"}, MIN_8))
    assert "placeholder" in found and "vague_wording" not in found


def test_vague_clarifications_are_flagged():
    draft = RequirementsDraft(
        requirements=[MIN_8],
        statements=[Statement(text="Errors are shown properly", provenance=Provenance.USER_CONFIRMED,
                              requirement_ids=["REQ-1"])],
    )
    assert codes(check_requirements(draft))["vague_wording"].field == "statements"


# --- Consistency with the source -------------------------------------------------------

def test_limit_that_contradicts_the_requirement_is_flagged():
    draft = tc(expected_result="Passwords of at least 10 characters are accepted")
    finding = codes(check_test_case(draft, {"REQ-1"}, MIN_8))["limit_conflicts_source"]
    assert finding.category == ReviewCategory.CONTRADICTION and finding.requirement_ids == ["REQ-1"]
    message, _ = render_finding(finding)
    assert "at least 10 characters" in message and "at least 8 characters" in message


def test_new_rule_absent_from_the_source_is_flagged():
    draft = tc(expected_result="Passwords of up to 64 characters are accepted")
    finding = codes(check_test_case(draft, {"REQ-1"}, MIN_8))["limit_not_in_source"]
    assert finding.category == ReviewCategory.UNSUPPORTED_CLAIM


def test_concrete_test_values_are_not_mistaken_for_rules():
    draft = tc(test_type=TestType.BOUNDARY, test_data=["7", "8", "9"], steps=["Enter 7 characters", "Click Register"],
               expected_result="The 7-character password is rejected with an error")
    found = codes(check_test_case(draft, {"REQ-1"}, MIN_8))
    assert "limit_conflicts_source" not in found and "limit_not_in_source" not in found


def test_limits_are_only_compared_with_a_linked_requirement():
    draft = tc(requirement_id="", feature="Registration", expected_result="At least 10 characters are accepted")
    found = codes(check_test_case(draft, None, None))
    assert "limit_conflicts_source" not in found and "limit_not_in_source" not in found


def test_bug_expected_result_must_follow_the_requirement():
    draft = bug(expected_result="The session expires after 15 minutes")
    found = codes(check_bug_report(draft, {"REQ-2"}, SESSION))
    assert found["limit_conflicts_source"].params["source_phrase"] == "30 minutes"
    # Observed values in the actual result are facts, not rules.
    assert "limit_conflicts_source" not in codes(check_bug_report(bug(), {"REQ-2"}, SESSION))


# --- Test design and executability -------------------------------------------------------

@pytest.mark.parametrize("expected", [
    "The account is created",
    "The user sees the dashboard",
])
def test_negative_test_must_expect_a_failure(expected):
    found = codes(check_test_case(tc(test_type=TestType.NEGATIVE, expected_result=expected), {"REQ-1"}, MIN_8))
    assert found["negative_without_failure"].category == ReviewCategory.CONTRADICTION


@pytest.mark.parametrize("expected", [
    "An error message says the password is too short",
    "The account is locked",
    "The form is not submitted",
    "Отображается сообщение об ошибке",
    "Форма не відправляється",
])
def test_negative_test_with_a_failure_outcome_passes(expected):
    found = codes(check_test_case(tc(test_type=TestType.ERROR_HANDLING, expected_result=expected), {"REQ-1"}, MIN_8))
    assert "negative_without_failure" not in found


def test_positive_test_expecting_an_error_is_contradictory():
    found = codes(check_test_case(tc(expected_result="An error is shown"), {"REQ-1"}, MIN_8))
    assert "“error”" in found["positive_expects_failure"].params["terms"]
    clean = codes(check_test_case(tc(expected_result="No error is shown and the account is created"),
                                  {"REQ-1"}, MIN_8))
    assert "positive_expects_failure" not in clean


def test_step_that_repeats_the_result_is_redundant():
    draft = tc(steps=["Enter the password", "The account is created"])
    assert codes(check_test_case(draft, {"REQ-1"}, MIN_8))["expected_in_steps"].level == FindingLevel.SUGGESTION
    report = bug(steps=["Log in", "The session expires after 10 minutes"])
    assert "expected_in_steps" in codes(check_bug_report(report, {"REQ-2"}, SESSION))


@pytest.mark.parametrize("test_type", [TestType.BOUNDARY, TestType.EQUIVALENCE, TestType.DECISION_TABLE])
def test_data_driven_test_without_data_cannot_be_executed(test_type):
    found = codes(check_test_case(tc(test_type=test_type, test_data=[]), {"REQ-1"}, MIN_8))
    assert found["data_missing_for_type"].category == ReviewCategory.EXECUTABILITY


def test_boundary_test_should_cover_all_boundary_values():
    partial = tc(test_type=TestType.BOUNDARY, test_data=["8"], expected_result="Accepted")
    finding = codes(check_test_case(partial, {"REQ-1"}, MIN_8))["boundary_values_missing"]
    assert finding.params["values"] == "7, 8, 9" and finding.level == FindingLevel.SUGGESTION
    full = partial.model_copy(update={"test_data": ["7 characters", "8 characters", "9 characters"]})
    assert "boundary_values_missing" not in codes(check_test_case(full, {"REQ-1"}, MIN_8))


# --- Requirements review -------------------------------------------------------------------

def test_requirement_review_reports_rule_findings_with_their_ids():
    reqs = [MIN_8, Requirement(id="REQ-3", text="The password must be at least 10 characters."),
            Requirement(id="REQ-4", text="The page should load fast.")]
    found = codes(check_requirements(RequirementsDraft(requirements=reqs)))
    assert found["req_contradiction"].requirement_ids == ["REQ-1", "REQ-3"]
    assert found["req_contradiction"].category == ReviewCategory.CONTRADICTION
    assert found["req_ambiguous_wording"].requirement_ids == ["REQ-4"]
    assert all(f.level == FindingLevel.WARNING for f in found.values())


def test_qa_review_of_requirements_runs_without_an_interview():
    session = WF.start(GrillKind.REVIEW, artifact=ArtifactType.REQUIREMENTS)
    session = WF.submit_input(session, RequirementsDraft(requirements=[Requirement(id="R-1", text="Upload files.")]))
    found = codes(session.findings)
    assert {"req_missing_expected_result", "req_missing_error_handling"} <= set(found)


def test_unknown_rule_answer_is_reported_once():
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS),
                              RequirementsDraft(requirements=[Requirement(id="R-1", text="The page should load fast.")]))
    session = WF.review(WF.answer(session, "", AnswerStatus.UNKNOWN))
    assert [f.message_key for f in session.findings] == ["grill.check.req_ambiguous_wording"]


# --- Review through the workflow ----------------------------------------------------------

def test_review_uses_the_linked_requirement_from_the_document():
    session = WF.start(GrillKind.REVIEW, artifact=ArtifactType.TEST_CASE, context_requirements=[MIN_8, SESSION])
    session = WF.submit_input(session, tc(expected_result="At least 12 characters are accepted"))
    assert "limit_conflicts_source" in codes(session.findings)


def test_review_separates_blocking_issues_from_optional_improvements():
    session = WF.start(GrillKind.REVIEW, artifact=ArtifactType.TEST_CASE, context_requirements=[MIN_8])
    session = WF.submit_input(session, tc(steps=[], objective="", expected_result="Works fast"))
    levels = [f.level for f in session.findings]
    assert levels == sorted(levels, key=[FindingLevel.BLOCKING, FindingLevel.WARNING, FindingLevel.SUGGESTION].index)
    assert {f.level for f in session.findings} == set(FindingLevel)


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_content_findings_render_in_every_language(lang):
    findings = check_test_case(
        tc(test_type=TestType.BOUNDARY, test_data=[], steps=["Enter some text", "The page loads fast"],
           expected_result="The page loads fast; up to 64 characters; at least 10 characters"),
        {"REQ-1"}, MIN_8,
    )
    findings += check_test_case(tc(test_type=TestType.NEGATIVE, expected_result="Saved"), {"REQ-1"}, MIN_8)
    findings += check_test_case(tc(expected_result="An error is shown"), {"REQ-1"}, MIN_8)
    findings += check_test_case(tc(expected_result="Up to 64 characters are accepted"), {"REQ-1"}, MIN_8)
    findings += check_test_case(tc(test_type=TestType.BOUNDARY, test_data=["8"]), {"REQ-1"}, MIN_8)
    findings += check_requirements(RequirementsDraft(requirements=[
        MIN_8, Requirement(id="REQ-3", text="The password must be at least 10 characters."),
        Requirement(id="REQ-4", text="Users enter the email in the form."),
        Requirement(id="REQ-5", text="The number of attempts is limited."),
    ]))
    assert {f.message_key.removeprefix("grill.check.") for f in findings} >= {
        "vague_wording", "limit_conflicts_source", "limit_not_in_source", "negative_without_failure",
        "positive_expects_failure", "data_missing_for_type", "boundary_values_missing",
        "req_contradiction", "req_missing_error_handling", "req_missing_boundary",
    }
    for finding in findings:
        message, fix = render_finding(finding, lang)
        assert message and fix and "grill." not in message + fix and "{" not in message + fix
