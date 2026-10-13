"""Contradictions found during a Grill interview, and the state of every question.

Detection is deterministic and reuses the rule engine's limit parsing
(`rules.compare_limits`), so nothing is guessed:

- SOURCE: two source requirements contradict each other (a rule-engine
  contradiction finding). Its rule question resolves it.
- REQUIREMENT: a confirmed or assumed answer states a limit that differs from
  the linked requirement ("at least 10" vs "at least 8 characters").
- ANSWERS: two answers about the same requirement state different limits.

REQUIREMENT and ANSWERS conflicts get a resolution question from the planner
(ID `conflict.<digest>`). A conflict is resolved once that question is
answered (confirmed or assumed); answering "unknown" leaves it open. The
answers that lost a resolved conflict are "superseded": the report keeps
them in the contradiction record instead of listing them as decisions.
"""

import hashlib
from enum import StrEnum

from pydantic import BaseModel, Field

from spec_to_test.grill.models import (
    DECISION_PREFIXES,
    AnswerStatus,
    BugReportDraft,
    ClarificationState,
    GrillSession,
    Question,
    RequirementsDraft,
)
from spec_to_test.grill.rules import RULE_QUESTION_PREFIX, compare_limits
from spec_to_test.models import Requirement

CONFLICT_PREFIX = "conflict."
FOLLOWUP_PREFIX = "followup."
_CONFIRMING = (AnswerStatus.ANSWERED, AnswerStatus.ASSUMED)
# Field answers that are never compared with a requirement's limits:
# chosen values, and test inputs (a boundary test enters "7 characters" on purpose).
_NOT_COMPARED = frozenset({"requirement_id", "test_type", "severity", "priority", "reproducibility", "test_data"})


class ConflictKind(StrEnum):
    SOURCE = "source"
    REQUIREMENT = "requirement"
    ANSWERS = "answers"


class Conflict(BaseModel):
    id: str
    kind: ConflictKind
    requirement_ids: list[str]
    # Questions whose answers take part (empty for a SOURCE conflict).
    question_ids: list[str] = Field(default_factory=list)
    # The conflicting statements, verbatim: "REQ-2: <text>" or an answer.
    statements: list[str]
    # The disagreeing phrases, e.g. ("at least 10 characters", "at least 8 characters").
    phrases: list[str] = Field(default_factory=list)
    # Draft field the resolution fills ("" = a clarification statement).
    field: str = ""
    resolved: bool = False
    resolution: str = ""


def is_decision(question_id: str) -> bool:
    """A question that chooses between conflicting statements."""
    return question_id.startswith(DECISION_PREFIXES)


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:10]


def _requirement_text(requirement: Requirement) -> str:
    return f"{requirement.id}: {requirement.text}"


def _requirements(session: GrillSession) -> dict[str, Requirement]:
    found = {r.id: r for r in session.context_requirements}
    if isinstance(session.draft, RequirementsDraft):
        found |= {r.id: r for r in session.draft.requirements}
    return found


def _compared_answers(session: GrillSession) -> list[tuple[Question, str, list[str]]]:
    """(question, answer text, requirement IDs it is about) for confirmed or assumed answers.

    Answers to conflict questions and to source contradictions are decisions
    between conflicting statements, so they are not checked again (that would
    ask the same question forever).
    """
    draft = session.draft
    link = getattr(draft, "requirement_id", "").strip()
    result = []
    for question in session.questions:
        answer = session.answers.get(question.id)
        if answer is None or answer.status not in _CONFIRMING or is_decision(question.id):
            continue
        if question.field in _NOT_COMPARED:
            continue
        ids = list(question.requirement_ids) if not question.field else ([link] if link else [])
        if isinstance(draft, BugReportDraft) and question.field != "expected_result":
            continue  # a bug's actual result and steps may legitimately differ from the requirement
        result.append((question, answer.value, ids))
    return result


def _resolution(session: GrillSession, conflict_id: str) -> tuple[bool, str]:
    answer = session.answers.get(conflict_id)
    if answer is not None and answer.status in _CONFIRMING:
        return True, answer.value
    return False, ""


def detect_conflicts(session: GrillSession) -> list[Conflict]:
    """Every contradiction known so far, resolved or not, in a stable order."""
    if session.draft is None:
        return []
    requirements = _requirements(session)
    conflicts: list[Conflict] = []

    # SOURCE: rule-engine contradictions between requirements (requirements Grill only).
    if isinstance(session.draft, RequirementsDraft):
        for question in session.questions:
            if not question.id.startswith(f"{RULE_QUESTION_PREFIX}contradiction."):
                continue
            ids = [i for i in question.requirement_ids if i in requirements]
            resolved, resolution = _resolution(session, question.id)
            conflicts.append(Conflict(
                id=question.id, kind=ConflictKind.SOURCE, requirement_ids=sorted(ids),
                statements=[_requirement_text(requirements[i]) for i in sorted(ids)],
                resolved=resolved, resolution=resolution,
            ))

    answers = _compared_answers(session)
    # REQUIREMENT: an answer states a limit that differs from its requirement.
    for question, text, ids in answers:
        for rid in ids:
            requirement = requirements.get(rid)
            if requirement is None:
                continue
            for kind, stated, source in compare_limits(text, requirement):
                if kind != "conflict" or source is None:
                    continue
                conflict_id = CONFLICT_PREFIX + _digest("req", question.id, rid, stated.phrase, source.phrase)
                resolved, resolution = _resolution(session, conflict_id)
                conflicts.append(Conflict(
                    id=conflict_id, kind=ConflictKind.REQUIREMENT, requirement_ids=[rid],
                    question_ids=[question.id], statements=[_requirement_text(requirement), text],
                    phrases=[stated.phrase, source.phrase], field=question.field,
                    resolved=resolved, resolution=resolution,
                ))

    # ANSWERS: two clarifications about the same requirement disagree.
    statements = [(q, text, ids) for q, text, ids in answers if not q.field]
    for n, (first, first_text, first_ids) in enumerate(statements):
        for second, second_text, second_ids in statements[n + 1:]:
            shared = sorted(set(first_ids) & set(second_ids))
            if not shared:
                continue
            as_rule = Requirement(id=shared[0], text=first_text)
            for kind, stated, source in compare_limits(second_text, as_rule):
                if kind != "conflict" or source is None:
                    continue
                conflict_id = CONFLICT_PREFIX + _digest("ans", first.id, second.id, stated.phrase, source.phrase)
                resolved, resolution = _resolution(session, conflict_id)
                conflicts.append(Conflict(
                    id=conflict_id, kind=ConflictKind.ANSWERS, requirement_ids=shared,
                    question_ids=[first.id, second.id], statements=[first_text, second_text],
                    phrases=[source.phrase, stated.phrase], resolved=resolved, resolution=resolution,
                ))

    unique: dict[str, Conflict] = {}
    for conflict in conflicts:
        unique.setdefault(conflict.id, conflict)
    return list(unique.values())


def unresolved_conflicts(session: GrillSession) -> list[Conflict]:
    return [c for c in detect_conflicts(session) if not c.resolved]


def superseded_questions(session: GrillSession) -> set[str]:
    """Questions whose answer lost a resolved conflict.

    The resolution is the chosen statement or a new text; an answer that is
    not the chosen statement is superseded by it.
    """
    lost: set[str] = set()
    for conflict in detect_conflicts(session):
        if not conflict.resolved or conflict.kind == ConflictKind.SOURCE:
            continue
        chosen = " ".join(conflict.resolution.split()).casefold()
        for question_id in conflict.question_ids:
            answer = session.answers.get(question_id)
            if answer is not None and " ".join(answer.value.split()).casefold() != chosen:
                lost.add(question_id)
    return lost


def contested(session: GrillSession) -> tuple[set[str], set[str]]:
    """(question IDs, draft fields) whose value is in an open contradiction or lost a resolved one.

    Such values are not decisions: the report lists them under contradictions,
    and they never resolve a finding in the workspace.
    """
    questions = superseded_questions(session)
    fields: set[str] = set()
    for conflict in detect_conflicts(session):
        if not conflict.resolved:
            questions |= set(conflict.question_ids)
            if conflict.field:
                fields.add(conflict.field)
    return questions, fields


def question_state(session: GrillSession, question: Question, conflicts: list[Conflict] | None = None) -> ClarificationState:
    """CONFIRMED, ASSUMPTION, UNKNOWN, CONFLICT or OPEN for one question."""
    answer = session.answers.get(question.id)
    if answer is None or answer.status == AnswerStatus.SKIPPED:
        return ClarificationState.OPEN
    if answer.status == AnswerStatus.UNKNOWN:
        return ClarificationState.UNKNOWN
    open_conflicts = [c for c in (conflicts if conflicts is not None else detect_conflicts(session)) if not c.resolved]
    if any(question.id in c.question_ids for c in open_conflicts):
        return ClarificationState.CONFLICT
    return ClarificationState.CONFIRMED if answer.status == AnswerStatus.ANSWERED else ClarificationState.ASSUMPTION


def question_states(session: GrillSession) -> dict[str, ClarificationState]:
    conflicts = detect_conflicts(session)
    return {q.id: question_state(session, q, conflicts) for q in session.questions}
