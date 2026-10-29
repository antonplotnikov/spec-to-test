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
    grill/<session id>.json             Grill interviews of the default project
    grill/latest.json                   its last active interview
    projects/default/project.json       its name and description, once edited
    projects/<id>/project.json          any other project
    projects/<id>/workspaces/<hash>.json
    projects/<id>/grill/<session id>.json
    projects/<id>/grill/latest.json
    qa_memory.json                      QA Agent memory of the default project
    projects/<id>/qa_memory.json        QA Agent memory of any other project
    bug_reports.json                    Bug Reports (product bugs) of the default project
    projects/<id>/bug_reports.json      Bug Reports of any other project
    test_runs.json                      Manual test runs and their results of the default project
    projects/<id>/test_runs.json        Test runs of any other project
    conflicts/<hash>.unsaved-<digest>.json  an edit that could not be saved (document changed elsewhere)
    conflicts/<hash>-replaced-*.json    a saved copy replaced by "my version" (kept, never deleted by the app)
    projects/<id>/conflicts/...         the same for any other project

Workspaces carry a `schema_version`; older files are upgraded on load by
spec_to_test.migrations (the file itself is rewritten on the next save).

A new copy never replaces a saved file: when one already exists the save raises
WorkspaceConflict, and the app asks the user which version to keep.

The default project keeps the location used before projects existed, so work
saved by older versions opens unchanged.

The mode is read from the process environment (or Streamlit secrets, which
become environment variables) only. A .env file never switches it.
"""

import hashlib
import json
import os
import secrets
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from spec_to_test.filelock import locked
from spec_to_test.migrations import migrate_workspace_data
from spec_to_test.models import DocumentSummary, Project, Workspace

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / ".spec_to_test_data"
LATEST_FILE = "latest.json"
PROJECT_FILE = "project.json"
DEFAULT_PROJECT_ID = "default"
GRILL_DIR = "grill"
MEMORY_FILE = "qa_memory.json"
BUG_REPORTS_FILE = "bug_reports.json"
RUNS_FILE = "test_runs.json"
IMPACT_DECISIONS_FILE = "impact_decisions.json"
# Copies the app could not save because the document changed elsewhere (see keep_unsaved_copy).
CONFLICTS_DIR = "conflicts"
UNSAVED_MARK = ".unsaved-"
# Saved interviews larger than this are not read (a normal one is a few hundred KB at most).
MAX_INTERVIEW_BYTES = 5_000_000
# A test runs file holds up to 100 runs of up to 2000 results each.
MAX_RUNS_BYTES = 50_000_000


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


def _conflicts_dir(project_id: str) -> Path:
    if _file_name(project_id, "project id") == DEFAULT_PROJECT_ID:
        return data_dir() / CONFLICTS_DIR
    return _project_dir(project_id) / CONFLICTS_DIR


def _stamp() -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}-{secrets.token_hex(2)}"


# --- Workspaces (one per document) ---------------------------------------------------

class WorkspaceConflict(ValueError):
    """The saved file changed after this copy was read (another tab, or the QA on-change run),
    or a new copy would replace a saved file that already exists."""


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def save_workspace(workspace: Workspace, project_id: str = DEFAULT_PROJECT_ID, remember: bool = True) -> None:
    """Write the workspace to disk; does nothing in "session" mode.

    `remember` also makes it the last opened document; writes from outside the app pass False.
    The check and the write happen under the document's lock (see spec_to_test.filelock), so two
    writers cannot both pass the check and the second write cannot replace the first silently.
    Raises WorkspaceConflict when the copy was read from or saved to a file that has changed since,
    or when the copy is new and a saved file for the document already exists.
    """
    if not persistence_enabled():
        return
    path = _workspace_path(workspace.document_hash, project_id)
    content = workspace.model_dump_json(indent=2)
    with locked(path):
        if workspace._stored_digest is None:
            if path.exists():
                raise WorkspaceConflict(f"{workspace.document_hash} already saved")
        else:
            try:
                current = _digest(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                current = workspace._stored_digest  # deleted meanwhile: saving restores it, as before
            if current != workspace._stored_digest:
                raise WorkspaceConflict(f"{workspace.document_hash} changed on disk")
        _write_atomic(path, content)
    workspace._stored_digest = _digest(content)
    if remember:
        save_pointer(project_id, workspace.document_hash)


def keep_unsaved_copy(workspace: Workspace, project_id: str = DEFAULT_PROJECT_ID) -> Path | None:
    """Keep the copy the app could not save, so no edit is lost. Returns its path.

    The file name holds the digest of the content (`conflicts/<hash>.unsaved-<digest>.json`), so a
    different edit never replaces an earlier copy, and the same edit is written once. The saved
    document itself is not touched. Does nothing in "session" mode.
    """
    if not persistence_enabled():
        return None
    content = workspace.model_dump_json(indent=2)
    name = f"{_file_name(workspace.document_hash, 'document hash')}{UNSAVED_MARK}{_digest(content)[:16]}.json"
    path = _conflicts_dir(project_id) / name
    if not path.exists():  # same name, same content
        _write_atomic(path, content)
    return path


def overwrite_workspace(workspace: Workspace, project_id: str = DEFAULT_PROJECT_ID) -> Path | None:
    """Save `workspace` over the file that changed elsewhere, because the user chose "my version".

    The file it replaces is copied to the conflicts folder first, under the same lock as the write,
    so nothing saved in between is lost. Returns that copy's path, or None when there was no file to
    replace. Does nothing in "session" mode.
    """
    if not persistence_enabled():
        return None
    path = _workspace_path(workspace.document_hash, project_id)
    content = workspace.model_dump_json(indent=2)
    with locked(path):
        replaced = None
        if path.exists():
            replaced = _conflicts_dir(project_id) / f"{workspace.document_hash}-replaced-{_stamp()}.json"
            replaced.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, replaced)
        _write_atomic(path, content)
    workspace._stored_digest = _digest(content)
    save_pointer(project_id, workspace.document_hash)
    return replaced


def load_workspace(doc_hash: str, project_id: str = DEFAULT_PROJECT_ID) -> Workspace | None:
    """Return the saved workspace, or None if missing, unreadable or disabled."""
    if not persistence_enabled():
        return None
    try:
        path = _workspace_path(doc_hash, project_id)
        content = path.read_text(encoding="utf-8")
        workspace = Workspace.model_validate(migrate_workspace_data(json.loads(content)))
    except (OSError, ValueError, ValidationError):
        return None
    workspace._stored_digest = _digest(content)
    return workspace


def delete_workspace(doc_hash: str, project_id: str = DEFAULT_PROJECT_ID) -> None:
    if not persistence_enabled():
        return
    path = _workspace_path(doc_hash, project_id)
    with locked(path):
        path.unlink(missing_ok=True)


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
        shutil.rmtree(_grill_dir(DEFAULT_PROJECT_ID), ignore_errors=True)
        memory_path(DEFAULT_PROJECT_ID).unlink(missing_ok=True)
        bug_reports_path(DEFAULT_PROJECT_ID).unlink(missing_ok=True)
        runs_path(DEFAULT_PROJECT_ID).unlink(missing_ok=True)
        impact_decisions_path(DEFAULT_PROJECT_ID).unlink(missing_ok=True)
    shutil.rmtree(_project_dir(project_id), ignore_errors=True)


# --- Grill interviews (raw JSON; validated by spec_to_test.grill.persistence) ------------

def _grill_dir(project_id: str) -> Path:
    if _file_name(project_id, "project id") == DEFAULT_PROJECT_ID:
        return data_dir() / GRILL_DIR
    return _project_dir(project_id) / GRILL_DIR


def _interview_path(project_id: str, session_id: str) -> Path:
    return _grill_dir(project_id) / f"{_file_name(session_id, 'session id')}.json"


def _read_json(path: Path, limit: int = MAX_INTERVIEW_BYTES) -> dict | None:
    try:
        if path.stat().st_size > limit:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_interview_data(project_id: str, session_id: str, data: dict) -> None:
    """Write one interview; does nothing in "session" mode."""
    if not persistence_enabled():
        return
    _write_atomic(_interview_path(project_id, session_id), json.dumps(data, ensure_ascii=False, indent=1))


def load_interview_data(project_id: str, session_id: str) -> dict | None:
    if not persistence_enabled():
        return None
    try:
        return _read_json(_interview_path(project_id, session_id))
    except ValueError:  # not a valid id
        return None


def list_interview_data(project_id: str) -> list[dict]:
    """Every readable saved interview of the project (unreadable files are skipped)."""
    if not persistence_enabled():
        return []
    try:
        paths = sorted(_grill_dir(project_id).glob("*.json"))
    except (OSError, ValueError):
        return []
    found = []
    for path in paths:
        if path.name.startswith(".") or path.name == LATEST_FILE or not path.stem.isalnum():
            continue
        if (data := _read_json(path)) is not None:
            found.append(data)
    return found


def delete_interview(project_id: str, session_id: str) -> None:
    if not persistence_enabled():
        return
    _interview_path(project_id, session_id).unlink(missing_ok=True)


def save_interview_pointer(project_id: str, session_id: str) -> None:
    """Remember the interview to reopen after a reload ("" = none)."""
    if not persistence_enabled():
        return
    if session_id:
        _file_name(session_id, "session id")
    _write_atomic(_grill_dir(project_id) / LATEST_FILE, json.dumps({"session_id": session_id}))


def load_interview_pointer(project_id: str) -> str:
    if not persistence_enabled():
        return ""
    try:
        data = _read_json(_grill_dir(project_id) / LATEST_FILE) or {}
        session_id = str(data.get("session_id") or "")
        return _file_name(session_id, "session id") if session_id else ""
    except ValueError:
        return ""


# --- QA Agent memory (raw JSON; validated by spec_to_test.qa_agent.memory) -------------

def memory_path(project_id: str) -> Path:
    if _file_name(project_id, "project id") == DEFAULT_PROJECT_ID:
        return data_dir() / MEMORY_FILE
    return _project_dir(project_id) / MEMORY_FILE


def save_memory_data(project_id: str, data: dict) -> None:
    """Write the project's QA Agent memory; does nothing in "session" mode."""
    if not persistence_enabled():
        return
    _write_atomic(memory_path(project_id), json.dumps(data, ensure_ascii=False, indent=1))


def load_memory_data(project_id: str) -> dict | None:
    if not persistence_enabled():
        return None
    try:
        return _read_json(memory_path(project_id))
    except ValueError:  # not a valid id
        return None


def delete_memory_data(project_id: str) -> None:
    if not persistence_enabled():
        return
    memory_path(project_id).unlink(missing_ok=True)


# --- Bug Reports (raw JSON; validated by spec_to_test.bug_generator.store) -------------

def bug_reports_path(project_id: str) -> Path:
    if _file_name(project_id, "project id") == DEFAULT_PROJECT_ID:
        return data_dir() / BUG_REPORTS_FILE
    return _project_dir(project_id) / BUG_REPORTS_FILE


def save_bug_reports_data(project_id: str, data: dict) -> None:
    """Write the project's bug reports; does nothing in "session" mode."""
    if not persistence_enabled():
        return
    _write_atomic(bug_reports_path(project_id), json.dumps(data, ensure_ascii=False, indent=1))


def load_bug_reports_data(project_id: str) -> dict | None:
    if not persistence_enabled():
        return None
    try:
        return _read_json(bug_reports_path(project_id))
    except ValueError:  # not a valid id
        return None


def delete_bug_reports_data(project_id: str) -> None:
    if not persistence_enabled():
        return
    bug_reports_path(project_id).unlink(missing_ok=True)


# --- Manual test runs (raw JSON; validated by spec_to_test.execution) -------------------

def runs_path(project_id: str) -> Path:
    if _file_name(project_id, "project id") == DEFAULT_PROJECT_ID:
        return data_dir() / RUNS_FILE
    return _project_dir(project_id) / RUNS_FILE


def save_runs_data(project_id: str, data: dict) -> None:
    """Write the project's test runs; does nothing in "session" mode."""
    if not persistence_enabled():
        return
    _write_atomic(runs_path(project_id), json.dumps(data, ensure_ascii=False, indent=1))


def load_runs_data(project_id: str) -> dict | None:
    if not persistence_enabled():
        return None
    try:
        return _read_json(runs_path(project_id), MAX_RUNS_BYTES)
    except ValueError:  # not a valid id
        return None


def delete_runs_data(project_id: str) -> None:
    if not persistence_enabled():
        return
    runs_path(project_id).unlink(missing_ok=True)


# --- Confirmed decisions about the change impact (raw JSON; validated by spec_to_test.impact_decisions) ---

def impact_decisions_path(project_id: str) -> Path:
    if _file_name(project_id, "project id") == DEFAULT_PROJECT_ID:
        return data_dir() / IMPACT_DECISIONS_FILE
    return _project_dir(project_id) / IMPACT_DECISIONS_FILE


def save_impact_decisions_data(project_id: str, data: dict) -> None:
    """Write the project's impact decisions; does nothing in "session" mode."""
    if not persistence_enabled():
        return
    _write_atomic(impact_decisions_path(project_id), json.dumps(data, ensure_ascii=False, indent=1))


def load_impact_decisions_data(project_id: str) -> dict | None:
    if not persistence_enabled():
        return None
    try:
        return _read_json(impact_decisions_path(project_id))
    except ValueError:  # not a valid id
        return None


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
