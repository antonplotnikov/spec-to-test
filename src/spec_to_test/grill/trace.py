"""Traceability and audit history of a Grill session.

`decision_records` answers, for every question of the interview: where did the
question come from (a rule finding and the words that triggered it, a
contradiction, a follow-up to an earlier answer, the AI interviewer and its
model, or an empty draft field), which requirements it is about, what was
answered, and its state:

- CONFIRMED   the author confirmed the answer (a decision);
- ASSUMPTION  accepted without confirmation (not a fact);
- UNKNOWN     the author said it is not known (no value is filled in);
- CONFLICT    the answer contradicts a requirement or another answer and the
              contradiction is not resolved yet;
- OPEN        not answered yet, or skipped.

Each record carries the full answer history from the audit log (every status
and value the answer ever had, with timestamps). Nothing is inferred: a
requirement ID appears only if the question or the draft links it and the
loaded document contains it, and an unknown or open item has no value.

`audit_rows` / `audit_json` / `trace_markdown` present the same data for the
page and for export.
"""

import json
from typing import Any

from pydantic import BaseModel, Field

from spec_to_test.exports import _md_table
from spec_to_test.grill.conflicts import (
    CONFLICT_PREFIX,
    FOLLOWUP_PREFIX,
    detect_conflicts,
    question_state,
    superseded_questions,
)
from spec_to_test.grill.models import (
    AnswerStatus,
    AuditAction,
    AuditEvent,
    ClarificationState,
    GrillSession,
    Question,
    RequirementsDraft,
    RetireReason,
)
from spec_to_test.grill.rules import RULE_QUESTION_PREFIX, requirement_findings
from spec_to_test.grill.text import field_label, render_question
from spec_to_test.i18n import t
from spec_to_test.models import FindingType, Requirement, Source


class AnswerRevision(BaseModel):
    at: str = ""
    status: AnswerStatus
    value: str = ""


class DecisionRecord(BaseModel):
    question_id: str
    question: str
    # rule | contradiction | followup | conflict | ai | field
    origin: str
    # Evidence for why the question was asked (e.g. the vague words a rule matched).
    basis: str = ""
    ai_model: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    field: str = ""
    state: ClarificationState
    status: AnswerStatus | None = None
    value: str = ""
    # The answer lost a resolved contradiction (kept for the record, not a decision).
    superseded: bool = False
    history: list[AnswerRevision] = Field(default_factory=list)


def session_requirements(session: GrillSession) -> list[Requirement]:
    if isinstance(session.draft, RequirementsDraft):
        return list(session.draft.requirements)
    return list(session.context_requirements)


def question_origin(question: Question) -> str:
    qid = question.id
    if question.origin == Source.AI:
        return "ai"
    if qid.startswith(CONFLICT_PREFIX):
        return "conflict"
    if qid.startswith(f"{RULE_QUESTION_PREFIX}contradiction."):
        return "contradiction"
    if qid.startswith(RULE_QUESTION_PREFIX):
        return "rule"
    if qid.startswith(FOLLOWUP_PREFIX):
        return "followup"
    return "field"


def _rule_basis(session: GrillSession, lang: str) -> dict[str, str]:
    """Question ID -> the rule finding behind it, in words."""
    basis = {}
    for question_id, finding in requirement_findings(session_requirements(session)):
        text = t(f"finding.{finding.type.value}", lang)
        if finding.matched_terms:
            text += ": " + ", ".join(f"“{term}”" for term in finding.matched_terms)
        if finding.type == FindingType.CONTRADICTION:
            text += " (" + ", ".join(sorted({finding.requirement_id, *finding.related_requirement_ids})) + ")"
        basis[question_id] = text
    return basis


def _linked_ids(session: GrillSession, question: Question) -> list[str]:
    known = {r.id for r in session_requirements(session)}
    ids = list(question.requirement_ids)
    if question.field and not ids:
        link = getattr(session.draft, "requirement_id", "") or ""
        ids = [link.strip()] if link.strip() else []
    return [i for i in dict.fromkeys(ids) if i in known]


def answer_history(session: GrillSession, question_id: str) -> list[AnswerRevision]:
    """Every answer the question had, oldest first, from the audit log.

    Sessions migrated from schema 1 have no log for earlier answers; their
    current answer is still listed (without a time) so it is never lost.
    """
    revisions = [
        AnswerRevision(at=e.at, status=e.status, value=e.value)
        for e in session.events
        if e.question_id == question_id and e.status is not None
        and e.action in (AuditAction.ANSWERED, AuditAction.ANSWER_CHANGED)
    ]
    answer = session.answers.get(question_id)
    if answer is not None and (not revisions or (revisions[-1].status, revisions[-1].value) != (answer.status, answer.value)):
        revisions.append(AnswerRevision(status=answer.status, value=answer.value))
    return revisions


def decision_records(session: GrillSession, lang: str = "en") -> list[DecisionRecord]:
    """One record per question, in the order asked (then the rest of the queue)."""
    conflicts = detect_conflicts(session)
    lost = superseded_questions(session)
    rule_basis = _rule_basis(session, lang)
    conflict_basis = {c.id: " ⟷ ".join(c.statements) for c in conflicts}
    order = list(dict.fromkeys([*session.history, *(q.id for q in session.questions)]))
    records = []
    for question_id in order:
        question = session.question(question_id)
        if question is None:
            continue
        answer = session.answers.get(question_id)
        origin = question_origin(question)
        basis = rule_basis.get(question_id) or conflict_basis.get(question_id, "")
        if origin == "followup":
            basis = question.params.get("answer", "") or question.params.get("phrase", "")
        elif origin == "ai":
            basis = render_question(question, lang)[1]
        keeps_value = answer is not None and answer.status in (AnswerStatus.ANSWERED, AnswerStatus.ASSUMED)
        records.append(DecisionRecord(
            question_id=question_id,
            question=render_question(question, lang)[0],
            origin=origin,
            basis=basis,
            ai_model=question.ai_model,
            requirement_ids=_linked_ids(session, question),
            field=question.field,
            state=question_state(session, question, conflicts),
            status=answer.status if answer else None,
            value=answer.value if keeps_value and answer else "",
            superseded=question_id in lost,
            history=answer_history(session, question_id),
        ))
    return records


def state_counts(records: list[DecisionRecord]) -> dict[ClarificationState, int]:
    return {state: sum(r.state == state for r in records) for state in ClarificationState}


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

def origin_text(record: DecisionRecord, lang: str = "en") -> str:
    text = t(f"grill.trace.origin.{record.origin}", lang)
    return f"{text} ({record.ai_model})" if record.ai_model else text


def event_text(event: AuditEvent, session: GrillSession, lang: str = "en") -> str:
    """One line describing an audit event."""
    question = _any_question(session, event.question_id) if event.question_id else None
    prompt = render_question(question, lang)[0] if question else event.question_id
    status = t(f"grill.answer_status.{event.status.value}", lang) if event.status else ""
    if event.action == AuditAction.ANSWERED:
        return t("grill.audit.text.answered", lang, question=prompt, status=status, value=event.value or "—")
    if event.action == AuditAction.ANSWER_CHANGED:
        before = t(f"grill.answer_status.{event.previous_status.value}", lang) if event.previous_status else ""
        return t("grill.audit.text.answer_changed", lang, question=prompt, before=before,
                 before_value=event.previous_value or "—", status=status, value=event.value or "—")
    if event.action == AuditAction.QUESTION_ADDED:
        return t("grill.audit.text.question_added", lang, question=prompt, model=event.detail or "AI")
    if event.action == AuditAction.DRAFT_EDITED:
        return t("grill.audit.text.draft_edited", lang, fields=", ".join(field_label(f, lang) for f in event.fields) or "—")
    if event.action == AuditAction.QUESTION_RETIRED:
        return t("grill.audit.text.question_retired", lang, question=prompt, reason=retire_reason_text(session, event.detail, lang))
    if event.action == AuditAction.QUESTION_RESTORED:
        return t("grill.audit.text.question_restored", lang, question=prompt)
    if event.action == AuditAction.FINDINGS_SYNCED:
        parts = dict(part.split(": ", 1) for part in event.detail.split("; ") if ": " in part)
        return t("grill.audit.text.findings_synced", lang, resolved=parts.get("resolved", "—"),
                 reopened=parts.get("reopened", "—"))
    return t(f"grill.audit.action.{event.action.value}", lang)


def _any_question(session: GrillSession, question_id: str) -> Question | None:
    """An active or retired question."""
    retired = session.retired_question(question_id)
    return session.question(question_id) or (retired.question if retired else None)


def retire_reason_text(session: GrillSession, detail: str, lang: str = "en") -> str:
    """ "answered_elsewhere:<question id>" -> "already answered by “<question>”"."""
    reason, _, other_id = detail.partition(":")
    other = _any_question(session, other_id) if other_id else None
    other_text = render_question(other, lang)[0] if other else other_id
    try:
        return t(f"grill.retire_reason.{RetireReason(reason).value}", lang, other=other_text)
    except ValueError:
        return detail


def audit_rows(session: GrillSession, lang: str = "en") -> list[dict[str, str]]:
    """The audit log, newest first, for a table."""
    return [
        {
            t("grill.audit.col_time", lang): (event.at[:19].replace("T", " ") if event.at else "—"),
            t("grill.audit.col_action", lang): t(f"grill.audit.action.{event.action.value}", lang),
            t("grill.audit.col_detail", lang): event_text(event, session, lang),
        }
        for event in reversed(session.events)
    ]


def audit_data(session: GrillSession, lang: str = "en") -> dict[str, Any]:
    """Everything needed to audit the session, as plain data."""
    return {
        "session_id": session.id,
        "kind": session.kind.value,
        "artifact": session.artifact.value,
        "step": session.step.value,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "requirements": [{"id": r.id, "text": r.text} for r in session_requirements(session)],
        "decisions": [r.model_dump(mode="json") for r in decision_records(session, lang)],
        "events": [e.model_dump(mode="json") for e in session.events],
    }


def audit_json(session: GrillSession, lang: str = "en") -> str:
    return json.dumps(audit_data(session, lang), ensure_ascii=False, indent=1)


def audit_file_name(session: GrillSession) -> str:
    return f"grill-audit-{session.id[:8]}.json"


def trace_markdown(session: GrillSession, lang: str = "en") -> str:
    """The decision trace as a Markdown section (appended to the downloaded result)."""
    records = decision_records(session, lang)
    out = [f"## {t('grill.trace.heading', lang)}", "", f"_{t('grill.trace.note', lang)}_", ""]
    if not records:
        return "\n".join([*out, t("grill.trace.none", lang), ""])
    rows: list[list[object]] = []
    for record in records:
        history = "; ".join(
            f"{t(f'grill.answer_status.{rev.status.value}', lang)}"
            + (f": {rev.value}" if rev.value else "")
            + (f" ({rev.at[:16].replace('T', ' ')})" if rev.at else "")
            for rev in record.history
        )
        rows.append([
            record.question,
            origin_text(record, lang) + (f" — {record.basis}" if record.basis else ""),
            ", ".join(record.requirement_ids) or "—",
            t(f"grill.state.{record.state.value}", lang) + (f" ({t('grill.trace.superseded', lang)})" if record.superseded else ""),
            record.value or "—",
            history or "—",
        ])
    out += _md_table(
        [t("grill.ui.column_question", lang), t("grill.trace.col_source", lang), t("grill.ui.column_requirements", lang),
         t("grill.ui.column_state", lang), t("grill.ui.column_answer", lang), t("grill.trace.col_history", lang)],
        rows,
    )
    return "\n".join(out) + "\n"

