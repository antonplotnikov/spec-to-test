"""Saving and restoring Grill interviews (disk, browser session, files)."""

import json

import pytest

from spec_to_test import storage
from spec_to_test.grill.models import AnswerStatus, GrillKind, GrillStep, RequirementsDraft
from spec_to_test.grill.persistence import (
    FORMAT_VERSION,
    MAX_IMPORT_BYTES,
    DiskInterviewStore,
    PersistenceError,
    SavedInterview,
    SessionInterviewStore,
    export_json,
    from_data,
    import_json,
    interview_title,
    open_interview_store,
)
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import Project
from spec_to_test.projects import DiskProjectStore

REQS = extract_requirements("""REQ-1: The password must be at least 8 characters.
REQ-2: The password must be at least 10 characters.
REQ-3: The page should load fast.""")


def half_done():
    """One answer given, one question open."""
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=REQS))
    return WF.answer(session, "REQ-1: The password must be at least 8 characters.")


def record(project_id: str = "default", session=None) -> SavedInterview:
    return SavedInterview(project_id=project_id, document_hash="abc123", session=session or half_done(),
                          unparsed=["??? line"])


def assert_same_interview(restored, original):
    assert restored.answers == original.answers
    assert restored.history == original.history
    assert restored.current_question_id == original.current_question_id
    assert restored.progress == original.progress
    assert [q.id for q in restored.unresolved_questions] == [q.id for q in original.unresolved_questions]
    assert restored.events == original.events
    assert restored.draft == original.draft


@pytest.mark.parametrize("store_type", [DiskInterviewStore, SessionInterviewStore])
def test_an_interview_comes_back_exactly(store_type):
    store = store_type()
    saved = record()
    store.save(saved)
    restored = store.load("default", saved.session.id)
    assert restored is not None and restored.saved_at and restored.unparsed == ["??? line"]
    assert_same_interview(restored.session, saved.session)
    # ...and it can be continued.
    continued = WF.answer(restored.session, "Within 2 seconds", AnswerStatus.ASSUMED)
    assert continued.step == GrillStep.SHOW_DRAFT


@pytest.mark.parametrize("store_type", [DiskInterviewStore, SessionInterviewStore])
def test_list_last_active_and_delete(store_type):
    store = store_type()
    first, second = record(), record()
    finished = record(session=WF.cancel(half_done()))
    for item in (first, second, finished):
        store.save(item)
    summaries = store.interviews("default")
    assert len(summaries) == 3 and summaries[-1].finished  # unfinished first
    assert summaries[0].answered == 1 and summaries[0].total == 2 and summaries[0].unresolved == 1
    assert summaries[0].title == "REQ-1, REQ-2, REQ-3"
    store.set_last_active("default", second.session.id)
    assert store.last_active("default") == second.session.id
    store.delete("default", second.session.id)
    assert store.last_active("default") == ""
    assert store.load("default", second.session.id) is None
    assert store.interviews("other") == []


def test_disk_layout_follows_projects(tmp_path):
    store = DiskInterviewStore()
    store.save(record("default"))
    store.save(record("abc123"))
    assert len(list((storage.data_dir() / "grill").glob("*.json"))) == 1
    assert len(list((storage.data_dir() / "projects" / "abc123" / "grill").glob("*.json"))) == 1
    DiskProjectStore().save_project(Project(id="abc123", name="Shop"))
    storage.delete_project("abc123")
    assert DiskInterviewStore().interviews("abc123") == []
    storage.delete_project("default")
    assert DiskInterviewStore().interviews("default") == []


def test_session_mode_writes_nothing_to_disk(monkeypatch):
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE")
    state: dict = {}
    store = open_interview_store(state)
    assert isinstance(store, SessionInterviewStore) and open_interview_store(state) is store
    store.save(record())
    assert not storage.data_dir().exists()
    assert DiskInterviewStore().interviews("default") == []  # disk functions are off too


def test_broken_or_foreign_files_are_skipped_not_shown(tmp_path):
    folder = storage.data_dir() / "grill"
    folder.mkdir(parents=True)
    (folder / "aaaa.json").write_text("{not json", encoding="utf-8")
    (folder / "bbbb.json").write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
    (folder / "cccc.json").write_text(json.dumps({**json.loads(export_json(record())), "format_version": 99}), encoding="utf-8")
    store = DiskInterviewStore()
    store.save(record())
    assert len(store.interviews("default")) == 1
    assert store.load("default", "aaaa") is None
    assert store.load("default", "../etc") is None  # not a valid id: refused, not read


# --- Files ---------------------------------------------------------------------------------

def test_export_and_import_round_trip_into_the_current_project():
    saved = record("abc123")
    loaded = import_json(export_json(saved).encode("utf-8"), "default")
    assert loaded.project_id == "default"
    assert_same_interview(loaded.session, saved.session)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"not json", "interview_invalid"),
        (json.dumps({"format": "spec-to-test/grill-interview", "format_version": FORMAT_VERSION,
                     "session": {"schema_version": 2, "kind": "nonsense"}}).encode(), "interview_invalid"),
        (json.dumps({"format": "spec-to-test/grill-interview", "format_version": FORMAT_VERSION + 1}).encode(),
         "interview_version"),
        (json.dumps([1, 2]).encode(), "interview_invalid"),
        (b" " * (MAX_IMPORT_BYTES + 1), "interview_too_large"),
    ],
)
def test_bad_files_are_refused(raw, code):
    with pytest.raises(PersistenceError) as err:
        import_json(raw, "default")
    assert err.value.code == code


def test_a_file_cannot_choose_a_path_through_its_session_id():
    data = json.loads(export_json(record()))
    data["session"]["id"] = "../../outside"
    with pytest.raises(PersistenceError) as err:
        import_json(json.dumps(data), "default")
    assert err.value.code == "interview_invalid"


def test_a_file_with_a_schema_1_session_is_migrated():
    data = json.loads(export_json(record()))
    session = data["session"]
    for key in ("events", "created_at", "updated_at", "settled_question_ids"):
        session.pop(key)
    session["schema_version"] = 1
    loaded = from_data(data)
    assert loaded.session.schema_version == 3 and loaded.session.events[0].action.value == "migrated"
    assert loaded.session.answers.keys() == {"rule.contradiction.REQ-1+REQ-2"}


def test_titles_come_from_the_content():
    from spec_to_test.grill.models import BugReportDraft, GrillMode, TestCaseDraft

    tc = WF.submit_input(WF.start(GrillKind.TEST_CASE, GrillMode.REVIEW_DRAFT), TestCaseDraft(title="Login works"))
    bug = WF.submit_input(WF.start(GrillKind.BUG_REPORT), BugReportDraft(summary="Crash on save " * 20))
    assert interview_title(tc) == "Login works"
    assert interview_title(bug).endswith("…") and len(interview_title(bug)) <= 70
