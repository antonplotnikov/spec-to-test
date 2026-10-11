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
    Workspace,
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


# --- Source.USER (added for Grill Mode) ----------------------------------------

# A workspace saved by version 1.0.0, before Source.USER existed.
SAVED_BY_1_0_0 = """{
  "document_hash": "abc123",
  "requirements": [{"id": "REQ-1", "text": "The user must log in.", "language": "en",
                    "source_line": 1, "has_explicit_id": true}],
  "findings": [{"requirement_id": "REQ-1", "type": "missing_error_handling", "severity": "medium",
                "source": "rule", "matched_terms": ["log in"], "related_requirement_ids": [],
                "status": "needs_clarification"}],
  "test_cases": [{"id": "TC-001", "requirement_id": "REQ-1", "title": "Login", "test_type": "positive",
                  "preconditions": [], "steps": ["Log in"], "expected_result": "Logged in",
                  "assumptions": [], "clarification_questions": [], "source": "rule",
                  "review_status": "draft", "reviewer_comment": ""}],
  "defects": [{"id": "BUG-001", "requirement_id": "REQ-1", "title": "Gap", "severity": "medium",
               "description": "", "expected_behavior": "", "reproduction_context": "",
               "source": "ai", "origin_key": "ai|AI-001"}],
  "ai_suggestions": [],
  "ai_model": ""
}"""


def test_existing_source_values_are_unchanged():
    assert Source.RULE.value == "rule" and Source.AI.value == "ai"
    assert Source.USER.value == "user"


def test_workspace_saved_before_user_source_still_loads():
    ws = Workspace.model_validate_json(SAVED_BY_1_0_0)
    assert ws.test_cases[0].source == Source.RULE
    assert ws.defects[0].source == Source.AI


def test_user_authored_test_case_round_trips():
    ws = Workspace.model_validate_json(SAVED_BY_1_0_0)
    ws.test_cases.append(
        TestCase(id="TC-002", requirement_id="REQ-1", title="Grill case", test_type=TestType.NEGATIVE,
                 steps=["Enter a wrong password"], expected_result="An error is shown", source=Source.USER)
    )
    restored = Workspace.model_validate_json(ws.model_dump_json())
    assert restored == ws
    assert restored.test_cases[1].source == Source.USER
