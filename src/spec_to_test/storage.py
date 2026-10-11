"""Optionally persist the user's workspace (test cases, reviews, bug reports) on disk.

Storage modes (SPEC_TO_TEST_STORAGE):
- "session": the default everywhere. Work lives only in the browser session
  (Streamlit session state); nothing is read from or written to disk, so
  visitors of a shared deployment can never see each other's documents.
- "local":   opt-in, single-user machines only. Each analyzed document is
  stored as JSON in the data directory, keyed by a hash of its text, so
  re-analyzing the same document restores earlier edits. Enabled only by the
  exact value "local" (case and surrounding spaces ignored); any other or
  empty value means "session". Set SPEC_TO_TEST_DATA_DIR to change the folder.

The mode is read from the process environment (or Streamlit secrets, which
become environment variables) only. A .env file never switches it.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from spec_to_test.models import Workspace

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / ".spec_to_test_data"
LATEST_FILE = "latest.json"


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


def _workspace_path(doc_hash: str) -> Path:
    if not doc_hash.isalnum():  # the hash is used as a file name
        raise ValueError("invalid document hash")
    return data_dir() / "workspaces" / f"{doc_hash}.json"


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


def save_workspace(workspace: Workspace) -> None:
    """Write the workspace to disk; does nothing in "session" mode."""
    if not persistence_enabled():
        return
    _write_atomic(_workspace_path(workspace.document_hash), workspace.model_dump_json(indent=2))
    _write_atomic(data_dir() / LATEST_FILE, json.dumps({"document_hash": workspace.document_hash}))


def load_workspace(doc_hash: str) -> Workspace | None:
    """Return the saved workspace, or None if missing, unreadable or disabled."""
    if not persistence_enabled():
        return None
    try:
        path = _workspace_path(doc_hash)
        return Workspace.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


def load_latest() -> Workspace | None:
    if not persistence_enabled():
        return None
    try:
        pointer = json.loads((data_dir() / LATEST_FILE).read_text(encoding="utf-8"))
        return load_workspace(str(pointer["document_hash"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
