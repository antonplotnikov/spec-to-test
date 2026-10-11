"""Bridge from Grill Mode to the existing rule engine and test design.

Grill reuses the same keyword lists and numeric-limit parsing as the main
analysis, so a requirement gets the same verdict in both places.
"""

import re
from decimal import Decimal
from functools import lru_cache

from spec_to_test.models import Finding, FindingType, Language, Requirement
from spec_to_test.rule_engine import (
    _AMBIGUOUS,
    _ERROR,
    _NEGATIVE,
    _compile,
    _matches,
    _normalize,
    analyze_requirements,
)
from spec_to_test.test_design import Constraint, boundary_values, extract_constraints, format_value

RULE_QUESTION_PREFIX = "rule."

# Words that clearly describe a failure (used to check positive tests).
_FAILURE = _compile([
    "error*", "invalid*", "fail*", "reject*", "denied", "exception*",
    "помилк*", "невірн*", "недійсн*", "відхил*", "відмов*",
    "ошибк*", "неверн*", "недействител*", "отклон*", "отказ*",
])
# Outcomes of a correctly handled failure that the error list does not cover.
_BLOCKED = _compile(["lock*", "block*", "блоку*", "заблок*", "блокир*"])
_NEGATION = re.compile(
    r"(?<!\w)(?:no|not|never|without|cannot|can't|isn't|aren't|doesn't|don't|won't"
    r"|не|ні|немає|нема|без|нет|ни)(?!\w)",
    re.IGNORECASE,
)


def vague_terms(text: str) -> list[str]:
    """Vague words from the rule engine's ambiguity list."""
    return _matches(_AMBIGUOUS, _normalize(text))


def describes_failure(text: str) -> bool:
    """True if the text mentions an error, a rejection or a negation."""
    text = _normalize(text)
    return any(p.search(text) for p in (_ERROR, _FAILURE, _BLOCKED, _NEGATIVE, _NEGATION))


def failure_terms(text: str) -> list[str]:
    """Clear failure words, unless the text negates them ("no error is shown")."""
    text = _normalize(text)
    return [] if _NEGATION.search(text) else _matches(_FAILURE, text)


# ---------------------------------------------------------------------------
# Requirement findings as clarification questions
# ---------------------------------------------------------------------------

def rule_question_id(finding: Finding) -> str:
    """Stable question ID for a finding. A contradiction gets one ID per pair."""
    if finding.type == FindingType.CONTRADICTION:
        ids = sorted({finding.requirement_id, *finding.related_requirement_ids})
        return f"{RULE_QUESTION_PREFIX}contradiction.{'+'.join(ids)}"
    return f"{RULE_QUESTION_PREFIX}{finding.type.value}.{finding.requirement_id}"


@lru_cache(maxsize=16)
def _cached_findings(key: tuple[tuple[str, str, str], ...]) -> tuple[tuple[str, Finding], ...]:
    requirements = [Requirement(id=i, text=text, language=Language(lang)) for i, text, lang in key]
    seen: set[str] = set()
    result = []
    for finding in analyze_requirements(requirements).findings:
        question_id = rule_question_id(finding)
        if question_id not in seen:  # the rule engine reports a contradiction on both sides
            seen.add(question_id)
            result.append((question_id, finding))
    return tuple(result)


def requirement_findings(requirements: list[Requirement]) -> list[tuple[str, Finding]]:
    """(question ID, finding) for every rule finding, one per contradicting pair."""
    key = tuple((r.id, r.text, r.language.value) for r in requirements)
    return [(qid, finding.model_copy(deep=True)) for qid, finding in _cached_findings(key)]


# ---------------------------------------------------------------------------
# Numeric limits
# ---------------------------------------------------------------------------

def _bounds(constraint: Constraint, include_exact: bool = False) -> dict[str, Decimal]:
    """Lower and upper limits stated by a min, max or range constraint."""
    bounds = {}
    if constraint.kind in ("min", "range") and constraint.low is not None:
        bounds["low"] = constraint.low
    if constraint.kind in ("max", "range") and constraint.high is not None:
        bounds["high"] = constraint.high
    if include_exact and constraint.kind == "exact" and constraint.low is not None:
        bounds["exact"] = constraint.low
    return bounds


def compare_limits(
    text: str, source: Requirement, include_exact: bool = False
) -> list[tuple[str, Constraint, Constraint | None]]:
    """Compare limits stated in a draft with the linked requirement.

    Returns ("conflict", draft_limit, source_limit) when the same limit has a
    different value, and ("new", draft_limit, None) when the draft states a
    limit the requirement does not have.

    Exact values ("enter 7 characters") are usually test inputs, not rules, so
    they are compared only with `include_exact` (e.g. for a bug's expected
    result, which must follow the requirement).
    """
    source_bounds: dict[str, list[tuple[str, Decimal, Constraint]]] = {}
    for constraint in extract_constraints(source.text):
        for side, value in _bounds(constraint, include_exact=True).items():
            source_bounds.setdefault(constraint.unit, []).append((side, value, constraint))

    result: list[tuple[str, Constraint, Constraint | None]] = []
    for constraint in extract_constraints(text):
        for side, value in _bounds(constraint, include_exact).items():
            match = next((s for s in source_bounds.get(constraint.unit, []) if s[0] == side), None)
            if match is None:
                result.append(("new", constraint, None))
            elif match[1] != value:
                result.append(("conflict", constraint, match[2]))
            else:
                continue
            break  # one finding per stated limit
    return result


def boundary_hints(source: Requirement) -> list[tuple[str, list[str]]]:
    """(source phrase, values to test) for each numeric limit in a requirement."""
    return [
        (constraint.phrase, [format_value(v.value) for v in boundary_values(constraint).values])
        for constraint in extract_constraints(source.text)
    ]


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def numbers_in(text: str) -> set[str]:
    return {format_value(Decimal(n.replace(",", "."))) for n in _NUMBER.findall(text)}
