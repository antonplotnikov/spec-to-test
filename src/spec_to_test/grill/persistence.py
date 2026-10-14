"""Save and restore Grill interviews, so unfinished work survives reloads and new sessions.

A saved interview is the whole `GrillSession` (answers, question history,
draft, findings, audit log) plus what the page keeps beside it (lines of a
pasted draft that could not be read, AI test ideas for the report). Progress
and unresolved questions are derived from the session, so they come back
exactly as they were.

Where interviews live follows the storage mode (see storage.py), like projects:
- "local":   one JSON file per interview in the project's `grill/` folder,
             written after every change, plus a pointer to the last active one
             that is reopened after a page reload;
- "session": in this browser session only (nothing on disk). A reload starts a
             new browser session, so the page offers "Save progress to a file"
             and "Resume from a file" instead.

Loading never trusts a file: it is size-limited, validated against the models,
and older session schemas are migrated (grill.models.migrate_session_data).
"""

import json
from collections.abc import MutableMapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from spec_to_test import storage
from spec_to_test.grill.models import (
    BugReportDraft,
    GrillKind,
    GrillSession,
    RequirementsDraft,
    TestCaseDraft,
    load_session,
    utc_now,
)
from spec_to_test.grill.report import SuggestedTestCase

FORMAT: Literal["spec-to-test/grill-interview"] = "spec-to-test/grill-interview"
FORMAT_VERSION = 1
MAX_IMPORT_BYTES = storage.MAX_INTERVIEW_BYTES
_TITLE_CHARS = 70


class PersistenceError(Exception):
    """A saved interview cannot be used; `code` maps to grill.error.<code>."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SavedInterview(BaseModel):
    format: Literal["spec-to-test/grill-interview"] = FORMAT
    format_version: int = FORMAT_VERSION
    project_id: str = storage.DEFAULT_PROJECT_ID
    # The analyzed document the interview was started on ("" = none or pasted text).
    document_hash: str = ""
    saved_at: str = ""
    session: GrillSession
    unparsed: list[str] = Field(default_factory=list)
    ai_test_ideas: list[SuggestedTestCase] = Field(default_factory=list)


class InterviewSummary(BaseModel):
    """What the list of saved interviews shows."""

    session_id: str
    kind: GrillKind
    step: str
    title: str = ""
    answered: int = 0
    total: int = 0
    unresolved: int = 0
    created_at: str = ""
    updated_at: str = ""
    document_hash: str = ""
    finished: bool = False


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _TITLE_CHARS else text[: _TITLE_CHARS - 1].rstrip() + "…"


def interview_title(session: GrillSession) -> str:
    """A short, language-neutral name taken from the interview's own content."""
    draft = session.draft
    if isinstance(draft, RequirementsDraft):
        ids = [r.id for r in draft.requirements]
        return _short(", ".join(ids[:4]) + (f" (+{len(ids) - 4})" if len(ids) > 4 else ""))
    if isinstance(draft, TestCaseDraft):
        return _short(draft.title or draft.feature or draft.requirement_id)
    if isinstance(draft, BugReportDraft):
        return _short(draft.summary or draft.requirement_id)
    return ""


def summarize(record: SavedInterview) -> InterviewSummary:
    session = record.session
    done, total = session.progress
    return InterviewSummary(
        session_id=session.id,
        kind=session.kind,
        step=session.step.value,
        title=interview_title(session),
        answered=done,
        total=total,
        unresolved=len(session.unresolved_questions),
        created_at=session.created_at,
        updated_at=session.updated_at or record.saved_at,
        document_hash=record.document_hash,
        finished=session.is_terminal,
    )


def from_data(data: Any) -> SavedInterview:
    """Validate a saved interview (any supported schema). Raises PersistenceError."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise PersistenceError("interview_invalid")
    if data.get("format_version") != FORMAT_VERSION:
        raise PersistenceError("interview_version")
    session = load_session(data.get("session"))
    # The ID names the file on disk: letters and digits only (as generated), nothing else.
    if session is None or not (session.id.isascii() and session.id.isalnum() and len(session.id) <= 64):
        raise PersistenceError("interview_invalid")
    try:
        return SavedInterview.model_validate({**data, "session": session.model_dump(mode="json")})
    except ValidationError:
        raise PersistenceError("interview_invalid") from None


def to_data(record: SavedInterview) -> dict[str, Any]:
    return record.model_dump(mode="json")


def export_json(record: SavedInterview) -> str:
    """The interview as a file the user can keep and load later (also in "session" mode)."""
    return json.dumps(to_data(record), ensure_ascii=False, indent=1)


def import_json(raw: bytes | str, project_id: str) -> SavedInterview:
    """Read an exported interview into `project_id`. Raises PersistenceError."""
    if len(raw) > MAX_IMPORT_BYTES:
        raise PersistenceError("interview_too_large")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise PersistenceError("interview_invalid") from None
    record = from_data(data)
    # The file may come from another project or machine: keep it in the one it is loaded into.
    return record.model_copy(update={"project_id": project_id})


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

class InterviewStore(Protocol):
    def interviews(self, project_id: str) -> list[InterviewSummary]: ...
    def load(self, project_id: str, session_id: str) -> SavedInterview | None: ...
    def save(self, record: SavedInterview) -> None: ...
    def delete(self, project_id: str, session_id: str) -> None: ...
    def last_active(self, project_id: str) -> str: ...
    def set_last_active(self, project_id: str, session_id: str) -> None: ...


def _sorted(summaries: list[InterviewSummary]) -> list[InterviewSummary]:
    """Unfinished first, then the most recently changed."""
    by_time = sorted(summaries, key=lambda s: s.updated_at or s.created_at, reverse=True)
    return sorted(by_time, key=lambda s: s.finished)


class SessionInterviewStore:
    """Interviews kept in this browser session only."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, dict[str, Any]]] = {}
        self._active: dict[str, str] = {}

    def interviews(self, project_id: str) -> list[InterviewSummary]:
        records = (self.load(project_id, sid) for sid in list(self._records.get(project_id, {})))
        return _sorted([summarize(r) for r in records if r is not None])

    def load(self, project_id: str, session_id: str) -> SavedInterview | None:
        data = self._records.get(project_id, {}).get(session_id)
        try:
            return from_data(data) if data is not None else None
        except PersistenceError:
            return None

    def save(self, record: SavedInterview) -> None:
        stamped = record.model_copy(update={"saved_at": utc_now()})
        self._records.setdefault(record.project_id, {})[record.session.id] = to_data(stamped)

    def delete(self, project_id: str, session_id: str) -> None:
        self._records.get(project_id, {}).pop(session_id, None)
        if self._active.get(project_id) == session_id:
            self._active[project_id] = ""

    def last_active(self, project_id: str) -> str:
        return self._active.get(project_id, "")

    def set_last_active(self, project_id: str, session_id: str) -> None:
        self._active[project_id] = session_id


class DiskInterviewStore:
    """Interviews in the local data folder (SPEC_TO_TEST_STORAGE=local)."""

    def interviews(self, project_id: str) -> list[InterviewSummary]:
        found = []
        for data in storage.list_interview_data(project_id):
            try:
                found.append(summarize(from_data(data)))
            except PersistenceError:
                continue  # unreadable or from a newer app version: left on disk, not shown
        return _sorted(found)

    def load(self, project_id: str, session_id: str) -> SavedInterview | None:
        data = storage.load_interview_data(project_id, session_id)
        try:
            return from_data(data) if data is not None else None
        except PersistenceError:
            return None

    def save(self, record: SavedInterview) -> None:
        stamped = record.model_copy(update={"saved_at": utc_now()})
        storage.save_interview_data(record.project_id, record.session.id, to_data(stamped))

    def delete(self, project_id: str, session_id: str) -> None:
        storage.delete_interview(project_id, session_id)
        if storage.load_interview_pointer(project_id) == session_id:
            storage.save_interview_pointer(project_id, "")

    def last_active(self, project_id: str) -> str:
        return storage.load_interview_pointer(project_id)

    def set_last_active(self, project_id: str, session_id: str) -> None:
        storage.save_interview_pointer(project_id, session_id)


def open_interview_store(session_state: MutableMapping[Any, Any]) -> InterviewStore:
    """The store for the current storage mode; the session one lives in `session_state`."""
    if storage.persistence_enabled():
        return DiskInterviewStore()
    store = session_state.get("grill_interview_store")
    if not isinstance(store, SessionInterviewStore):
        store = session_state["grill_interview_store"] = SessionInterviewStore()
    return store
