"""Persist the user's workspace (test cases, reviews, bug reports) locally.

Each analyzed document is stored as JSON in the data directory, keyed by a
hash of its text, so re-analyzing the same document restores earlier edits.
Data never leaves the machine. Set SPEC_TO_TEST_DATA_DIR to change the folder.

Storage modes (SPEC_TO_TEST_STORAGE):
- "local":   save to disk and restore on the next visit (default on your computer).
- "session": keep work only in the browser session, never write to disk.
  This is the default on Streamlit Community Cloud, where the disk is shared
  by every visitor and saved documents would be visible to other people.
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
STORAGE_MODES = ("local", "session")
# Streamlit Community Cloud checks apps out under this folder.
CLOUD_SOURCE_ROOT = Path("/mount/src")


def is_streamlit_cloud(app_file: Path | None = None) -> bool:
    path = (app_file or Path(__file__)).resolve()
    return CLOUD_SOURCE_ROOT in path.parents


def storage_mode() -> str:
    """Return "local" or "session" (see module docstring)."""
    mode = os.environ.get("SPEC_TO_TEST_STORAGE", "").strip().lower()
    if mode in STORAGE_MODES:
        return mode
    return "session" if is_streamlit_cloud() else "local"


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
