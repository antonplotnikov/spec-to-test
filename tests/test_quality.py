from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import (
    ClarificationStatus,
    Finding,
    FindingType,
    Requirement,
    Severity,
    Source,
)
from spec_to_test.quality import CRITERIA, score_requirement
from spec_to_test.rule_engine import analyze_requirements


def score_of(text: str, explicit_id: bool = True):
    req = Requirement(id="REQ-1", text=text, has_explicit_id=explicit_id)
    return score_requirement(req, analyze_requirements([req]).findings)


def by_key(score):
    return {c.key: c for c in score.criteria}


def test_criteria_add_up_to_100():
    assert sum(CRITERIA.values()) == 100


def test_clear_requirement_scores_100():
    score = score_of("The system must lock the account after 5 failed login attempts and show an error message.")
    assert score.score == 100
    assert score.grade == "good"
    assert all(c.passed for c in score.criteria)


def test_ambiguous_terms_cost_points_with_evidence():
    score = score_of("The reset page must load fast and be user-friendly.")
    unambiguous = by_key(score)["unambiguous"]
    assert unambiguous.points == 0
    assert set(unambiguous.evidence) == {"fast", "user-friendly"}


def test_single_ambiguous_term_costs_ten_points():
    score = score_of("The system must show the report quickly.")
    assert by_key(score)["unambiguous"].points == 10


def test_missing_expected_result_costs_20():
    score = score_of("The user can reset the password.")
    assert by_key(score)["expected_result"].points == 0


def test_contradiction_evidence_names_related_requirement(example_text):
    reqs = extract_requirements(example_text)
    findings = analyze_requirements(reqs).findings
    req4 = next(r for r in reqs if r.id == "REQ-4")
    consistent = by_key(score_requirement(req4, findings))["consistent"]
    assert consistent.points == 0
    assert "REQ-7" in consistent.evidence


def test_generated_id_loses_identifiable_points():
    assert by_key(score_of("The system must save drafts.", explicit_id=False))["identifiable"].points == 0


def test_multiple_obligation_sentences_are_not_atomic():
    score = score_of("The system must save drafts. The system must also send an email.")
    assert by_key(score)["atomic"].points == 0
    assert by_key(score_of("The system must save drafts and send an email."))["atomic"].points == 10


def test_resolved_and_ai_findings_do_not_reduce_score():
    req = Requirement(id="REQ-1", text="The system must save drafts.", has_explicit_id=True)
    findings = [
        Finding(requirement_id="REQ-1", type=FindingType.CONTRADICTION, severity=Severity.HIGH,
                status=ClarificationStatus.RESOLVED),
        Finding(requirement_id="REQ-1", type=FindingType.MISSING_BOUNDARY, severity=Severity.HIGH,
                source=Source.AI),
    ]
    assert score_requirement(req, findings).score == 100


def test_score_never_negative():
    req = Requirement(id="REQ-1", text="x" * 10)
    findings = [
        Finding(requirement_id="REQ-1", type=kind, severity=Severity.HIGH, matched_terms=["a", "b", "c"])
        for kind in FindingType
    ]
    score = score_requirement(req, findings)
    assert 0 <= score.score <= 100
    assert score.grade == "poor"
