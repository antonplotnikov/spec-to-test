"""Manual test execution: runs, recorded results, the figures, storage and what counts as executed."""

import csv
import io
import json
import threading

import pytest

from spec_to_test import execution, filelock, storage
from spec_to_test.execution import (
    DiskRunStore,
    RunError,
    RunStatus,
    SessionRunStore,
    executed_requirement_ids,
    new_run,
    next_run_id,
    open_run_store,
    record_result,
    summarize,
)
from spec_to_test.exports import run_csv
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import Workspace
from spec_to_test.rtm import build_rtm, coverage_levels
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.test_generator import generate_test_cases

NOW = "2026-10-29T10:00:00+00:00"
PASSED, FAILED, BLOCKED, NOT_RUN = RunStatus.PASSED, RunStatus.FAILED, RunStatus.BLOCKED, RunStatus.NOT_RUN


def run_of(*case_ids: str, document: str = "doc1", run_id: str = "RUN-001"):
    return new_run(run_id, "Smoke", "smoke", "Chrome 130, Windows", "1.2.0", document, case_ids, NOW)


# --- Runs and results ----------------------------------------------------------------------------

def test_a_new_run_has_every_case_once_and_not_run():
    run = run_of("TC-1", "TC-2", "TC-1")
    assert [(r.test_case_id, r.status) for r in run.results] == [("TC-1", NOT_RUN), ("TC-2", NOT_RUN)]


def test_a_run_needs_test_cases():
    with pytest.raises(RunError) as error:
        run_of()
    assert error.value.code == "no_test_cases"


def test_recording_a_result_changes_only_that_case_and_keeps_the_run_it_came_from():
    run = run_of("TC-1", "TC-2")
    updated = record_result(run, "TC-1", FAILED, "  Button missing ", " BUG-7 ", NOW)
    assert [r.status for r in updated.results] == [FAILED, NOT_RUN]
    assert (updated.results[0].comment, updated.results[0].bug_id) == ("Button missing", "BUG-7")
    assert updated.results[0].updated_at == NOW
    assert run.results[0].status == NOT_RUN  # the earlier copy is untouched


def test_a_result_for_a_case_outside_the_run_is_refused():
    with pytest.raises(RunError) as error:
        record_result(run_of("TC-1"), "TC-9", PASSED, "", "", NOW)
    assert error.value.code == "unknown_test_case"


def test_figures_count_progress_and_pass_rate_from_verdicts():
    run = run_of("TC-1", "TC-2", "TC-3", "TC-4")
    run = record_result(run, "TC-1", PASSED, "", "", NOW)
    run = record_result(run, "TC-2", FAILED, "", "BUG-1", NOW)
    run = record_result(run, "TC-3", BLOCKED, "", "", NOW)
    s = summarize(run)
    assert (s.total, s.passed, s.failed, s.blocked, s.not_run) == (4, 1, 1, 1, 1)
    assert s.progress == 75.0  # three of four have a result
    assert s.pass_rate == 50.0  # blocked is not a verdict: one passed of two


def test_the_pass_rate_is_unknown_while_no_case_has_a_verdict():
    assert summarize(record_result(run_of("TC-1"), "TC-1", BLOCKED, "", "", NOW)).pass_rate is None


def test_run_ids_follow_the_highest_existing_one():
    assert next_run_id([]) == "RUN-001"
    assert next_run_id([run_of("TC-1", run_id="RUN-003")]) == "RUN-004"


def test_only_a_verdict_in_a_run_of_this_document_counts_as_executed():
    mapping = {"TC-1": "REQ-1", "TC-2": "REQ-2", "TC-3": "REQ-3"}
    run = record_result(run_of("TC-1", "TC-2"), "TC-1", PASSED, "", "", NOW)
    run = record_result(run, "TC-2", BLOCKED, "", "", NOW)
    other = record_result(run_of("TC-3", document="doc2", run_id="RUN-002"), "TC-3", FAILED, "", "", NOW)
    assert executed_requirement_ids([run, other], "doc1", mapping) == {"REQ-1"}
    assert executed_requirement_ids([run, other], "doc2", mapping) == {"REQ-3"}


# --- Storage ---------------------------------------------------------------------------------------

def test_the_session_store_adds_a_run_and_updates_its_latest_version():
    store = SessionRunStore()
    store.add_run("p", lambda runs: run_of("TC-1"))
    store.update_run("p", "RUN-001", lambda r: record_result(r, "TC-1", PASSED, "", "", NOW))
    [run] = store.runs("p")
    assert (run.id, run.results[0].status) == ("RUN-001", PASSED)


def test_disk_runs_survive_a_reload_and_an_unreadable_entry_is_kept_not_dropped():
    store = DiskRunStore()
    store.add_run("default", lambda runs: run_of("TC-1"))
    assert [r.id for r in store.runs("default")] == ["RUN-001"]
    path = storage.runs_path("default")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["runs"].append({"id": "not-a-run", "from": "a newer version"})
    path.write_text(json.dumps(data), encoding="utf-8")
    store.update_run("default", "RUN-001", lambda r: record_result(r, "TC-1", PASSED, "", "", NOW))
    kept = json.loads(path.read_text(encoding="utf-8"))["runs"]
    assert {"id": "not-a-run", "from": "a newer version"} in kept  # written back, never dropped
    assert [r.id for r in DiskRunStore().runs("default")] == ["RUN-001"]


def test_a_file_of_another_format_is_never_overwritten():
    path = storage.runs_path("default")
    path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"format": "other", "format_version": 1, "runs": []})
    path.write_text(original, encoding="utf-8")
    assert DiskRunStore().runs("default") == []  # reading shows nothing
    with pytest.raises(RunError) as error:
        DiskRunStore().add_run("default", lambda runs: run_of("TC-1"))
    assert error.value.code == "unreadable"
    assert path.read_text(encoding="utf-8") == original


def test_a_damaged_file_is_never_overwritten():
    path = storage.runs_path("default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RunError) as error:
        DiskRunStore().add_run("default", lambda runs: run_of("TC-1"))
    assert error.value.code == "unreadable"
    assert path.read_text(encoding="utf-8") == "{not json"


def test_the_store_refuses_more_runs_than_its_limit(monkeypatch):
    monkeypatch.setattr(execution, "MAX_RUNS", 1)
    store = SessionRunStore()
    store.add_run("p", lambda runs: run_of("TC-1"))
    with pytest.raises(RunError) as error:
        store.add_run("p", lambda runs: run_of("TC-1", run_id="RUN-002"))
    assert error.value.code == "full"


def test_a_result_recorded_from_a_stale_copy_does_not_erase_another_tabs_result():
    """Regression: tab A still shows the run as it was before tab B recorded a result.

    A result is always applied to the latest saved run, so tab A's later result must not drop the
    result tab B saved in between.
    """
    store = DiskRunStore()
    store.add_run("default", lambda runs: run_of("TC-1", "TC-2"))
    store.update_run("default", "RUN-001", lambda r: record_result(r, "TC-2", FAILED, "", "BUG-2", NOW))  # tab B
    store.update_run("default", "RUN-001", lambda r: record_result(r, "TC-1", PASSED, "", "", NOW))  # tab A, stale
    results = {r.test_case_id: r.status for r in store.runs("default")[0].results}
    assert results == {"TC-1": PASSED, "TC-2": FAILED}


def test_run_ids_are_unique_when_runs_are_added_at_the_same_time():
    store = DiskRunStore()
    errors = []

    def add():
        try:
            store.add_run("default", lambda runs: new_run(next_run_id(runs), "Smoke", "smoke", "", "",
                                                          "doc1", ["TC-1"], NOW))
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=add) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert not errors
    ids = [r.id for r in store.runs("default")]
    assert len(ids) == 8 and len(set(ids)) == 8


def test_a_busy_runs_file_is_reported_and_left_unchanged(monkeypatch):
    store = DiskRunStore()
    store.add_run("default", lambda runs: run_of("TC-1"))
    monkeypatch.setattr(filelock, "LOCK_TIMEOUT_S", 0.05)
    with filelock.locked(storage.runs_path("default")):
        with pytest.raises(OSError):
            store.add_run("default", lambda runs: run_of("TC-1", run_id="RUN-002"))
    assert [r.id for r in store.runs("default")] == ["RUN-001"]


def test_the_session_store_is_kept_in_the_session_state(monkeypatch):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "session")
    state: dict = {}
    assert open_run_store(state) is open_run_store(state)
    assert isinstance(open_run_store(state), SessionRunStore)


# --- Export and coverage -------------------------------------------------------------------------

def test_the_results_csv_lists_every_case_and_marks_removed_ones():
    run = record_result(run_of("TC-1", "TC-2"), "TC-1", FAILED, "Crash", "BUG-1", NOW)
    rows = list(csv.reader(io.StringIO(run_csv(run, {"TC-1": "Login"}, "en"))))
    assert rows[1][1:5] == ["Login", "Failed", "Crash", "BUG-1"]
    assert rows[2][1] == "removed from the document"


def make_workspace(example_text) -> Workspace:
    result = analyze_requirements(extract_requirements(example_text))
    ws = Workspace(requirements=result.requirements, findings=result.findings)
    ws.test_cases = generate_test_cases(ws)
    return ws


def test_execution_is_unknown_without_runs_and_a_share_of_requirements_with_runs(example_text):
    rows = build_rtm(make_workspace(example_text))
    assert coverage_levels(rows).execution is None  # no runs recorded: not zero
    assert coverage_levels(rows, set()).execution == 0.0  # runs recorded, nothing executed
    assert coverage_levels(rows, {"REQ-1"}).execution == round(100 / 9, 1)
