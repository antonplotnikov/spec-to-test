"""Saved bug reports of a project.

Where they live follows the storage mode (see storage.py), like projects and
QA Agent memory: "local" keeps one JSON file per project, "session" keeps them
in this browser session.

Every change is a transaction: the file is read again under its lock, the change is applied to the
latest version, and the result is written back. A new report never replaces a saved one that has the
same ID: it gets the next free ID instead (two tabs can both draft BR-004). Reports that cannot be read
are kept as they are on write, and a file of another format or a damaged file is never overwritten.
"""

import threading
from collections.abc import MutableMapping
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from spec_to_test import storage
from spec_to_test.bug_generator.models import ProductBugReport, next_report_id
from spec_to_test.filelock import locked

FORMAT: Literal["spec-to-test/bug-reports"] = "spec-to-test/bug-reports"
FORMAT_VERSION = 1
MAX_REPORTS = 500


class BugStoreError(ValueError):
    """A report cannot be saved; `code` maps to bugreport.error.<code>."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _to_data(reports: list[ProductBugReport], kept: list[Any]) -> dict[str, Any]:
    return {"format": FORMAT, "format_version": FORMAT_VERSION,
            "reports": [r.model_dump(mode="json") for r in reports] + kept}


def _parse(data: Any) -> tuple[list[ProductBugReport], list[Any]]:
    """The readable reports, and the entries that could not be read (kept as they are on write)."""
    if data is None:
        return [], []
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("format_version") != FORMAT_VERSION:
        raise BugStoreError("unreadable")
    raw = data.get("reports")
    found: list[ProductBugReport] = []
    kept: list[Any] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        try:
            report = ProductBugReport.model_validate(item)
        except ValidationError:
            kept.append(item)
            continue
        if report.id in seen:
            kept.append(item)
            continue
        seen.add(report.id)
        found.append(report)
    return found[:MAX_REPORTS], kept


class BugReportStore(Protocol):
    def reports(self, project_id: str) -> list[ProductBugReport]: ...
    def save(self, project_id: str, report: ProductBugReport, *, new: bool = False) -> ProductBugReport: ...
    def delete(self, project_id: str, report_id: str) -> None: ...
    def delete_project(self, project_id: str) -> None: ...


class _Store:
    """Transactions over a project's whole list of reports; `_read`, `_write`, `_lock` differ by mode."""

    def _read(self, project_id: str) -> Any:
        raise NotImplementedError

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def _lock(self, project_id: str) -> Any:
        raise NotImplementedError

    def _unreadable(self, project_id: str) -> bool:
        return False

    def _transaction(self, project_id: str, change: Any) -> Any:
        with self._lock(project_id):
            if self._unreadable(project_id):
                raise BugStoreError("unreadable")
            reports, kept = _parse(self._read(project_id))
            new_reports, result = change(reports)
            if len(new_reports) > MAX_REPORTS:
                raise BugStoreError("full")
            self._write(project_id, _to_data(new_reports, kept))
            return result

    def reports(self, project_id: str) -> list[ProductBugReport]:
        try:
            return _parse(self._read(project_id))[0]
        except BugStoreError:
            return []  # shown as empty; reading never writes

    def save(self, project_id: str, report: ProductBugReport, *, new: bool = False) -> ProductBugReport:
        """Replace the saved report with the same ID, or add it. A `new` report whose ID is taken gets the
        next free ID. Returns the report as saved (its ID may have changed)."""
        def change(reports: list[ProductBugReport]) -> tuple[list[ProductBugReport], ProductBugReport]:
            saved = report
            if new and any(r.id == report.id for r in reports):
                saved = report.model_copy(update={"id": next_report_id(reports)})
            existing = next((r for r in reports if r.id == saved.id), None)
            if existing is not None:
                # Fields this version does not know, saved by a newer one, are carried over.
                saved = ProductBugReport.model_validate({**(existing.model_extra or {}), **saved.model_dump()})
                return [saved if r.id == saved.id else r for r in reports], saved
            return [*reports, saved], saved
        return self._transaction(project_id, change)

    def delete(self, project_id: str, report_id: str) -> None:
        self._transaction(project_id, lambda reports: ([r for r in reports if r.id != report_id], None))


class SessionBugReportStore(_Store):
    """Reports kept in this browser session only."""

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


class DiskBugReportStore(_Store):
    """Reports in the project's folder (SPEC_TO_TEST_STORAGE=local), under the file's lock."""

    def _read(self, project_id: str) -> Any:
        return storage.load_bug_reports_data(project_id)

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        storage.save_bug_reports_data(project_id, data)

    def _lock(self, project_id: str) -> Any:
        return locked(storage.bug_reports_path(project_id))

    def _unreadable(self, project_id: str) -> bool:
        return storage.load_bug_reports_data(project_id) is None and storage.bug_reports_path(project_id).exists()

    def delete_project(self, project_id: str) -> None:
        storage.delete_bug_reports_data(project_id)


def open_bug_report_store(session_state: MutableMapping[Any, Any]) -> BugReportStore:
    """The store for the current storage mode; the session one lives in `session_state`."""
    if storage.persistence_enabled():
        return DiskBugReportStore()
    store = session_state.get("bug_report_store")
    if not isinstance(store, SessionBugReportStore):
        store = session_state["bug_report_store"] = SessionBugReportStore()
    return store
