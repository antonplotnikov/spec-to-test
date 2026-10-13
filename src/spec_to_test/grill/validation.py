"""Deterministic checks for Grill drafts (no AI, no network).

Each check returns ReviewFinding objects with a translation key
(`grill.check.<code>`) and a suggested fix (`grill.fix.<code>`), so findings
are re-rendered in the current interface language.

Levels:
- BLOCKING:   the artifact cannot be finalized (e.g. a test case without steps).
- WARNING:    must be fixed or explicitly accepted as unresolved.
- SUGGESTION: optional improvement.

Content checks reuse the rule engine (vague wording, numeric limits), so a
draft is judged by the same rules as the source requirements. A check may
point out a problem; it never rewrites the draft.
"""

import re

from spec_to_test.grill.conflicts import CONFLICT_PREFIX, FOLLOWUP_PREFIX, ConflictKind, unresolved_conflicts
from spec_to_test.grill.drafts import AnyDraft, field_is_empty
from spec_to_test.grill.models import (
    AnswerStatus,
    BugReportDraft,
    FindingLevel,
    GrillSession,
    Provenance,
    RequirementsDraft,
    ReviewCategory,
    ReviewFinding,
    TestCaseDraft,
)
from spec_to_test.grill.rules import (
    boundary_hints,
    compare_limits,
    describes_failure,
    failure_terms,
    numbers_in,
    requirement_findings,
    vague_terms,
)
from spec_to_test.models import Finding, FindingType, Requirement, Source, TestType

TEST_CASE_REQUIRED = ("title", "test_type", "steps", "expected_result")
TEST_CASE_RECOMMENDED = ("objective", "preconditions")
BUG_REQUIRED = ("summary", "steps", "actual_result", "expected_result")
# Unknown values are allowed here, but never filled in for the user.
BUG_IMPORTANT = ("environment", "app_version", "reproducibility", "severity", "priority")
BUG_RECOMMENDED = ("evidence",)

# Every code has grill.check.<code> and grill.fix.<code> translations.
CHECK_CODES = (
    "required_missing", "unknown_value", "subject_missing", "recommended_missing",
    "no_requirement_link", "unverified_requirement", "unknown_requirement",
    "placeholder", "duplicate", "assumption_field", "assumptions_listed", "ai_field",
    "actual_equals_expected", "no_requirements", "statement_unknown_requirement",
    "statement_assumption", "statement_ai", "question_open", "question_unknown",
    # Content checks
    "vague_wording", "limit_conflicts_source", "limit_not_in_source", "negative_without_failure",
    "positive_expects_failure", "expected_in_steps", "data_missing_for_type", "boundary_values_missing",
    # Rule engine findings on source requirements
    "req_ambiguous_wording", "req_missing_expected_result", "req_missing_boundary",
    "req_missing_error_handling", "req_contradiction",
    # Contradictions found in the answers (grill.conflicts)
    "answer_conflict",
)

_PLACEHOLDER = re.compile(
    r"^\s*(?:tbd|tbc|todo|n/?a|xxx+|\?+|\.{3,}|…|-+|lorem ipsum.*|<[^>]*>|\[[^\]]*\])\s*$",
    re.IGNORECASE,
)


def is_placeholder(text: str) -> bool:
    """True for filler such as "TBD", "N/A", "..." or "<steps>"."""
    return bool(_PLACEHOLDER.match(text))


def _finding(
    level: FindingLevel,
    category: ReviewCategory,
    code: str,
    field: str = "",
    requirement_ids: list[str] | None = None,
    **params: str,
) -> ReviewFinding:
    if code not in CHECK_CODES:
        raise ValueError(f"unregistered check code: {code}")
    return ReviewFinding(
        level=level,
        category=category,
        field=field,
        message_key=f"grill.check.{code}",
        suggestion_key=f"grill.fix.{code}",
        params=params,
        requirement_ids=requirement_ids or [],
    )


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold().rstrip(".!;")


def _missing(draft: AnyDraft, field: str, level: FindingLevel) -> ReviewFinding:
    if draft.provenance.get(field) == Provenance.UNKNOWN:
        return _finding(level, ReviewCategory.UNKNOWN_VALUE, "unknown_value", field)
    return _finding(level, ReviewCategory.REQUIRED_FIELD, "required_missing", field)


def _check_fields(
    draft: AnyDraft, fields: tuple[str, ...], level: FindingLevel, code: str | None = None
) -> list[ReviewFinding]:
    findings = []
    for field in fields:
        if not field_is_empty(draft, field):
            continue
        if code and draft.provenance.get(field) != Provenance.UNKNOWN:
            findings.append(_finding(level, ReviewCategory.REQUIRED_FIELD, code, field))
        else:
            findings.append(_missing(draft, field, level))
    return findings


def _text_values(draft: AnyDraft) -> list[tuple[str, str]]:
    """(field, text) for every filled text or list-of-text field."""
    values: list[tuple[str, str]] = []
    for field, value in draft:
        if field in ("draft_type", "provenance", "requirements", "statements"):
            continue
        if isinstance(value, str) and value:
            values.append((field, value))
        elif isinstance(value, list):
            values += [(field, item) for item in value if isinstance(item, str)]
    return values


def _check_placeholders(draft: AnyDraft) -> list[ReviewFinding]:
    return [
        _finding(FindingLevel.WARNING, ReviewCategory.PLACEHOLDER, "placeholder", field, text=text.strip())
        for field, text in _text_values(draft)
        if is_placeholder(text)
    ]


def _check_duplicates(draft: AnyDraft, fields: tuple[str, ...]) -> list[ReviewFinding]:
    findings = []
    for field in fields:
        seen: set[str] = set()
        for item in getattr(draft, field):
            key = _normalized(item)
            if key in seen:
                findings.append(
                    _finding(FindingLevel.WARNING, ReviewCategory.DUPLICATE, "duplicate", field, text=item)
                )
            seen.add(key)
    return findings


def _check_provenance(draft: AnyDraft) -> list[ReviewFinding]:
    findings = []
    for field, source in draft.provenance.items():
        if source == Provenance.ASSUMPTION:
            findings.append(_finding(FindingLevel.WARNING, ReviewCategory.ASSUMPTION, "assumption_field", field))
        elif source == Provenance.AI_SUGGESTION:
            findings.append(_finding(FindingLevel.WARNING, ReviewCategory.AI_SUGGESTION, "ai_field", field))
    if draft.assumptions:
        findings.append(
            _finding(
                FindingLevel.WARNING, ReviewCategory.ASSUMPTION, "assumptions_listed", "assumptions",
                count=str(len(draft.assumptions)),
            )
        )
    return findings


def _check_requirement_link(
    requirement_id: str, known_ids: set[str] | None, required: bool
) -> list[ReviewFinding]:
    req = requirement_id.strip()
    if not req:
        if required:
            return [_finding(FindingLevel.WARNING, ReviewCategory.TRACEABILITY, "no_requirement_link", "requirement_id")]
        return []
    if known_ids is None:
        return [
            _finding(
                FindingLevel.WARNING, ReviewCategory.TRACEABILITY, "unverified_requirement",
                "requirement_id", [req], req=req,
            )
        ]
    if req not in known_ids:
        return [
            _finding(
                FindingLevel.BLOCKING, ReviewCategory.TRACEABILITY, "unknown_requirement",
                "requirement_id", [req], req=req,
            )
        ]
    return []


# --- Content checks -------------------------------------------------------------

def _quoted(terms: list[str]) -> str:
    return ", ".join(f"“{term}”" for term in terms)


def _check_vague(draft: AnyDraft, fields: dict[str, FindingLevel]) -> list[ReviewFinding]:
    """Vague words make a value impossible to verify."""
    findings = []
    for field, level in fields.items():
        value = getattr(draft, field)
        items = value if isinstance(value, list) else [value]
        terms: list[str] = []
        for item in items:
            if item and not is_placeholder(item):
                terms += [t for t in vague_terms(item) if t.casefold() not in {x.casefold() for x in terms}]
        if terms:
            findings.append(_finding(level, ReviewCategory.CLARITY, "vague_wording", field, terms=_quoted(terms)))
    return findings


def _check_limits(
    draft: AnyDraft, source: Requirement | None, exact_fields: tuple[str, ...] = ()
) -> list[ReviewFinding]:
    """Limits in the draft must match the linked requirement, not add new rules.

    `exact_fields` are also checked for exact values ("expires after 15 minutes").
    """
    if source is None:
        return []
    findings = []
    for field, text in _text_values(draft):
        if field in ("requirement_id", "feature"):
            continue
        for verdict, stated, original in compare_limits(text, source, include_exact=field in exact_fields):
            if verdict == "conflict" and original is not None:
                findings.append(
                    _finding(
                        FindingLevel.WARNING, ReviewCategory.CONTRADICTION, "limit_conflicts_source", field,
                        [source.id], phrase=stated.phrase, source_phrase=original.phrase, req=source.id,
                    )
                )
            else:
                findings.append(
                    _finding(
                        FindingLevel.WARNING, ReviewCategory.UNSUPPORTED_CLAIM, "limit_not_in_source", field,
                        [source.id], phrase=stated.phrase, req=source.id,
                    )
                )
    return findings


def _check_redundant_steps(draft: TestCaseDraft | BugReportDraft, result_field: str) -> list[ReviewFinding]:
    """A step that only repeats the expected (or actual) result is not an action."""
    result = _normalized(getattr(draft, result_field))
    if result and any(_normalized(step) == result for step in draft.steps):
        return [_finding(FindingLevel.SUGGESTION, ReviewCategory.DUPLICATE, "expected_in_steps", "steps")]
    return []


def _check_test_design(draft: TestCaseDraft, source: Requirement | None) -> list[ReviewFinding]:
    findings = []
    test_type, expected = draft.test_type, draft.expected_result.strip()
    if expected and not is_placeholder(expected):
        if test_type in (TestType.NEGATIVE, TestType.ERROR_HANDLING) and not describes_failure(expected):
            findings.append(
                _finding(FindingLevel.WARNING, ReviewCategory.CONTRADICTION, "negative_without_failure",
                         "expected_result")
            )
        if test_type == TestType.POSITIVE and (terms := failure_terms(expected)):
            findings.append(
                _finding(FindingLevel.WARNING, ReviewCategory.CONTRADICTION, "positive_expects_failure",
                         "expected_result", terms=_quoted(terms))
            )
    data_driven = (TestType.BOUNDARY, TestType.EQUIVALENCE, TestType.DECISION_TABLE)
    if test_type in data_driven and not draft.test_data:
        findings.append(
            _finding(FindingLevel.WARNING, ReviewCategory.EXECUTABILITY, "data_missing_for_type", "test_data")
        )
    if test_type == TestType.BOUNDARY and source is not None:
        used = numbers_in(" ".join([*draft.test_data, *draft.steps]))
        for phrase, values in boundary_hints(source):
            if not set(values) <= used:
                findings.append(
                    _finding(
                        FindingLevel.SUGGESTION, ReviewCategory.EXECUTABILITY, "boundary_values_missing",
                        "test_data", [source.id], phrase=phrase, values=", ".join(values), req=source.id,
                    )
                )
    return findings


def check_test_case(
    draft: TestCaseDraft, known_ids: set[str] | None = None, source: Requirement | None = None
) -> list[ReviewFinding]:
    """`source` is the linked requirement from the document, used for content checks."""
    findings = _check_fields(draft, TEST_CASE_REQUIRED, FindingLevel.BLOCKING)
    if not draft.requirement_id.strip() and not draft.feature.strip():
        findings.append(
            _finding(FindingLevel.BLOCKING, ReviewCategory.REQUIRED_FIELD, "subject_missing", "requirement_id")
        )
    else:
        findings += _check_requirement_link(draft.requirement_id, known_ids, required=True)
    findings += _check_fields(draft, TEST_CASE_RECOMMENDED, FindingLevel.SUGGESTION, "recommended_missing")
    findings += _check_placeholders(draft)
    findings += _check_duplicates(draft, ("preconditions", "steps"))
    findings += _check_redundant_steps(draft, "expected_result")
    findings += _check_vague(
        draft,
        {"expected_result": FindingLevel.WARNING, "steps": FindingLevel.SUGGESTION,
         "preconditions": FindingLevel.SUGGESTION, "test_data": FindingLevel.SUGGESTION},
    )
    findings += _check_test_design(draft, source)
    findings += _check_limits(draft, source)
    findings += _check_provenance(draft)
    return findings


def check_bug_report(
    draft: BugReportDraft, known_ids: set[str] | None = None, source: Requirement | None = None
) -> list[ReviewFinding]:
    findings = _check_fields(draft, BUG_REQUIRED, FindingLevel.BLOCKING)
    findings += _check_fields(draft, BUG_IMPORTANT, FindingLevel.WARNING)
    findings += _check_fields(draft, BUG_RECOMMENDED, FindingLevel.SUGGESTION, "recommended_missing")
    actual, expected = _normalized(draft.actual_result), _normalized(draft.expected_result)
    if actual and actual == expected:
        findings.append(
            _finding(FindingLevel.BLOCKING, ReviewCategory.CONTRADICTION, "actual_equals_expected", "actual_result")
        )
    findings += _check_requirement_link(draft.requirement_id, known_ids, required=False)
    findings += _check_placeholders(draft)
    findings += _check_duplicates(draft, ("preconditions", "steps"))
    findings += _check_redundant_steps(draft, "actual_result")
    findings += _check_vague(draft, {"expected_result": FindingLevel.WARNING, "steps": FindingLevel.SUGGESTION})
    findings += _check_limits(draft, source, exact_fields=("expected_result",))
    findings += _check_provenance(draft)
    return findings


def check_requirements(draft: RequirementsDraft) -> list[ReviewFinding]:
    if not draft.requirements:
        return [_finding(FindingLevel.BLOCKING, ReviewCategory.REQUIRED_FIELD, "no_requirements", "requirements")]
    known = {r.id for r in draft.requirements}
    findings = _check_rule_findings(draft)
    for statement in draft.statements:
        for req in statement.requirement_ids:
            if req not in known:
                findings.append(
                    _finding(
                        FindingLevel.BLOCKING, ReviewCategory.TRACEABILITY, "statement_unknown_requirement",
                        "statements", [req], req=req,
                    )
                )
        if statement.provenance == Provenance.ASSUMPTION:
            findings.append(
                _finding(
                    FindingLevel.WARNING, ReviewCategory.ASSUMPTION, "statement_assumption", "statements",
                    statement.requirement_ids, text=statement.text,
                )
            )
        elif statement.provenance == Provenance.AI_SUGGESTION:
            findings.append(
                _finding(
                    FindingLevel.WARNING, ReviewCategory.AI_SUGGESTION, "statement_ai", "statements",
                    statement.requirement_ids, text=statement.text,
                )
            )
    vague = [term for s in draft.statements for term in vague_terms(s.text)]
    if vague:
        findings.append(
            _finding(FindingLevel.WARNING, ReviewCategory.CLARITY, "vague_wording", "statements",
                     terms=_quoted(list(dict.fromkeys(vague))))
        )
    findings += _check_provenance(draft)
    return findings


_RULE_CATEGORY = {
    FindingType.AMBIGUOUS_WORDING: ReviewCategory.CLARITY,
    FindingType.MISSING_EXPECTED_RESULT: ReviewCategory.EXECUTABILITY,
    FindingType.MISSING_BOUNDARY: ReviewCategory.MISSING_CONDITION,
    FindingType.MISSING_ERROR_HANDLING: ReviewCategory.MISSING_CONDITION,
    FindingType.CONTRADICTION: ReviewCategory.CONTRADICTION,
}


def _rule_finding(finding: Finding) -> ReviewFinding:
    code = {
        FindingType.AMBIGUOUS_WORDING: "req_ambiguous_wording",
        FindingType.MISSING_EXPECTED_RESULT: "req_missing_expected_result",
        FindingType.MISSING_BOUNDARY: "req_missing_boundary",
        FindingType.MISSING_ERROR_HANDLING: "req_missing_error_handling",
        FindingType.CONTRADICTION: "req_contradiction",
    }[finding.type]
    return _finding(
        FindingLevel.WARNING, _RULE_CATEGORY[finding.type], code, "requirements",
        [finding.requirement_id, *finding.related_requirement_ids],
        req=finding.requirement_id,
        related=", ".join(finding.related_requirement_ids) or "—",
        terms=_quoted(finding.matched_terms) or "—",
    )


def _check_rule_findings(draft: RequirementsDraft) -> list[ReviewFinding]:
    """Rule engine findings that no clarification has addressed yet.

    A finding counts as addressed once the answer to its question is recorded
    as a statement (confirmed or assumed; assumptions are flagged separately).
    """
    addressed = {s.origin for s in draft.statements}
    return [
        _rule_finding(finding)
        for question_id, finding in requirement_findings(draft.requirements)
        if question_id not in addressed
    ]


def check_draft(
    draft: AnyDraft, known_ids: set[str] | None = None, source: Requirement | None = None
) -> list[ReviewFinding]:
    if isinstance(draft, TestCaseDraft):
        return check_test_case(draft, known_ids, source)
    if isinstance(draft, BugReportDraft):
        return check_bug_report(draft, known_ids, source)
    return check_requirements(draft)


def check_open_clarifications(session: GrillSession) -> list[ReviewFinding]:
    """Clarification questions (no draft field) that are still open.

    Questions that fill a draft field are covered by the field checks, and
    questions built from rule findings by the requirement checks, so each gap
    is reported once.
    """
    rule_ids: set[str] = set()
    if isinstance(session.draft, RequirementsDraft):
        rule_ids = {qid for qid, _ in requirement_findings(session.draft.requirements)}
    findings = []
    for question in session.unresolved_questions:
        if question.field or question.id in rule_ids or question.id.startswith(CONFLICT_PREFIX):
            continue  # conflicts are reported by check_conflicts
        answer = session.answers.get(question.id)
        status = answer.status if answer else None
        if status == AnswerStatus.SKIPPED and (question.origin == Source.AI or question.id.startswith(FOLLOWUP_PREFIX)):
            continue  # skipping an AI question or a follow-up dismisses it
        code = "question_unknown" if status == AnswerStatus.UNKNOWN else "question_open"
        findings.append(
            _finding(
                FindingLevel.WARNING, ReviewCategory.OPEN_QUESTION, code, "statements",
                question.requirement_ids, question=question.id,
            )
        )
    return findings


def check_conflicts(session: GrillSession) -> list[ReviewFinding]:
    """Clarifications that contradict a requirement or each other, not yet resolved.

    Conflicts in draft fields are reported by the limit checks, and
    contradictions between source requirements by the rule-engine checks.
    """
    return [
        _finding(
            FindingLevel.WARNING, ReviewCategory.CONTRADICTION, "answer_conflict", "statements",
            conflict.requirement_ids, first=conflict.phrases[0], second=conflict.phrases[1],
        )
        for conflict in unresolved_conflicts(session)
        if conflict.kind != ConflictKind.SOURCE and not conflict.field
    ]


def deterministic_review(session: GrillSession) -> list[ReviewFinding]:
    """Default reviewer: field checks, open clarification questions and unresolved conflicts."""
    if session.draft is None:
        return []
    draft = session.draft
    requirement_id = getattr(draft, "requirement_id", "").strip()
    source = next((r for r in session.context_requirements if r.id == requirement_id), None)
    findings = check_draft(draft, session.known_requirement_ids, source)
    findings += check_open_clarifications(session)
    findings += check_conflicts(session)
    return sort_findings(findings)


_LEVEL_ORDER = {FindingLevel.BLOCKING: 0, FindingLevel.WARNING: 1, FindingLevel.SUGGESTION: 2}


def sort_findings(findings: list[ReviewFinding]) -> list[ReviewFinding]:
    """Most severe first; the order within a level is kept."""
    return sorted(findings, key=lambda f: _LEVEL_ORDER[f.level])
