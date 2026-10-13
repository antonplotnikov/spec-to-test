"""Projects: named sets of requirement documents, e.g. one per product or application.

Each document added to a project gets its own workspace (requirements, findings,
test cases, bug reports…), so the same text in two projects is two independent
pieces of work. Where projects live follows the storage mode (see storage.py):
- "local":   on disk, through `DiskProjectStore`;
- "session": only in this browser session, through `SessionProjectStore`, which
  never touches the disk.

There is always at least one project: when none was created yet, the default
project (id "default", no name) is offered.
"""

import re
import secrets
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any, Protocol

from spec_to_test import storage
from spec_to_test.models import DocumentSummary, Project, Workspace

DEFAULT_PROJECT_ID = storage.DEFAULT_PROJECT_ID
MAX_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 500
MAX_TITLE_LENGTH = 60


class ProjectError(ValueError):
    """A project could not be created or changed; `code` is a translation key suffix."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProjectStore(Protocol):
    def projects(self) -> list[Project]: ...
    def save_project(self, project: Project) -> None: ...
    def delete_project(self, project_id: str) -> None: ...
    def documents(self, project_id: str) -> list[DocumentSummary]: ...
    def load(self, project_id: str, doc_hash: str) -> Workspace | None: ...
    def save(self, project_id: str, workspace: Workspace) -> None: ...
    def delete_document(self, project_id: str, doc_hash: str) -> None: ...
    def last_opened(self) -> tuple[str, str] | None: ...
    def set_last_opened(self, project_id: str, doc_hash: str) -> None: ...


def _check_hash(doc_hash: str) -> str:
    if not (doc_hash.isascii() and doc_hash.isalnum()):
        raise ValueError("invalid document hash")
    return doc_hash


def summary_of(workspace: Workspace) -> DocumentSummary:
    return DocumentSummary(
        document_hash=workspace.document_hash,
        title=workspace.title,
        created_at=workspace.created_at,
        requirements=len(workspace.requirements),
        first_requirement=workspace.requirements[0].text if workspace.requirements else "",
    )


class SessionProjectStore:
    """Projects kept in one browser session (Streamlit session state) only."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._workspaces: dict[str, dict[str, Workspace]] = {}

    def projects(self) -> list[Project]:
        return list(self._projects.values()) or [Project(id=DEFAULT_PROJECT_ID)]

    def save_project(self, project: Project) -> None:
        self._projects[project.id] = project.model_copy()

    def delete_project(self, project_id: str) -> None:
        self._projects.pop(project_id, None)
        self._workspaces.pop(project_id, None)

    def documents(self, project_id: str) -> list[DocumentSummary]:
        workspaces = self._workspaces.get(project_id, {}).values()
        return sorted(map(summary_of, workspaces), key=lambda d: d.created_at)

    def load(self, project_id: str, doc_hash: str) -> Workspace | None:
        workspace = self._workspaces.get(project_id, {}).get(doc_hash)
        # Copies, like the disk: an unsaved edit never leaks into the stored document.
        return workspace.model_copy(deep=True) if workspace is not None else None

    def save(self, project_id: str, workspace: Workspace) -> None:
        _check_hash(workspace.document_hash)
        if project_id not in self._projects:  # first document of the default project
            self._projects[project_id] = Project(id=project_id)
        self._workspaces.setdefault(project_id, {})[workspace.document_hash] = workspace.model_copy(deep=True)

    def delete_document(self, project_id: str, doc_hash: str) -> None:
        self._workspaces.get(project_id, {}).pop(doc_hash, None)

    def last_opened(self) -> tuple[str, str] | None:
        return None  # a new browser session starts empty

    def set_last_opened(self, project_id: str, doc_hash: str) -> None:
        pass


class DiskProjectStore:
    """Projects in the local data folder (SPEC_TO_TEST_STORAGE=local)."""

    def projects(self) -> list[Project]:
        return storage.list_projects() or [Project(id=DEFAULT_PROJECT_ID)]

    def save_project(self, project: Project) -> None:
        storage.save_project(project)

    def delete_project(self, project_id: str) -> None:
        storage.delete_project(project_id)

    def documents(self, project_id: str) -> list[DocumentSummary]:
        return storage.list_documents(project_id)

    def load(self, project_id: str, doc_hash: str) -> Workspace | None:
        return storage.load_workspace(doc_hash, project_id)

    def save(self, project_id: str, workspace: Workspace) -> None:
        storage.save_workspace(workspace, project_id)

    def delete_document(self, project_id: str, doc_hash: str) -> None:
        storage.delete_workspace(doc_hash, project_id)

    def last_opened(self) -> tuple[str, str] | None:
        return storage.load_pointer()

    def set_last_opened(self, project_id: str, doc_hash: str) -> None:
        storage.save_pointer(project_id, doc_hash)


def open_store(session_state: MutableMapping[Any, Any]) -> ProjectStore:
    """The store for the current storage mode; the session one lives in `session_state`."""
    if storage.persistence_enabled():
        return DiskProjectStore()
    store = session_state.get("project_store")
    if not isinstance(store, SessionProjectStore):
        store = session_state["project_store"] = SessionProjectStore()
    return store


# --- Helpers -------------------------------------------------------------------------

def now() -> str:
    return datetime.now(UTC).isoformat()


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def check_name(name: str, projects: list[Project], project_id: str = "") -> str:
    """Return the cleaned name, or raise ProjectError if it is empty, too long or taken."""
    cleaned = clean_name(name)
    if not cleaned:
        raise ProjectError("name_required")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ProjectError("name_too_long")
    if any(p.id != project_id and p.name.casefold() == cleaned.casefold() for p in projects):
        raise ProjectError("name_taken")
    return cleaned


def check_description(description: str) -> str:
    cleaned = description.strip()
    if len(cleaned) > MAX_DESCRIPTION_LENGTH:
        raise ProjectError("description_too_long")
    return cleaned


def new_project(name: str, description: str, projects: list[Project]) -> Project:
    return Project(
        id=secrets.token_hex(6),
        name=check_name(name, projects),
        description=check_description(description),
        created_at=now(),
    )


def document_title(text: str, file_name: str | None = None) -> str:
    """A short name for a document: its file name, or else its first non-empty line."""
    title = (file_name or "").strip()
    if not title:
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        title = clean_name(first.lstrip("#").strip())
    if len(title) > MAX_TITLE_LENGTH:
        title = title[: MAX_TITLE_LENGTH - 1].rstrip() + "…"
    return title
