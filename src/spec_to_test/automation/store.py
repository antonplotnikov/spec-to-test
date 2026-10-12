"""Job folders on disk, job ownership and service errors.

Kept free of heavy imports (no anyio, mcp or anthropic), so the page can list
approved tests and build exports even where the automation extras are not
installed.
"""

import re
import secrets
import shutil
import time
from pathlib import Path

from pydantic import ValidationError

from spec_to_test.automation.models import ACTIVE_STATUSES, AutomationJob
from spec_to_test.storage import _write_atomic, persistence_enabled

JOB_ID = re.compile(r"^[0-9a-f]{16}$")
LOCAL_OWNER = "local"


class AutomationError(Exception):
    """A request the service refuses. `code` maps to automation.error.<code>."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def job_dir(self, job_id: str) -> Path:
        if not JOB_ID.match(job_id):
            raise ValueError("invalid job id")
        return self.root / "jobs" / job_id

    def save(self, job: AutomationJob) -> None:
        _write_atomic(self.job_dir(job.id) / "job.json", job.model_dump_json(indent=1))

    def load(self, job_id: str) -> AutomationJob | None:
        try:
            return AutomationJob.model_validate_json((self.job_dir(job_id) / "job.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None

    def all(self) -> list[AutomationJob]:
        folder = self.root / "jobs"
        if not folder.is_dir():
            return []
        jobs = [self.load(path.name) for path in folder.iterdir() if JOB_ID.match(path.name)]
        return [job for job in jobs if job is not None]

    def artifact_path(self, job: AutomationJob, relative: str) -> Path | None:
        """A file of this job, or None (never a path outside its folder)."""
        base = self.job_dir(job.id).resolve()
        try:
            path = (base / relative).resolve()
            path.relative_to(base)
        except (ValueError, OSError):
            return None
        return path if path.is_file() else None

    def prune(self, max_age: float, keep: set[str]) -> None:
        cutoff = time.time() - max_age
        for job in self.all():
            folder = self.job_dir(job.id)
            if job.id not in keep and job.status not in ACTIVE_STATUSES and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)


def new_owner_id() -> str:
    """Who owns new jobs: everyone on a single-user machine, else this browser session only."""
    return LOCAL_OWNER if persistence_enabled() else secrets.token_hex(16)
