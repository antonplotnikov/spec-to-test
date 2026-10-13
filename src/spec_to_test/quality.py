"""Explainable 0-100 quality score for each requirement.

The score is the sum of fixed criteria. Each criterion has a maximum number
of points and reports the evidence that cost points, so a reviewer can see
exactly why a requirement scored what it did. Only open rule-based findings
are used; AI suggestions never change the score.

| Criterion        | Points | Loses points when                                        |
|------------------|-------:|----------------------------------------------------------|
| unambiguous      |     20 | ambiguous wording found (10 per term, 0 from 2 terms)    |
| expected_result  |     20 | no observable expected result                            |
| consistent       |     20 | a possible contradiction with another requirement        |
| boundaries       |     15 | limits are mentioned without concrete values             |
| error_handling   |     10 | user input is involved but failure behavior is missing   |
| atomic           |     10 | more than one obligation ("must ... must ...")           |
| identifiable     |      5 | the requirement has no ID in the source document         |
"""

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from spec_to_test.models import (
    ClarificationStatus,
    Finding,
    FindingType,
    Requirement,
    Source,
)
from spec_to_test.rule_engine import _OBLIGATION, _normalize

CRITERIA: dict[str, int] = {
    "unambiguous": 20,
    "expected_result": 20,
    "consistent": 20,
    "boundaries": 15,
    "error_handling": 10,
    "atomic": 10,
    "identifiable": 5,
}
assert sum(CRITERIA.values()) == 100

_FINDING_CRITERION = {
    FindingType.MISSING_EXPECTED_RESULT: "expected_result",
    FindingType.CONTRADICTION: "consistent",
    FindingType.MISSING_BOUNDARY: "boundaries",
    FindingType.MISSING_ERROR_HANDLING: "error_handling",
}

GOOD_THRESHOLD = 80
FAIR_THRESHOLD = 50

Grade = Literal["good", "fair", "poor"]


class CriterionResult(BaseModel):
    key: str
    max_points: int
    points: int
    # Phrases or IDs that explain lost points (empty when the criterion passed).
    evidence: list[str] = []

    @property
    def passed(self) -> bool:
        return self.points == self.max_points


class QualityScore(BaseModel):
    requirement_id: str
    score: int
    criteria: list[CriterionResult]

    @property
    def grade(self) -> Grade:
        return grade_of(self.score)


def _obligation_count(text: str) -> int:
    return len(_OBLIGATION.findall(_normalize(text)))


def _sentences_with_obligation(text: str) -> int:
    parts = re.split(r"(?<=[.!?;])\s+", text.strip())
    return sum(1 for part in parts if _OBLIGATION.search(_normalize(part)))


def score_requirement(requirement: Requirement, findings: list[Finding]) -> QualityScore:
    """Score one requirement using its open rule-based findings."""
    open_findings = [
        f
        for f in findings
        if f.requirement_id == requirement.id
        and f.source == Source.RULE
        and f.status == ClarificationStatus.NEEDS_CLARIFICATION
    ]
    results: dict[str, CriterionResult] = {
        key: CriterionResult(key=key, max_points=points, points=points)
        for key, points in CRITERIA.items()
    }

    for finding in open_findings:
        if finding.type == FindingType.AMBIGUOUS_WORDING:
            result = results["unambiguous"]
            result.evidence.extend(finding.matched_terms or ["?"])
            lost = 10 * len(result.evidence)
            result.points = max(0, result.max_points - lost)
            continue
        result = results[_FINDING_CRITERION[finding.type]]
        result.points = 0
        evidence = finding.related_requirement_ids or finding.matched_terms
        result.evidence.extend(e for e in evidence if e not in result.evidence)

    if _obligation_count(requirement.text) > 1 and _sentences_with_obligation(requirement.text) > 1:
        results["atomic"].points = 0
        results["atomic"].evidence.extend(_OBLIGATION.findall(_normalize(requirement.text)))

    if not requirement.has_explicit_id:
        results["identifiable"].points = 0

    criteria = list(results.values())
    return QualityScore(
        requirement_id=requirement.id,
        score=sum(c.points for c in criteria),
        criteria=criteria,
    )


def score_all(requirements: list[Requirement], findings: list[Finding]) -> dict[str, QualityScore]:
    return {req.id: score_requirement(req, findings) for req in requirements}



# ---------------------------------------------------------------------------
# Dimensions: the criteria grouped for an at-a-glance summary
# ---------------------------------------------------------------------------

# Every criterion belongs to exactly one dimension, so the dimensions add up to
# the same points as the score itself and stay just as explainable.
DIMENSIONS: dict[str, tuple[str, ...]] = {
    "clarity": ("unambiguous", "atomic"),
    "completeness": ("boundaries", "error_handling", "identifiable"),
    "testability": ("expected_result",),
    "consistency": ("consistent",),
}
assert sorted(c for criteria in DIMENSIONS.values() for c in criteria) == sorted(CRITERIA)
_DIMENSION_OF = {criterion: key for key, criteria in DIMENSIONS.items() for criterion in criteria}


class DimensionScore(BaseModel):
    key: str
    points: int
    max_points: int

    @property
    def percent(self) -> int:
        return round(100 * self.points / self.max_points) if self.max_points else 0


def dimension_scores(scores: Iterable[QualityScore]) -> list[DimensionScore]:
    """Points per dimension summed over `scores` (several requirements give one total)."""
    totals = {key: [0, 0] for key in DIMENSIONS}
    for score in scores:
        for criterion in score.criteria:
            total = totals[_DIMENSION_OF[criterion.key]]
            total[0] += criterion.points
            total[1] += criterion.max_points
    return [DimensionScore(key=key, points=p, max_points=m) for key, (p, m) in totals.items()]


def average_score(scores: Iterable[QualityScore]) -> int | None:
    """Mean score, rounded; None when there is nothing to score."""
    values = [s.score for s in scores]
    return round(sum(values) / len(values)) if values else None


def grade_of(score: int) -> Grade:
    if score >= GOOD_THRESHOLD:
        return "good"
    if score >= FAIR_THRESHOLD:
        return "fair"
    return "poor"
