"""Saved bug reports of a project.

Where they live follows the storage mode (see storage.py), like projects and
QA Agent memory: "local" keeps one JSON file per project, "session" keeps them
in this browser session. Loading never trusts the file: it is size-limited and
every report is validated; unreadable reports are skipped.
"""

from collections.abc import MutableMapping
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from spec_to_test import storage
from spec_to_test.bug_generator.models import ProductBugReport

FORMAT: Literal["spec-to-test/bug-reports"] = "spec-to-test/bug-reports"
FORMAT_VERSION = 1
MAX_REPORTS = 500


class BugStoreError(ValueError):
    """A report cannot be saved; `code` maps to bugreport.error.<code>."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _to_data(reports: list[ProductBugReport]) -> dict[str, Any]:
    return {"format": FORMAT, "format_version": FORMAT_VERSION,
            "reports": [r.model_dump(mode="json") for r in reports]}


def _from_data(data: Any) -> list[ProductBugReport]:
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("format_version") != FORMAT_VERSION:
        return []
    raw = data.get("reports")
    found: list[ProductBugReport] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        try:
            report = ProductBugReport.model_validate(item)
        except ValidationError:
            continue  # unreadable report: skipped, never guessed
        if report.id not in seen:
            seen.add(report.id)
            found.append(report)
    return found[:MAX_REPORTS]


class BugReportStore(Protocol):
    def reports(self, project_id: str) -> list[ProductBugReport]: ...
    def save(self, project_id: str, report: ProductBugReport) -> None: ...
    def delete(self, project_id: str, report_id: str) -> None: ...
    def delete_project(self, project_id: str) -> None: ...


class _Store:
    """Shared save / delete over `_read` and `_write` of a project's whole list."""

    def _read(self, project_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def reports(self, project_id: str) -> list[ProductBugReport]:
        return _from_data(self._read(project_id))

    def save(self, project_id: str, report: ProductBugReport) -> None:
        """Add the report, or replace the saved one with the same ID."""
        current = self.reports(project_id)
        if any(r.id == report.id for r in current):
            self._write(project_id, _to_data([report if r.id == report.id else r for r in current]))
            return
        if len(current) >= MAX_REPORTS:
            raise BugStoreError("full")
        self._write(project_id, _to_data([*current, report]))

    def delete(self, project_id: str, report_id: str) -> None:
        self._write(project_id, _to_data([r for r in self.reports(project_id) if r.id != report_id]))


class SessionBugReportStore(_Store):
    """Reports kept in this browser session only."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    def _read(self, project_id: str) -> dict[str, Any] | None:
        return self._data.get(project_id)

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        self._data[project_id] = data

    def delete_project(self, project_id: str) -> None:
        self._data.pop(project_id, None)


class DiskBugReportStore(_Store):
    """Reports in the project's folder (SPEC_TO_TEST_STORAGE=local)."""

    def _read(self, project_id: str) -> dict[str, Any] | None:
        return storage.load_bug_reports_data(project_id)

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        storage.save_bug_reports_data(project_id, data)

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
