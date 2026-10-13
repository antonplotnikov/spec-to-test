"""Where QA Agent plans and runs are kept.

Follows the storage mode (spec_to_test.storage):
- "local":   <data dir>/qa_agent/<project id>/plans/<document hash>.json and
             <data dir>/qa_agent/<project id>/runs/<run id>/run.json (+ screenshots);
- "session": the same layout in a private temp folder (mode 0700) that only
             this browser session knows, so visitors of a shared deployment
             never see each other's runs.

File names come only from validated ids (hex run ids, alphanumeric hashes and
project ids); evidence files are served only from inside their run folder.
"""

import secrets
import shutil
import tempfile
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from spec_to_test.qa_agent.models import QARun, RunState, TestPlan
from spec_to_test.storage import _file_name, _write_atomic, data_dir, persistence_enabled

MAX_FILE_BYTES = 10_000_000
NO_DOCUMENT = "nodocument"
SESSION_ROOT = "qa_agent_store_root"


def new_run_id() -> str:
    return secrets.token_hex(8)


def _run_id(run_id: str) -> str:
    if len(run_id) != 16 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("invalid run id")
    return run_id


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    # --- Plans ---------------------------------------------------------------------

    def _plan_path(self, document_hash: str) -> Path:
        return self.root / "plans" / f"{_file_name(document_hash or NO_DOCUMENT, 'document hash')}.json"

    def save_plan(self, plan: TestPlan) -> None:
        _write_atomic(self._plan_path(plan.document_hash), plan.model_dump_json(indent=1))

    def load_plan(self, document_hash: str) -> TestPlan | None:
        try:
            path = self._plan_path(document_hash)
            if path.stat().st_size > MAX_FILE_BYTES:
                return None
            return TestPlan.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None

    # --- Runs ----------------------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        return self.root / "runs" / _run_id(run_id)

    def save(self, run: QARun) -> None:
        _write_atomic(self.run_dir(run.id) / "run.json", run.model_dump_json(indent=1))

    def load(self, run_id: str) -> QARun | None:
        try:
            path = self.run_dir(run_id) / "run.json"
            if path.stat().st_size > MAX_FILE_BYTES:
                return None
            return QARun.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None

    def runs(self, document_hash: str | None = None) -> list[QARun]:
        """Saved runs, newest first; optionally only those of one document."""
        folder = self.root / "runs"
        if not folder.is_dir():
            return []
        found = []
        for path in folder.iterdir():
            try:
                run = self.load(path.name)
            except ValueError:
                continue
            if run is not None and (document_hash is None or run.document_hash == document_hash):
                found.append(run)
        return sorted(found, key=lambda r: (r.created_at, r.id), reverse=True)

    def evidence(self, run: QARun, name: str) -> Path | None:
        """A file of this run (a screenshot), or None; never a path outside the run folder."""
        if not name:
            return None
        base = self.run_dir(run.id).resolve()
        try:
            path = (base / name).resolve()
        except OSError:
            return None
        return path if path.parent == base and path.is_file() else None

    def delete(self, run_id: str) -> None:
        shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    def prune(self, keep: int) -> None:
        """Remove the oldest finished runs beyond `keep`."""
        finished = [r for r in self.runs() if r.state != RunState.RUNNING]
        for run in finished[keep:]:
            self.delete(run.id)


def open_run_store(session_state: MutableMapping[Any, Any], project_id: str) -> RunStore:
    if persistence_enabled():
        return RunStore(data_dir() / "qa_agent" / _file_name(project_id, "project id"))
    root = session_state.get(SESSION_ROOT)
    if not root or not Path(root).is_dir():
        root = tempfile.mkdtemp(prefix="spec-to-test-qa-")  # mkdtemp creates it with mode 0700
        session_state[SESSION_ROOT] = root
    return RunStore(Path(root) / _file_name(project_id, "project id"))
