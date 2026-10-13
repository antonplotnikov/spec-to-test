"""Optionally persist the user's projects and workspaces (test cases, reviews, bug reports) on disk.

Storage modes (SPEC_TO_TEST_STORAGE):
- "session": the default everywhere. Work lives only in the browser session
  (Streamlit session state); nothing is read from or written to disk, so
  visitors of a shared deployment can never see each other's documents.
- "local":   opt-in, single-user machines only. Each analyzed document is
  stored as JSON in its project's folder, keyed by a hash of its text, so
  re-analyzing the same document in the same project restores earlier edits.
  Enabled only by the exact value "local" (case and surrounding spaces
  ignored); any other or empty value means "session". Set
  SPEC_TO_TEST_DATA_DIR to change the folder.

Layout of the data folder:
    latest.json                         last opened project and document
    workspaces/<hash>.json              documents of the default project
    projects/default/project.json       its name and description, once edited
    projects/<id>/project.json          any other project
    projects/<id>/workspaces/<hash>.json

The default project keeps the location used before projects existed, so work
saved by older versions opens unchanged.

The mode is read from the process environment (or Streamlit secrets, which
become environment variables) only. A .env file never switches it.
"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from pydantic import ValidationError

from spec_to_test.models import DocumentSummary, Project, Workspace

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / ".spec_to_test_data"
LATEST_FILE = "latest.json"
PROJECT_FILE = "project.json"
DEFAULT_PROJECT_ID = "default"


def storage_mode() -> str:
    """Return "session" unless SPEC_TO_TEST_STORAGE is explicitly "local"."""
    mode = os.environ.get("SPEC_TO_TEST_STORAGE", "").strip().lower()
    return "local" if mode == "local" else "session"


def persistence_enabled() -> bool:
    return storage_mode() == "local"


def data_dir() -> Path:
    return Path(os.environ.get("SPEC_TO_TEST_DATA_DIR") or DEFAULT_DATA_DIR)


def document_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _file_name(value: str, what: str) -> str:
    """Project ids and document hashes become file names; refuse anything else."""
    if not (value.isascii() and value.isalnum()):
        raise ValueError(f"invalid {what}")
    return value


def _project_dir(project_id: str) -> Path:
    return data_dir() / "projects" / _file_name(project_id, "project id")


def _workspaces_dir(project_id: str) -> Path:
    if _file_name(project_id, "project id") == DEFAULT_PROJECT_ID:
        return data_dir() / "workspaces"
    return _project_dir(project_id) / "workspaces"


def _workspace_path(doc_hash: str, project_id: str = DEFAULT_PROJECT_ID) -> Path:
    return _workspaces_dir(project_id) / f"{_file_name(doc_hash, 'document hash')}.json"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --- Workspaces (one per document) ---------------------------------------------------

def save_workspace(workspace: Workspace, project_id: str = DEFAULT_PROJECT_ID) -> None:
    """Write the workspace to disk; does nothing in "session" mode."""
    if not persistence_enabled():
        return
    _write_atomic(_workspace_path(workspace.document_hash, project_id), workspace.model_dump_json(indent=2))
    save_pointer(project_id, workspace.document_hash)


def load_workspace(doc_hash: str, project_id: str = DEFAULT_PROJECT_ID) -> Workspace | None:
    """Return the saved workspace, or None if missing, unreadable or disabled."""
    if not persistence_enabled():
        return None
    try:
        path = _workspace_path(doc_hash, project_id)
        return Workspace.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


def delete_workspace(doc_hash: str, project_id: str = DEFAULT_PROJECT_ID) -> None:
    if not persistence_enabled():
        return
    _workspace_path(doc_hash, project_id).unlink(missing_ok=True)


def list_documents(project_id: str) -> list[DocumentSummary]:
    """The project's documents, oldest first; unreadable files are skipped."""
    if not persistence_enabled():
        return []
    try:
        paths = sorted(_workspaces_dir(project_id).glob("*.json"))
    except (OSError, ValueError):
        return []
    documents = []
    for path in paths:
        if path.name.startswith(".") or not path.stem.isalnum():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            requirements = raw.get("requirements") or []
            documents.append(
                DocumentSummary(
                    document_hash=path.stem,
                    title=str(raw.get("title") or ""),
                    created_at=str(raw.get("created_at") or ""),
                    requirements=len(requirements),
                    first_requirement=str(requirements[0].get("text") or "") if requirements else "",
                )
            )
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return sorted(documents, key=lambda d: d.created_at)


# --- Projects --------------------------------------------------------------------------

def save_project(project: Project) -> None:
    if not persistence_enabled():
        return
    _write_atomic(_project_dir(project.id) / PROJECT_FILE, project.model_dump_json(indent=2))


def load_project(project_id: str) -> Project | None:
    if not persistence_enabled():
        return None
    try:
        project = Project.model_validate_json((_project_dir(project_id) / PROJECT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        # The default project exists implicitly as soon as it holds a document.
        if project_id == DEFAULT_PROJECT_ID and list_documents(DEFAULT_PROJECT_ID):
            return Project(id=DEFAULT_PROJECT_ID)
        return None
    return project if project.id == project_id else None


def list_projects() -> list[Project]:
    """All saved projects, oldest first (the default project, if any, comes first)."""
    if not persistence_enabled():
        return []
    root = data_dir() / "projects"
    ids = {DEFAULT_PROJECT_ID}
    if root.is_dir():
        ids |= {p.name for p in root.iterdir() if p.is_dir() and p.name.isascii() and p.name.isalnum()}
    projects = [p for p in map(load_project, ids) if p is not None]
    return sorted(projects, key=lambda p: (p.id != DEFAULT_PROJECT_ID, p.created_at, p.name))


def delete_project(project_id: str) -> None:
    """Remove the project with all its documents."""
    if not persistence_enabled():
        return
    if project_id == DEFAULT_PROJECT_ID:
        for path in _workspaces_dir(DEFAULT_PROJECT_ID).glob("*.json"):
            path.unlink(missing_ok=True)
    shutil.rmtree(_project_dir(project_id), ignore_errors=True)


# --- Last opened project and document ---------------------------------------------------

def save_pointer(project_id: str, doc_hash: str = "") -> None:
    if not persistence_enabled():
        return
    _file_name(project_id, "project id")
    _write_atomic(data_dir() / LATEST_FILE, json.dumps({"project_id": project_id, "document_hash": doc_hash}))


def load_pointer() -> tuple[str, str] | None:
    """(project id, document hash or ""); files from older versions name only the document."""
    if not persistence_enabled():
        return None
    try:
        pointer = json.loads((data_dir() / LATEST_FILE).read_text(encoding="utf-8"))
        project_id = str(pointer.get("project_id") or DEFAULT_PROJECT_ID)
        return _file_name(project_id, "project id"), str(pointer.get("document_hash") or "")
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def load_latest() -> Workspace | None:
    if (pointer := load_pointer()) is None or not pointer[1]:
        return None
    return load_workspace(pointer[1], pointer[0])
