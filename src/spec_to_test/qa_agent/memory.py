"""QA Agent memory: project rules the user confirmed and the user's explicit feedback on task results.

Only what the user states is kept:
- rule:     a project rule the user wrote and confirmed ("REQ-4 limits apply to
            admins only", "Smoke must cover checkout");
- feedback: the user's rating (useful / not useful) of one task result, with an
            optional comment and the task it was given for.
The agent's own answers are never stored, so nothing it concluded becomes a
"fact" later. Every entry is tied to one project and to the tools it is about.

Memory does not change what the tools compute. With a task result the page shows
the entries relevant to it: same tool, and, when the entry names requirement or
test case IDs, only if the task looks at those IDs (or the whole document).
Matching is by tool and ID only: no embeddings, no model training.

Where memory lives follows the storage mode (see storage.py), like projects:
"local" keeps one JSON file per project, "session" keeps it in this browser
session. Loading never trusts the file: it is size-limited and every entry is
validated; unreadable entries are skipped.
"""

import secrets
import threading
from collections.abc import Callable, MutableMapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from spec_to_test import storage
from spec_to_test.filelock import locked
from spec_to_test.qa_agent.tasks import _ID, MAX_TASK_LENGTH, TOOLS, AgentPlan, AgentResult, Tool

FORMAT: Literal["spec-to-test/qa-memory"] = "spec-to-test/qa-memory"
FORMAT_VERSION = 1
MAX_ENTRIES = 200
MAX_TEXT_LENGTH = 500
# At most this many entries are shown with one result.
MAX_RELEVANT = 5

Kind = Literal["rule", "feedback"]
Rating = Literal["useful", "not_useful"]


class MemoryEntryError(ValueError):
    """An entry cannot be saved; `code` maps to qamemory.error.<code>."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


class MemoryEntry(BaseModel):
    # Fields this version does not know are kept on save: a file written by a newer version is not trimmed.
    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: secrets.token_hex(6), pattern=r"^[0-9a-f]{12}$")
    kind: Kind
    # The rule itself, or the comment of a feedback entry.
    text: str = Field(default="", max_length=MAX_TEXT_LENGTH)
    # The tools the entry is about; it is shown only with results of these tools.
    tools: list[Tool] = Field(min_length=1)
    rating: Rating | None = None  # feedback only
    task: str = Field(default="", max_length=MAX_TASK_LENGTH)  # feedback only
    created_at: str = ""
    updated_at: str = ""

    @model_validator(mode="after")
    def _check(self) -> "MemoryEntry":
        if self.kind == "rule" and (not self.text.strip() or self.rating is not None):
            raise ValueError("a rule needs text and no rating")
        if self.kind == "feedback" and self.rating is None:
            raise ValueError("feedback needs a rating")
        return self

    @property
    def ids(self) -> set[str]:
        """Requirement and test case IDs the entry names (matched case-insensitively)."""
        tokens = _ID.findall(f"{self.text}\n{self.task}")
        return {token.lower() for token in tokens if token.split("-")[0].isupper()}  # "REQ-4", not "mp3"


# --- Creating and editing entries -----------------------------------------------------

def _clean_tools(tools: list[str]) -> list[Tool]:
    chosen = [tool for tool in TOOLS if tool in tools]
    if not chosen:
        raise MemoryEntryError("no_tools")
    return chosen


def _clean_text(text: str, required: bool) -> str:
    cleaned = " ".join(text.split())
    if required and not cleaned:
        raise MemoryEntryError("text_required")
    if len(cleaned) > MAX_TEXT_LENGTH:
        raise MemoryEntryError("text_too_long")
    return cleaned


def new_rule(text: str, tools: list[str], confirmed: bool) -> MemoryEntry:
    """A project rule; only saved when the user confirmed it holds for this project."""
    if not confirmed:
        raise MemoryEntryError("not_confirmed")
    stamp = _now()
    return MemoryEntry(kind="rule", text=_clean_text(text, required=True), tools=_clean_tools(tools),
                       created_at=stamp, updated_at=stamp)


def new_feedback(result: AgentResult, rating: Rating, comment: str = "") -> MemoryEntry:
    """The user's rating of a result: the task, the tools that ran and the comment. Not the result itself."""
    tools = [step.tool for step in result.steps if step.status == "ok"]
    if not tools:
        raise MemoryEntryError("nothing_to_rate")
    stamp = _now()
    return MemoryEntry(kind="feedback", rating=rating, text=_clean_text(comment, required=False),
                       tools=_clean_tools(list(tools)), task=result.task, created_at=stamp, updated_at=stamp)


def edited(entry: MemoryEntry, text: str, tools: list[str], rating: Rating | None = None) -> MemoryEntry:
    """A corrected copy of `entry` (text, tools and, for feedback, the rating)."""
    update: dict[str, Any] = {
        "text": _clean_text(text, required=entry.kind == "rule"),
        "tools": _clean_tools(tools),
        "updated_at": _now(),
    }
    if entry.kind == "feedback" and rating is not None:
        update["rating"] = rating
    return MemoryEntry.model_validate({**entry.model_dump(), **update})


# --- Relevance ------------------------------------------------------------------------

def relevant(entries: list[MemoryEntry], plan: AgentPlan | None, limit: int = MAX_RELEVANT) -> list[MemoryEntry]:
    """Entries about the tools that ran and, if they name IDs, about the IDs the task looked at.

    Rules come before feedback, newest first within each kind.
    """
    if plan is None or not plan.tools:
        return []
    scope = {i.lower() for i in plan.test_case_ids + plan.requirement_ids}
    matching = [
        e for e in entries
        if set(e.tools) & set(plan.tools) and (not scope or not e.ids or e.ids & scope)
    ]
    matching.sort(key=lambda e: e.updated_at or e.created_at, reverse=True)
    matching.sort(key=lambda e: e.kind != "rule")
    return matching[:limit]


# --- Stores ---------------------------------------------------------------------------

def _to_data(entries: list[MemoryEntry], kept: list[Any]) -> dict[str, Any]:
    return {"format": FORMAT, "format_version": FORMAT_VERSION,
            "entries": [e.model_dump(mode="json") for e in entries] + kept}


def _parse(data: Any) -> tuple[list[MemoryEntry], list[Any]]:
    """The readable entries, and the ones that could not be read (kept as they are on write).
    A file of another format is refused: writing over it would destroy it."""
    if data is None:
        return [], []
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("format_version") != FORMAT_VERSION:
        raise MemoryEntryError("unreadable")
    raw = data.get("entries")
    found: list[MemoryEntry] = []
    kept: list[Any] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            found.append(MemoryEntry.model_validate(item))
        except ValidationError:
            kept.append(item)  # unreadable entry: never guessed, and never dropped by a write
    return found[:MAX_ENTRIES], kept


class MemoryStore(Protocol):
    def entries(self, project_id: str) -> list[MemoryEntry]: ...
    def add(self, project_id: str, entry: MemoryEntry) -> None: ...
    def update(self, project_id: str, entry: MemoryEntry) -> None: ...
    def delete(self, project_id: str, entry_id: str) -> None: ...
    def delete_project(self, project_id: str) -> None: ...


class _Store:
    """Transactions over a project's whole memory; `_read`, `_write` and `_lock` differ by mode.

    Each change re-reads the saved memory under the file's lock, so an entry added in another tab is
    kept, and a damaged or foreign file is never overwritten.
    """

    def _read(self, project_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def _lock(self, project_id: str) -> Any:
        raise NotImplementedError

    def _unreadable(self, project_id: str) -> bool:
        return False

    def _transaction(self, project_id: str, change: Callable[[list[MemoryEntry]], list[MemoryEntry]]) -> None:
        with self._lock(project_id):
            if self._unreadable(project_id):
                raise MemoryEntryError("unreadable")
            entries, kept = _parse(self._read(project_id))
            updated = change(entries)
            if len(updated) > MAX_ENTRIES:
                raise MemoryEntryError("full")
            self._write(project_id, _to_data(updated, kept))

    def entries(self, project_id: str) -> list[MemoryEntry]:
        try:
            return _parse(self._read(project_id))[0]
        except MemoryEntryError:
            return []  # shown as empty; reading never writes

    def add(self, project_id: str, entry: MemoryEntry) -> None:
        self._transaction(project_id, lambda current: [*current, entry])

    def update(self, project_id: str, entry: MemoryEntry) -> None:
        def change(current: list[MemoryEntry]) -> list[MemoryEntry]:
            saved = next((e for e in current if e.id == entry.id), None)
            if saved is None:
                raise MemoryEntryError("missing")
            # Fields a newer version added to the saved entry are carried over.
            merged = MemoryEntry.model_validate({**(saved.model_extra or {}), **entry.model_dump()})
            return [merged if e.id == entry.id else e for e in current]
        self._transaction(project_id, change)

    def delete(self, project_id: str, entry_id: str) -> None:
        self._transaction(project_id, lambda current: [e for e in current if e.id != entry_id])


class SessionMemoryStore(_Store):
    """Memory kept in this browser session only."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._mutex = threading.Lock()

    def _read(self, project_id: str) -> dict[str, Any] | None:
        return self._data.get(project_id)

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        self._data[project_id] = data

    def _lock(self, project_id: str) -> Any:
        return self._mutex

    def delete_project(self, project_id: str) -> None:
        self._data.pop(project_id, None)


class DiskMemoryStore(_Store):
    """Memory in the project's folder (SPEC_TO_TEST_STORAGE=local), under the file's lock."""

    def _read(self, project_id: str) -> dict[str, Any] | None:
        return storage.load_memory_data(project_id)

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        storage.save_memory_data(project_id, data)

    def _lock(self, project_id: str) -> Any:
        return locked(storage.memory_path(project_id))

    def _unreadable(self, project_id: str) -> bool:
        return storage.load_memory_data(project_id) is None and storage.memory_path(project_id).exists()

    def delete_project(self, project_id: str) -> None:
        storage.delete_memory_data(project_id)


def open_memory_store(session_state: MutableMapping[Any, Any]) -> MemoryStore:
    """The store for the current storage mode; the session one lives in `session_state`."""
    if storage.persistence_enabled():
        return DiskMemoryStore()
    store = session_state.get("qa_memory_store")
    if not isinstance(store, SessionMemoryStore):
        store = session_state["qa_memory_store"] = SessionMemoryStore()
    return store
