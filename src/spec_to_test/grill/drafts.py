"""Apply answers and direct edits to drafts, recording where each value came from."""

from typing import Any, get_origin

from pydantic import ValidationError

from spec_to_test.grill.models import (
    Answer,
    AnswerStatus,
    BugReportDraft,
    Provenance,
    Question,
    RequirementsDraft,
    Statement,
    TestCaseDraft,
)
from spec_to_test.input_parser import MAX_TEXT_CHARS

AnyDraft = TestCaseDraft | BugReportDraft | RequirementsDraft

# Bookkeeping fields that answers and edits may not set directly.
_PROTECTED_FIELDS = {"draft_type", "provenance", "requirements", "statements"}

_ANSWER_PROVENANCE = {
    AnswerStatus.ANSWERED: Provenance.USER_CONFIRMED,
    AnswerStatus.ASSUMED: Provenance.ASSUMPTION,
}


class DraftError(ValueError):
    """An answer or edit that does not fit the draft. `code` maps to grill.error.<code>."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def editable_fields(draft: AnyDraft) -> list[str]:
    """Fields a question or a direct edit may fill, in declaration order."""
    return [name for name in type(draft).model_fields if name not in _PROTECTED_FIELDS]


def is_list_field(draft: AnyDraft, field: str) -> bool:
    return get_origin(type(draft).model_fields[field].annotation) is list


def field_is_empty(draft: AnyDraft, field: str) -> bool:
    value = getattr(draft, field)
    return value is None or (isinstance(value, str | list) and not value)


def split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def check_length(text: str) -> None:
    """One answer or field may be as long as a whole analyzed document, not longer."""
    if len(text) > MAX_TEXT_CHARS:
        raise DraftError("too_long")


def _with(draft: AnyDraft, updates: dict[str, Any]) -> AnyDraft:
    try:
        return type(draft).model_validate({**draft.model_dump(), **updates})
    except ValidationError as exc:
        raise DraftError("invalid_answer") from exc


def _empty_value(draft: AnyDraft, field: str) -> Any:
    if is_list_field(draft, field):
        return []
    return None if type(draft).model_fields[field].default is None else ""


def set_field(draft: AnyDraft, field: str, raw: str, provenance: Provenance) -> AnyDraft:
    """Set one field from text (list fields take one item per line)."""
    if field not in editable_fields(draft):
        raise DraftError("invalid_field")
    check_length(raw)
    value: Any = split_lines(raw) if is_list_field(draft, field) else raw.strip()
    if value in ("", []):
        raise DraftError("invalid_answer")
    updated = _with(draft, {field: value})
    updated.provenance = {**draft.provenance, field: provenance}
    return updated


def mark_unknown(draft: AnyDraft, field: str) -> AnyDraft:
    """Clear a field and record that the user does not know its value."""
    if field not in editable_fields(draft):
        raise DraftError("invalid_field")
    updated = _with(draft, {field: _empty_value(draft, field)})
    updated.provenance = {**draft.provenance, field: Provenance.UNKNOWN}
    return updated


def apply_answer(draft: AnyDraft, question: Question, answer: Answer) -> AnyDraft:
    """Return the draft updated with one answer. The input draft is not modified."""
    if answer.status == AnswerStatus.SKIPPED:
        return draft
    if not question.field:
        if not isinstance(draft, RequirementsDraft):
            raise DraftError("invalid_field")
        return _apply_statement(draft, question, answer)
    if answer.status == AnswerStatus.UNKNOWN:
        return mark_unknown(draft, question.field)
    return set_field(draft, question.field, answer.value, _ANSWER_PROVENANCE[answer.status])


def _apply_statement(draft: RequirementsDraft, question: Question, answer: Answer) -> RequirementsDraft:
    """Replace the clarification produced by this question (or drop it if unknown)."""
    statements = [s for s in draft.statements if s.origin != question.id]
    if answer.status in _ANSWER_PROVENANCE:
        statements.append(
            Statement(
                text=answer.value.strip(),
                provenance=_ANSWER_PROVENANCE[answer.status],
                requirement_ids=list(question.requirement_ids),
                origin=question.id,
            )
        )
    return draft.model_copy(update={"statements": statements}, deep=True)


def draft_from_text(draft: AnyDraft, raw: dict[str, str | None]) -> AnyDraft:
    """Copy of `draft` with fields replaced by form text (provenance unchanged).

    List fields take one item per line; an empty choice clears an optional field.
    Pass the result to the workflow's update_draft, which records provenance.
    """
    updates: dict[str, Any] = {}
    for field, text in raw.items():
        if field not in editable_fields(draft):
            raise DraftError("invalid_field")
        check_length(text or "")
        if is_list_field(draft, field):
            updates[field] = split_lines(text or "")
        elif type(draft).model_fields[field].default is None:
            updates[field] = text or None
        else:
            updates[field] = (text or "").strip()
    return _with(draft, updates)


def merge_edit(old: AnyDraft, new: AnyDraft) -> AnyDraft:
    """Accept a direct edit by the user and update provenance of changed fields.

    Changed values become USER_CONFIRMED; cleared values lose their provenance.
    Source requirements must stay exactly as they were.
    """
    if type(old) is not type(new):
        raise DraftError("draft_type_mismatch")
    if isinstance(old, RequirementsDraft) and isinstance(new, RequirementsDraft):
        if old.requirements != new.requirements:
            raise DraftError("source_changed")
    provenance = dict(old.provenance)
    for field in editable_fields(old):
        if getattr(old, field) == getattr(new, field):
            continue
        if field_is_empty(new, field):
            provenance.pop(field, None)
        else:
            provenance[field] = Provenance.USER_CONFIRMED
    return new.model_copy(update={"provenance": provenance}, deep=True)
