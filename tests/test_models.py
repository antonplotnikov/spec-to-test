import pytest
from pydantic import ValidationError

from spec_to_test.models import (
    AnalysisResult,
    ClarificationStatus,
    Finding,
    FindingType,
    Requirement,
    RequirementStatus,
    ReviewStatus,
    Severity,
    Source,
    TestCase,
    TestType,
)


def test_requirement_requires_id_and_text():
    with pytest.raises(ValidationError):
        Requirement(id="", text="Something")
    with pytest.raises(ValidationError):
        Requirement(id="REQ-1", text="")


def test_finding_defaults_to_rule_based_and_needs_clarification():
    finding = Finding(
        requirement_id="REQ-1", type=FindingType.AMBIGUOUS_WORDING, severity=Severity.LOW
    )
    assert finding.source == Source.RULE
    assert finding.status == ClarificationStatus.NEEDS_CLARIFICATION


def test_test_case_links_to_requirement_and_starts_as_draft():
    case = TestCase(
        id="TC-1",
        requirement_id="REQ-1",
        title="Reset link is sent",
        test_type=TestType.POSITIVE,
        steps=["Request a reset"],
        expected_result="A reset email is sent",
    )
    assert case.requirement_id == "REQ-1"
    assert case.review_status == ReviewStatus.DRAFT


def test_test_case_needs_at_least_one_step():
    with pytest.raises(ValidationError):
        TestCase(
            id="TC-1",
            requirement_id="REQ-1",
            title="x",
            test_type=TestType.POSITIVE,
            steps=[],
            expected_result="y",
        )


def test_status_of_requirement_depends_on_open_findings():
    result = AnalysisResult(
        requirements=[
            Requirement(id="REQ-1", text="Ambiguous one"),
            Requirement(id="REQ-2", text="Clear one"),
        ],
        findings=[
            Finding(requirement_id="REQ-1", type=FindingType.CONTRADICTION, severity=Severity.HIGH)
        ],
    )
    assert result.status_of("REQ-1") == RequirementStatus.NEEDS_CLARIFICATION
    assert result.status_of("REQ-2") == RequirementStatus.CLEAR

    result.findings[0].status = ClarificationStatus.RESOLVED
    assert result.status_of("REQ-1") == RequirementStatus.CLEAR
