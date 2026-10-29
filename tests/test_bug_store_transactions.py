"""Saved bug reports as transactions: IDs of new drafts, unreadable files, and two tabs saving at once."""

import json
import threading

import pytest

from spec_to_test import filelock, storage
from spec_to_test.bug_generator.models import ProductBugReport
from spec_to_test.bug_generator.store import (
    BugStoreError,
    DiskBugReportStore,
    SessionBugReportStore,
)


def report(report_id: str, title: str) -> ProductBugReport:
    return ProductBugReport(id=report_id, title=title, what="The page crashes.", created_at=f"t-{title}")


def test_a_new_draft_whose_id_is_taken_is_saved_under_the_next_free_id():
    store = SessionBugReportStore()
    store.save("p", report("BR-001", "First"))
    saved = store.save("p", report("BR-001", "Second"), new=True)
    assert saved.id == "BR-002"
    assert {r.title for r in store.reports("p")} == {"First", "Second"}


def test_saving_an_existing_report_updates_it_and_never_adds_a_copy():
    store = SessionBugReportStore()
    store.save("p", report("BR-001", "First"))
    store.save("p", report("BR-001", "Renamed"))
    assert [(r.id, r.title) for r in store.reports("p")] == [("BR-001", "Renamed")]


def test_a_damaged_reports_file_is_refused_and_left_alone():
    path = storage.bug_reports_path("default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(BugStoreError) as error:
        DiskBugReportStore().save("default", report("BR-001", "x"))
    assert error.value.code == "unreadable"
    assert path.read_text(encoding="utf-8") == "{not json"


def test_a_file_of_another_format_is_refused_and_left_alone():
    path = storage.bug_reports_path("default")
    path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"format": "someone-else", "format_version": 9, "reports": []})
    path.write_text(original, encoding="utf-8")
    assert DiskBugReportStore().reports("default") == []  # reading shows nothing
    with pytest.raises(BugStoreError):
        DiskBugReportStore().save("default", report("BR-001", "x"))
    assert path.read_text(encoding="utf-8") == original


def test_an_unreadable_report_inside_a_readable_file_is_kept_when_another_is_saved():
    store = DiskBugReportStore()
    store.save("default", report("BR-001", "First"))
    path = storage.bug_reports_path("default")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["reports"].append({"id": "not-a-report", "from": "a newer version"})
    path.write_text(json.dumps(data), encoding="utf-8")
    store.save("default", report("BR-002", "Second"))
    kept = json.loads(path.read_text(encoding="utf-8"))["reports"]
    assert {"id": "not-a-report", "from": "a newer version"} in kept


def test_fields_a_newer_version_added_survive_a_save_by_this_version():
    store = DiskBugReportStore()
    store.save("default", report("BR-001", "First"))
    path = storage.bug_reports_path("default")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["reports"][0]["reviewer_tag"] = "added later"
    path.write_text(json.dumps(data), encoding="utf-8")
    store.save("default", report("BR-001", "Renamed"))
    [saved] = json.loads(path.read_text(encoding="utf-8"))["reports"]
    assert (saved["title"], saved["reviewer_tag"]) == ("Renamed", "added later")


def test_two_tabs_saving_drafts_with_the_same_id_at_once_keep_both_reports():
    store = DiskBugReportStore()
    store.save("default", report("BR-001", "Existing"))
    results, errors = [], []

    def save(title):
        try:
            results.append(store.save("default", report("BR-002", title), new=True))
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(f"Draft {n}",)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert not errors
    ids = sorted(r.id for r in store.reports("default"))
    assert len(ids) == 7 and len(set(ids)) == 7
    assert sorted(r.id for r in results) == sorted(set(r.id for r in results))  # each save got its own ID


def test_a_busy_reports_file_is_reported_and_nothing_is_written(monkeypatch):
    store = DiskBugReportStore()
    store.save("default", report("BR-001", "First"))
    monkeypatch.setattr(filelock, "LOCK_TIMEOUT_S", 0.05)
    with filelock.locked(storage.bug_reports_path("default")):
        with pytest.raises(OSError):
            store.save("default", report("BR-002", "Second"))
    assert [r.id for r in store.reports("default")] == ["BR-001"]
