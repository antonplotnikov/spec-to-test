"""Deterministic question banks: what to ask next, without AI.

The planner looks at the current draft and returns the questions that are
still relevant. It runs again after every answer, so a question disappears
once its field is filled, and follow-up questions (e.g. test data for a
boundary test) appear only when they apply. Already handled questions are
kept by the workflow and never asked twice.

Every question has a priority (high / medium / low): the workflow always asks
the highest-priority open question next, so the queue is re-ranked after each
answer. Answers also add questions (adaptive follow-ups):
- a conflict between an answer and a requirement, or between two answers,
  becomes a high-priority question that asks which statement is correct
  (`grill.conflicts`);
- a clarification that is itself vague ("fast") asks for a testable value;
- a clarification that sets a new limit asks what happens outside it, unless
  the requirement or an answer already says.

Rules:
- Only empty fields are asked about; values the user marked unknown are not
  asked again. A placeholder such as "TBD" counts as empty.
- Enumerated fields offer choices; everything else accepts free text.
- Requirement IDs are offered only from the loaded document, never invented.
- Requirement questions come from the existing rule engine findings and keep
  the real requirement IDs.
"""

from spec_to_test.grill.conflicts import (
    FOLLOWUP_PREFIX,
    ConflictKind,
    contested,
    detect_conflicts,
    is_decision,
)
from spec_to_test.grill.drafts import AnyDraft, field_is_empty
from spec_to_test.grill.models import (
    AnswerStatus,
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
from spec_to_test.grill.rules import boundary_hints, describes_failure, requirement_findings, vague_terms
from spec_to_test.grill.validation import deterministic_review, is_placeholder
from spec_to_test.grill.workflow import GrillWorkflow
from spec_to_test.models import FindingType, Requirement, Severity, Source, TestType
from spec_to_test.test_design import extract_constraints

# Test types whose steps are driven by concrete input values.
DATA_DRIVEN_TYPES = frozenset({TestType.BOUNDARY, TestType.EQUIVALENCE, TestType.DECISION_TABLE})
FAILURE_TYPES = frozenset({TestType.NEGATIVE, TestType.ERROR_HANDLING})
# Requirement findings that must be answered (or marked unknown / assumed).
ESSENTIAL_FINDINGS = frozenset({FindingType.CONTRADICTION, FindingType.MISSING_EXPECTED_RESULT})
# Priority of each rule finding's question: a test cannot be judged without the first two.
FINDING_PRIORITY = {
    FindingType.CONTRADICTION: "high",
    FindingType.MISSING_EXPECTED_RESULT: "high",
    FindingType.MISSING_ERROR_HANDLING: "medium",
    FindingType.MISSING_BOUNDARY: "medium",
    FindingType.AMBIGUOUS_WORDING: "medium",
}
_CONFIRMING = (AnswerStatus.ANSWERED, AnswerStatus.ASSUMED)
# Limits a user can go beyond (and that therefore need an "outside the limit" answer).
INPUT_LIMIT_UNITS = frozenset({"characters", "attempts", "megabytes"})

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
    priority: str = "",
) -> Question:
    """Question that fills one draft field. `key` selects a prompt variant.

    Priority defaults to high for essential questions and medium otherwise.
    """
    key = key or f"{prefix}.{field}"
    return Question(
        id=f"{prefix}.{field}",
        field=field,
        prompt_key=f"grill.q.{key}",
        reason_key=f"grill.why.{key}",
        essential=essential,
        choices=choices or [],
        allow_free_text=allow_free_text,
        importance=priority or ("high" if essential else "medium"),  # type: ignore[arg-type]
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
            importance="medium",
        )
    ]


def _requirement_link_question(prefix: str, session: GrillSession, *, essential: bool = False) -> Question:
    """Pick a requirement from the document; free text only when no document is loaded."""
    if session.context_requirements:
        return _ask(
            prefix, "requirement_id", essential=essential, priority="high",
            choices=_requirement_choices(session.context_requirements), allow_free_text=False,
        )
    return _ask(prefix, "requirement_id", key=f"{prefix}.requirement_id_free", essential=essential, priority="low")


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
        # The feature is asked once it is clear there is no requirement to link
        # (at once when no document is loaded: there is nothing to link to).
        link_handled = (
            "tc.requirement_id" in session.answers or not _needs_value(draft, "requirement_id")
            or not session.context_requirements
        )
        if link_handled and _needs_value(draft, "feature"):
            questions.append(_ask(p, "feature"))
    if _needs_value(draft, "title"):
        questions.append(_ask(p, "title"))
    if _needs_value(draft, "objective"):
        questions.append(_ask(p, "objective", essential=False, priority="low"))
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
        return _ask("tc", "test_data", essential=essential, priority="" if essential else "low")
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
        importance="high",
    )


# ---------------------------------------------------------------------------
# Bug report
# ---------------------------------------------------------------------------

def plan_bug_report(session: GrillSession, draft: BugReportDraft) -> list[Question]:
    p = "bug"
    questions: list[Question] = []
    for field, essential, priority in (
        ("summary", True, "high"), ("environment", True, "medium"), ("app_version", True, "medium"),
        ("preconditions", False, "low"), ("steps", True, "high"), ("actual_result", True, "high"),
        ("expected_result", True, "high"),
    ):
        if _needs_value(draft, field):
            questions.append(_ask(p, field, essential=essential, priority=priority))
    if _needs_value(draft, "reproducibility"):
        questions.append(
            _ask(p, "reproducibility", allow_free_text=False, priority="medium",
                 choices=_enum_choices([r.value for r in Reproducibility], "grill.reproducibility"))
        )
    if _needs_value(draft, "evidence"):
        questions.append(_ask(p, "evidence", essential=False, priority="low"))
    if _needs_value(draft, "severity"):
        questions.append(
            _ask(p, "severity", allow_free_text=False, choices=_enum_choices([s.value for s in Severity], "severity"))
        )
    if _needs_value(draft, "priority"):
        questions.append(
            _ask(p, "priority", allow_free_text=False, priority="medium",
                 choices=_enum_choices([v.value for v in Priority], "grill.priority"))
        )
    # Optional link; offered only when a document is loaded (an ID cannot be checked otherwise).
    if session.context_requirements and _needs_value(draft, "requirement_id"):
        link = _requirement_link_question(p, session)
        questions.append(link.model_copy(update={"importance": "medium"}))
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
                importance=FINDING_PRIORITY.get(finding.type, "medium"),  # type: ignore[arg-type]
            )
        )
    return questions


# ---------------------------------------------------------------------------
# Adaptive questions: built from the answers so far
# ---------------------------------------------------------------------------

def _short(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def conflict_questions(session: GrillSession) -> list[Question]:
    """One question per contradiction found in the answers: which statement is correct?

    For a clarification the conflicting statements are offered verbatim; for a
    draft field the user writes the correct value. Nothing is chosen for them.
    """
    questions = []
    for conflict in detect_conflicts(session):
        if conflict.kind == ConflictKind.SOURCE:
            continue  # asked by the rule question for that contradiction
        statement = not conflict.field
        questions.append(Question(
            id=conflict.id,
            field=conflict.field,
            prompt_key=f"grill.q.conflict.{conflict.kind.value}",
            reason_key="grill.why.conflict",
            params={
                "first": conflict.phrases[0], "second": conflict.phrases[1],
                "reqs": ", ".join(conflict.requirement_ids),
            },
            choices=[Choice(value=s, label_text=_short(s)) for s in conflict.statements] if statement else [],
            essential=True,
            requirement_ids=list(conflict.requirement_ids),
            origin=Source.RULE,
            importance="high",
        ))
    return questions


def followup_questions(session: GrillSession, draft: RequirementsDraft) -> list[Question]:
    """Follow-ups to clarifications that are vague or set a limit without saying what happens beyond it."""
    texts = {r.id: r.text for r in draft.requirements}
    disputed = contested(session)[0]  # contradicted or overruled answers raise no follow-ups
    confirmed = [
        (q, session.answers[q.id].value) for q in session.questions
        if not q.field and q.id in session.answers and session.answers[q.id].status in _CONFIRMING
        and q.id not in disputed
    ]
    questions = []
    for question, value in confirmed:
        if is_decision(question.id) or question.id.startswith(FOLLOWUP_PREFIX):
            continue  # one level of follow-ups; decisions are not questioned again
        ids = list(question.requirement_ids)
        if terms := vague_terms(value):
            questions.append(Question(
                id=f"{FOLLOWUP_PREFIX}vague.{question.id}",
                prompt_key="grill.q.followup.vague",
                reason_key="grill.why.followup.vague",
                params={"terms": ", ".join(f"“{term}”" for term in terms), "answer": _short(value)},
                essential=False, requirement_ids=ids, origin=Source.RULE, importance="medium",
            ))
        # Input limits only: "within 2 seconds" is a target, not something a user can exceed.
        constraints = [
            c for c in extract_constraints(value) if c.unit in INPUT_LIMIT_UNITS and c.kind != "exact"
        ]
        related = [value, *(texts[i] for i in ids if i in texts)]
        related += [v for q, v in confirmed if set(q.requirement_ids) & set(ids)]
        if constraints and not any(describes_failure(text) for text in related):
            questions.append(Question(
                id=f"{FOLLOWUP_PREFIX}limit.{question.id}",
                prompt_key="grill.q.followup.limit",
                reason_key="grill.why.followup.limit",
                params={"phrase": constraints[0].phrase},
                essential=False, requirement_ids=ids, origin=Source.RULE, importance="medium",
            ))
    return questions


def plan_questions(session: GrillSession) -> list[Question]:
    """Default planner for every Grill kind (QA Review asks no questions)."""
    draft = session.draft
    if draft is None:
        return []
    # Conflicts and follow-ups come first: among equal priorities, the
    # question an answer just raised is asked next.
    adaptive = conflict_questions(session)
    if isinstance(draft, TestCaseDraft):
        return adaptive + plan_test_case(session, draft)
    if isinstance(draft, BugReportDraft):
        return adaptive + plan_bug_report(session, draft)
    return adaptive + followup_questions(session, draft) + plan_requirements(session, draft)


# The deterministic Grill: works without an API key or network access.
DETERMINISTIC_WORKFLOW = GrillWorkflow(planner=plan_questions, reviewer=deterministic_review)
