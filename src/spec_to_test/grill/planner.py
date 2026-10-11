"""Deterministic question banks: what to ask next, without AI.

The planner looks at the current draft and returns the questions that are
still relevant. It runs again after every answer, so a question disappears
once its field is filled, and follow-up questions (e.g. test data for a
boundary test) appear only when they apply. Already handled questions are
kept by the workflow and never asked twice.

Rules:
- Only empty fields are asked about; values the user marked unknown are not
  asked again. A placeholder such as "TBD" counts as empty.
- Enumerated fields offer choices; everything else accepts free text.
- Requirement IDs are offered only from the loaded document, never invented.
- Requirement questions come from the existing rule engine findings and keep
  the real requirement IDs.
"""

from spec_to_test.grill.drafts import AnyDraft, field_is_empty
from spec_to_test.grill.models import (
    BugReportDraft,
    Choice,
    GrillSession,
    Priority,
    Provenance,
    Question,
    Reproducibility,
    RequirementsDraft,
    TestCaseDraft,
)
from spec_to_test.grill.rules import boundary_hints, requirement_findings, vague_terms
from spec_to_test.grill.validation import deterministic_review, is_placeholder
from spec_to_test.grill.workflow import GrillWorkflow
from spec_to_test.models import FindingType, Requirement, Severity, Source, TestType

# Test types whose steps are driven by concrete input values.
DATA_DRIVEN_TYPES = frozenset({TestType.BOUNDARY, TestType.EQUIVALENCE, TestType.DECISION_TABLE})
FAILURE_TYPES = frozenset({TestType.NEGATIVE, TestType.ERROR_HANDLING})
# Requirement findings that must be answered (or marked unknown / assumed).
ESSENTIAL_FINDINGS = frozenset({FindingType.CONTRADICTION, FindingType.MISSING_EXPECTED_RESULT})

_LABEL_CHARS = 80


def _needs_value(draft: AnyDraft, field: str) -> bool:
    """Empty (and not marked unknown), or filled with a placeholder."""
    if draft.provenance.get(field) == Provenance.UNKNOWN:
        return False
    if field_is_empty(draft, field):
        return True
    value = getattr(draft, field)
    items = value if isinstance(value, list) else [value]
    return all(isinstance(item, str) and is_placeholder(item) for item in items)


def _ask(
    prefix: str,
    field: str,
    *,
    key: str = "",
    essential: bool = True,
    choices: list[Choice] | None = None,
    allow_free_text: bool = True,
) -> Question:
    """Question that fills one draft field. `key` selects a prompt variant."""
    key = key or f"{prefix}.{field}"
    return Question(
        id=f"{prefix}.{field}",
        field=field,
        prompt_key=f"grill.q.{key}",
        reason_key=f"grill.why.{key}",
        essential=essential,
        choices=choices or [],
        allow_free_text=allow_free_text,
    )


def _enum_choices(values: list[str], label_prefix: str) -> list[Choice]:
    return [Choice(value=v, label_key=f"{label_prefix}.{v}") for v in values]


def _requirement_choices(requirements: list[Requirement]) -> list[Choice]:
    def short(text: str) -> str:
        return text if len(text) <= _LABEL_CHARS else text[: _LABEL_CHARS - 1].rstrip() + "…"

    return [Choice(value=r.id, label_text=f"{r.id} — {short(r.text)}") for r in requirements]


def _linked(session: GrillSession, requirement_id: str) -> Requirement | None:
    return next((r for r in session.context_requirements if r.id == requirement_id.strip()), None)


def _vague_question(prefix: str, draft: AnyDraft, field: str) -> list[Question]:
    """Follow-up when an expected result is filled but not checkable."""
    value = getattr(draft, field)
    if not value or is_placeholder(value) or not (terms := vague_terms(value)):
        return []
    return [
        Question(
            id=f"{prefix}.{field}.vague",
            field=field,
            prompt_key="grill.q.expected_result_vague",
            reason_key="grill.why.expected_result_vague",
            params={"terms": ", ".join(f"“{term}”" for term in terms)},
            essential=False,
        )
    ]


def _requirement_link_question(prefix: str, session: GrillSession, *, essential: bool = False) -> Question:
    """Pick a requirement from the document; free text only when no document is loaded."""
    if session.context_requirements:
        return _ask(
            prefix, "requirement_id", essential=essential,
            choices=_requirement_choices(session.context_requirements), allow_free_text=False,
        )
    return _ask(prefix, "requirement_id", key=f"{prefix}.requirement_id_free", essential=essential)


# ---------------------------------------------------------------------------
# Test case
# ---------------------------------------------------------------------------

def plan_test_case(session: GrillSession, draft: TestCaseDraft) -> list[Question]:
    p = "tc"
    questions: list[Question] = []
    test_type = draft.test_type
    failure = test_type in FAILURE_TYPES

    if not draft.requirement_id.strip() and not draft.feature.strip():
        if _needs_value(draft, "requirement_id"):
            questions.append(_requirement_link_question(p, session))
        # The feature is asked once it is clear there is no requirement to link.
        link_handled = "tc.requirement_id" in session.answers or not _needs_value(draft, "requirement_id")
        if link_handled and _needs_value(draft, "feature"):
            questions.append(_ask(p, "feature"))
    if _needs_value(draft, "title"):
        questions.append(_ask(p, "title"))
    if _needs_value(draft, "objective"):
        questions.append(_ask(p, "objective", essential=False))
    if _needs_value(draft, "test_type"):
        questions.append(
            _ask(p, "test_type", choices=_enum_choices([t.value for t in TestType], "test_type"),
                 allow_free_text=False)
        )
    if _needs_value(draft, "preconditions"):
        questions.append(_ask(p, "preconditions", essential=False))
    if test_type is not None and _needs_value(draft, "test_data"):
        questions.append(_test_data_question(session, draft, test_type))
    if _needs_value(draft, "steps"):
        questions.append(_ask(p, "steps"))
    if _needs_value(draft, "expected_result"):
        key = "tc.expected_result_negative" if failure else "tc.expected_result"
        questions.append(_ask(p, "expected_result", key=key))
    questions += _vague_question(p, draft, "expected_result")
    return questions


def _test_data_question(session: GrillSession, draft: TestCaseDraft, test_type: TestType) -> Question:
    essential = test_type in DATA_DRIVEN_TYPES
    if test_type in FAILURE_TYPES:
        return _ask("tc", "test_data", key="tc.test_data_negative", essential=False)
    if test_type != TestType.BOUNDARY:
        return _ask("tc", "test_data", essential=essential)
    linked = _linked(session, draft.requirement_id)
    hints = boundary_hints(linked) if linked else []
    if not hints:
        return _ask("tc", "test_data", key="tc.test_data_boundary")
    phrase, values = hints[0]
    return Question(
        id="tc.test_data",
        field="test_data",
        prompt_key="grill.q.tc.test_data_boundary",
        reason_key="grill.why.tc.test_data_boundary_values",
        params={"phrase": phrase, "values": ", ".join(values)},
        requirement_ids=[linked.id] if linked else [],
    )


# ---------------------------------------------------------------------------
# Bug report
# ---------------------------------------------------------------------------

def plan_bug_report(session: GrillSession, draft: BugReportDraft) -> list[Question]:
    p = "bug"
    questions: list[Question] = []
    for field, essential in (
        ("summary", True), ("environment", True), ("app_version", True), ("preconditions", False),
        ("steps", True), ("actual_result", True), ("expected_result", True),
    ):
        if _needs_value(draft, field):
            questions.append(_ask(p, field, essential=essential))
    if _needs_value(draft, "reproducibility"):
        questions.append(
            _ask(p, "reproducibility", allow_free_text=False,
                 choices=_enum_choices([r.value for r in Reproducibility], "grill.reproducibility"))
        )
    if _needs_value(draft, "evidence"):
        questions.append(_ask(p, "evidence", essential=False))
    if _needs_value(draft, "severity"):
        questions.append(
            _ask(p, "severity", allow_free_text=False, choices=_enum_choices([s.value for s in Severity], "severity"))
        )
    if _needs_value(draft, "priority"):
        questions.append(
            _ask(p, "priority", allow_free_text=False,
                 choices=_enum_choices([v.value for v in Priority], "grill.priority"))
        )
    # Optional link; offered only when a document is loaded (an ID cannot be checked otherwise).
    if session.context_requirements and _needs_value(draft, "requirement_id"):
        questions.append(_requirement_link_question(p, session))
    questions += _vague_question(p, draft, "expected_result")
    return questions


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

def plan_requirements(session: GrillSession, draft: RequirementsDraft) -> list[Question]:
    """One clarification question per rule finding, linked to real requirement IDs."""
    texts = {r.id: r.text for r in draft.requirements}
    questions = []
    for question_id, finding in requirement_findings(draft.requirements):
        ids = [finding.requirement_id, *finding.related_requirement_ids]
        choices = []
        if finding.type == FindingType.CONTRADICTION:
            # Offer each conflicting rule verbatim; the user may also write a new one.
            choices = [Choice(value=f"{i}: {texts[i]}", label_text=f"{i}: {texts[i]}") for i in sorted(ids)]
        questions.append(
            Question(
                id=question_id,
                prompt_key=f"question.{finding.type.value}",
                reason_key=f"grill.why.req.{finding.type.value}",
                params={
                    "terms": ", ".join(f"\"{term}\"" for term in finding.matched_terms) or "—",
                    "related": ", ".join(finding.related_requirement_ids) or "—",
                },
                choices=choices,
                essential=finding.type in ESSENTIAL_FINDINGS,
                requirement_ids=ids,
                origin=Source.RULE,
            )
        )
    return questions


def plan_questions(session: GrillSession) -> list[Question]:
    """Default planner for every Grill kind (QA Review asks no questions)."""
    draft = session.draft
    if isinstance(draft, TestCaseDraft):
        return plan_test_case(session, draft)
    if isinstance(draft, BugReportDraft):
        return plan_bug_report(session, draft)
    if isinstance(draft, RequirementsDraft):
        return plan_requirements(session, draft)
    return []


# The deterministic Grill: works without an API key or network access.
DETERMINISTIC_WORKFLOW = GrillWorkflow(planner=plan_questions, reviewer=deterministic_review)
