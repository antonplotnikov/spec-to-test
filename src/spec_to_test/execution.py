"""Manual test execution: test runs of a document's test cases, with results a tester records.

A run is a stable record: its ID (RUN-001, never reused), the suite it was started from, the
environment and build it ran on, the date, and one result per test case: Passed, Failed, Blocked
or Not Run, with an optional comment and Bug ID. Approved means reviewed, not executed: only a
recorded Passed or Failed result counts as executed.

Where runs live follows the storage mode (see storage.py), like bug reports: "local" keeps one
file per project (`test_runs.json`), "session" keeps them in this browser session. Loading never
trusts the file: it is size-limited and every run and result is validated.
"""

import threading
from collections.abc import Callable, Iterable, MutableMapping
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from spec_to_test import storage
from spec_to_test.filelock import locked

FORMAT: Literal["spec-to-test/test-runs"] = "spec-to-test/test-runs"
FORMAT_VERSION = 1
MAX_RUNS = 100
MAX_RESULTS_PER_RUN = 2000


class RunStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"


class RunError(ValueError):
    """A run cannot be saved or changed; `code` maps to execution.error.<code>."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CaseResult(BaseModel):
    # Fields this version does not know are kept on save (see TestRun).
    model_config = ConfigDict(extra="allow")

    test_case_id: str = Field(min_length=1, max_length=64)
    status: RunStatus = RunStatus.NOT_RUN
    comment: str = Field(default="", max_length=2000)
    bug_id: str = Field(default="", max_length=100)
    updated_at: str = ""


class TestRun(BaseModel):
    # Fields this version does not know are kept on save: a file written by a newer version is not trimmed.
    model_config = ConfigDict(extra="allow")

    id: str = Field(pattern=r"^RUN-\d{3,}$")
    name: str = Field(min_length=1, max_length=120)
    # The suite the cases were taken from: smoke, regression, full, or all.
    suite: str = Field(default="all", max_length=20)
    environment: str = Field(default="", max_length=200)
    build: str = Field(default="", max_length=100)
    document_hash: str = Field(min_length=1, max_length=64)
    created_at: str = ""
    results: list[CaseResult] = Field(default_factory=list, max_length=MAX_RESULTS_PER_RUN)


class RunSummary(BaseModel):
    total: int
    passed: int
    failed: int
    blocked: int
    not_run: int
    # Share of cases with any result other than Not Run, in percent.
    progress: float
    # Passed / (Passed + Failed), in percent; None while no case has a verdict.
    pass_rate: float | None


def new_run(run_id: str, name: str, suite: str, environment: str, build: str, document_hash: str,
            test_case_ids: Iterable[str], now: str) -> TestRun:
    """A run with every given test case Not Run."""
    results = [CaseResult(test_case_id=tc_id) for tc_id in dict.fromkeys(test_case_ids)]
    if not results:
        raise RunError("no_test_cases")
    return TestRun(id=run_id, name=name, suite=suite, environment=environment, build=build,
                   document_hash=document_hash, created_at=now, results=results)


def record_result(run: TestRun, test_case_id: str, status: RunStatus, comment: str, bug_id: str,
                  now: str) -> TestRun:
    """The run with the given case's result replaced. The run itself is not changed."""
    if not any(r.test_case_id == test_case_id for r in run.results):
        raise RunError("unknown_test_case")
    results = [
        CaseResult(test_case_id=test_case_id, status=status, comment=comment.strip(), bug_id=bug_id.strip(),
                   updated_at=now) if r.test_case_id == test_case_id else r
        for r in run.results
    ]
    return run.model_copy(update={"results": results})


def summarize(run: TestRun) -> RunSummary:
    counts = {status: sum(r.status == status for r in run.results) for status in RunStatus}
    total = len(run.results)
    verdicts = counts[RunStatus.PASSED] + counts[RunStatus.FAILED]
    return RunSummary(
        total=total,
        passed=counts[RunStatus.PASSED],
        failed=counts[RunStatus.FAILED],
        blocked=counts[RunStatus.BLOCKED],
        not_run=counts[RunStatus.NOT_RUN],
        progress=round(100 * (total - counts[RunStatus.NOT_RUN]) / total, 1) if total else 0.0,
        pass_rate=round(100 * counts[RunStatus.PASSED] / verdicts, 1) if verdicts else None,
    )


def next_run_id(runs: list[TestRun]) -> str:
    numbers = [int(r.id.removeprefix("RUN-")) for r in runs]
    return f"RUN-{max(numbers, default=0) + 1:03d}"


def case_ids_in_runs(runs: Iterable[TestRun], document_hash: str) -> set[str]:
    """Every test case ID that a run of this document refers to (never handed out again)."""
    return {r.test_case_id for run in runs if run.document_hash == document_hash for r in run.results}


def executed_requirement_ids(runs: Iterable[TestRun], document_hash: str,
                             requirement_of: dict[str, str]) -> set[str]:
    """Requirements with at least one Passed or Failed result in a run of this document."""
    return {
        requirement_of[r.test_case_id]
        for run in runs if run.document_hash == document_hash
        for r in run.results
        if r.status in (RunStatus.PASSED, RunStatus.FAILED) and r.test_case_id in requirement_of
    }


# --- Storage -------------------------------------------------------------------------------------
#
# Every change is a transaction: the file is read again under its lock, the change is applied to the
# latest version, and the result is written back. So a result recorded in one tab is never lost to a
# stale copy in another, and a run ID is chosen only from the runs that exist at that moment.


def _to_data(runs: list[TestRun], kept: list[Any]) -> dict[str, Any]:
    return {"format": FORMAT, "format_version": FORMAT_VERSION,
            "runs": [r.model_dump(mode="json") for r in runs] + kept}


def _parse(data: Any) -> tuple[list[TestRun], list[Any]]:
    """The readable runs, and the entries that could not be read. Those are kept as they are on write,
    so a newer or damaged entry is never dropped silently. A file of another format is refused."""
    if data is None:
        return [], []
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("format_version") != FORMAT_VERSION:
        raise RunError("unreadable")
    raw = data.get("runs")
    runs: list[TestRun] = []
    kept: list[Any] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        try:
            run = TestRun.model_validate(item)
        except ValidationError:
            kept.append(item)
            continue
        if run.id in seen:
            kept.append(item)
            continue
        seen.add(run.id)
        runs.append(run)
    return runs[:MAX_RUNS], kept


class RunStore(Protocol):
    def runs(self, project_id: str) -> list[TestRun]: ...
    def add_run(self, project_id: str, make: Callable[[list[TestRun]], TestRun]) -> TestRun: ...
    def update_run(self, project_id: str, run_id: str, change: Callable[[TestRun], TestRun]) -> TestRun: ...
    def delete_project(self, project_id: str) -> None: ...


class _Store:
    """Transactions over a project's whole list of runs; `_read` / `_write` and `_lock` differ by mode."""

    def _read(self, project_id: str) -> Any:
        raise NotImplementedError

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def _lock(self, project_id: str) -> Any:
        raise NotImplementedError

    def _unreadable(self, project_id: str) -> bool:
        return False

    def runs(self, project_id: str) -> list[TestRun]:
        try:
            return _parse(self._read(project_id))[0]
        except RunError:
            return []  # shown as empty; nothing is written by reading

    def _transaction(self, project_id: str, change: Callable[[list[TestRun], list[Any]], tuple[list[TestRun], Any]]) -> Any:
        with self._lock(project_id):
            if self._unreadable(project_id):
                raise RunError("unreadable")
            runs, kept = _parse(self._read(project_id))
            new_runs, result = change(runs, kept)
            if len(new_runs) > MAX_RUNS:
                raise RunError("full")
            self._write(project_id, _to_data(new_runs, kept))
            return result

    def add_run(self, project_id: str, make: Callable[[list[TestRun]], TestRun]) -> TestRun:
        """Add a run made from the runs that exist now (its ID is chosen here, under the lock)."""
        def change(runs: list[TestRun], kept: list[Any]) -> tuple[list[TestRun], TestRun]:
            run = make(runs)
            if any(r.id == run.id for r in runs):
                raise RunError("id_taken")
            return [*runs, run], run
        return self._transaction(project_id, change)

    def update_run(self, project_id: str, run_id: str, change_run: Callable[[TestRun], TestRun]) -> TestRun:
        """Change one run, applied to its latest saved version."""
        def change(runs: list[TestRun], kept: list[Any]) -> tuple[list[TestRun], TestRun]:
            current = next((r for r in runs if r.id == run_id), None)
            if current is None:
                raise RunError("unknown_run")
            updated = change_run(current)
            return [updated if r.id == run_id else r for r in runs], updated
        return self._transaction(project_id, change)


class SessionRunStore(_Store):
    """Runs kept in this browser session only."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._mutex = threading.Lock()

    def _read(self, project_id: str) -> Any:
        return self._data.get(project_id)

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        self._data[project_id] = data

    def _lock(self, project_id: str) -> Any:
        return self._mutex

    def delete_project(self, project_id: str) -> None:
        self._data.pop(project_id, None)


class DiskRunStore(_Store):
    """Runs in the project's folder (SPEC_TO_TEST_STORAGE=local), under the file's lock."""

    def _read(self, project_id: str) -> Any:
        return storage.load_runs_data(project_id)

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        storage.save_runs_data(project_id, data)

    def _lock(self, project_id: str) -> Any:
        return locked(storage.runs_path(project_id))

    def _unreadable(self, project_id: str) -> bool:
        # A file that exists but does not parse is not "no runs": writing over it would destroy it.
        return storage.load_runs_data(project_id) is None and storage.runs_path(project_id).exists()

    def delete_project(self, project_id: str) -> None:
        storage.delete_runs_data(project_id)


def open_run_store(session_state: MutableMapping[Any, Any]) -> RunStore:
    """The store for the current storage mode; the session one lives in `session_state`."""
    if storage.persistence_enabled():
        return DiskRunStore()
    store = session_state.get("run_store")
    if not isinstance(store, SessionRunStore):
        store = session_state["run_store"] = SessionRunStore()
    return store
