import json
import os
import tempfile
from pathlib import Path

import pytest

from conftest import goto, home
from spec_to_test import storage
from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestType, Workspace
from spec_to_test.storage import (
    data_dir,
    document_hash,
    load_latest,
    load_workspace,
    persistence_enabled,
    save_workspace,
    storage_mode,
)


def sample() -> Workspace:
    return Workspace(
        document_hash=document_hash("REQ-1: x"),
        requirements=[Requirement(id="REQ-1", text="The system must save drafts.")],
        test_cases=[
            TestCase(id="TC-001", requirement_id="REQ-1", title="Edited", test_type=TestType.POSITIVE,
                     steps=["a"], expected_result="b", review_status=ReviewStatus.APPROVED)
        ],
    )


def test_round_trip_keeps_edits():
    ws = sample()
    save_workspace(ws)
    loaded = load_workspace(ws.document_hash)
    assert loaded == ws
    assert load_latest() == ws


def test_a_copy_older_than_the_saved_file_is_not_saved():
    ws = sample()
    save_workspace(ws)
    first, second = load_workspace(ws.document_hash), load_workspace(ws.document_hash)  # e.g. two writers
    first.test_cases[0].title = "First"
    save_workspace(first)
    first.test_cases[0].title = "First again"
    save_workspace(first)  # its own last save is not a conflict
    second.test_cases[0].title = "Second"
    with pytest.raises(storage.WorkspaceConflict):
        save_workspace(second)
    assert load_workspace(ws.document_hash).test_cases[0].title == "First again"
    with pytest.raises(storage.WorkspaceConflict):
        save_workspace(ws)  # the copy saved first is outdated too
    reloaded = load_workspace(ws.document_hash)
    reloaded.test_cases[0].title = "Second"
    save_workspace(reloaded)
    assert load_workspace(ws.document_hash).test_cases[0].title == "Second"


def test_uses_configured_data_dir(tmp_path):
    save_workspace(sample())
    assert data_dir() == tmp_path / "data"
    assert list((tmp_path / "data" / "workspaces").glob("*.json"))


def test_missing_and_corrupt_files_return_none(tmp_path):
    assert load_latest() is None
    assert load_workspace("0123456789abcdef") is None
    ws = sample()
    save_workspace(ws)
    path = tmp_path / "data" / "workspaces" / f"{ws.document_hash}.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_workspace(ws.document_hash) is None
    (tmp_path / "data" / "latest.json").write_text(json.dumps({"document_hash": "../../etc"}))
    assert load_latest() is None


def test_hash_cannot_escape_data_dir():
    assert load_workspace("../secrets") is None


def test_hash_is_stable_and_content_based():
    assert document_hash("abc") == document_hash("abc")
    assert document_hash("abc") != document_hash("abd")


# --- Storage modes (shared hosting must not keep or restore documents) ---------------

def seed_old_files(tmp_path) -> None:
    """Leave a saved workspace on disk, as an earlier local run or old version would."""
    save_workspace(sample())  # conftest runs these tests in "local" mode
    assert (tmp_path / "data" / "latest.json").exists()


@pytest.mark.parametrize("value", [None, "", "   ", "session", "SESSION", "everywhere", "locally", "true", "1", "local-ish"])
def test_everything_except_explicit_local_means_session(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)
    else:
        monkeypatch.setenv("SPEC_TO_TEST_STORAGE", value)
    assert storage_mode() == "session"
    assert not persistence_enabled()


@pytest.mark.parametrize("value", ["local", "LOCAL", "Local", "  local  ", "\tLocal\n"])
def test_only_explicit_local_enables_disk_storage(monkeypatch, value):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", value)
    assert storage_mode() == "local"
    assert persistence_enabled()


def test_mount_src_path_no_longer_changes_the_mode(monkeypatch):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "local")
    monkeypatch.setattr(storage, "__file__", "/mount/src/spec-to-test/src/spec_to_test/storage.py")
    assert storage_mode() == "local"  # an explicit setting always wins
    assert not hasattr(storage, "is_streamlit_cloud")
    assert not hasattr(storage, "CLOUD_SOURCE_ROOT")


def test_dotenv_file_cannot_switch_the_mode(tmp_path, monkeypatch, no_network, example_text):
    """The app reads its .env (AI settings), but SPEC_TO_TEST_STORAGE=local there is ignored."""
    from test_app_features import button, new_app

    from spec_to_test import ai_analysis
    from spec_to_test.llm import config as llm_config

    env_file = tmp_path / ".env"
    env_file.write_text(
        "SPEC_TO_TEST_STORAGE=local\nAI_PROVIDER=anthropic\nANTHROPIC_API_KEY=test-key-123\n",
        encoding="utf-8",
    )
    # The app calls load_settings() with its default .env path; point that default (and the
    # constant, for any other reader) at this file.
    monkeypatch.setattr(ai_analysis, "ENV_FILE", env_file)
    monkeypatch.setattr(ai_analysis.load_config, "__defaults__", (None, env_file))
    monkeypatch.setattr(llm_config.load_settings, "__defaults__", (None, env_file))
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)  # let the file's AI settings apply
    monkeypatch.chdir(tmp_path)  # a .env in the working directory is not picked up either

    at = goto(new_app(), "settings")
    assert any("AI is configured" in info.value for info in at.info)  # the file was read
    assert any("only for this browser session" in c.value for c in at.sidebar.caption)
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    button(at, "bug_generate").click().run()
    assert not at.exception
    assert at.session_state["workspace"].defects
    assert "SPEC_TO_TEST_STORAGE" not in os.environ
    assert storage_mode() == "session"
    assert not (tmp_path / "data").exists()  # nothing was saved


def test_session_mode_never_writes_or_reads(tmp_path, monkeypatch):
    seed_old_files(tmp_path)
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    save_workspace(Workspace(document_hash="abc123", requirements=[]))
    assert load_latest() is None  # old files are ignored
    assert load_workspace(sample().document_hash) is None
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
    assert not (tmp_path / "data" / "workspaces" / "abc123.json").exists()


def test_session_mode_performs_no_disk_io_at_all(tmp_path, monkeypatch):
    seed_old_files(tmp_path)
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("disk access in session mode")

    for target in ("read_text", "write_text", "mkdir", "unlink", "open"):
        monkeypatch.setattr(Path, target, forbidden)
    monkeypatch.setattr(os, "replace", forbidden)
    monkeypatch.setattr(os, "fdopen", forbidden)
    monkeypatch.setattr(tempfile, "mkstemp", forbidden)
    save_workspace(sample())
    assert load_latest() is None
    assert load_workspace(sample().document_hash) is None


def test_local_mode_still_round_trips_after_session_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)
    save_workspace(sample())
    assert not (tmp_path / "data").exists()
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "local")
    save_workspace(sample())
    assert load_latest() == sample()


# --- Saving never replaces a file silently (conflicts) ------------------------------

def _titled(title: str) -> Workspace:
    ws = sample()
    ws.test_cases[0].title = title
    return ws


def _saved_title(doc_hash: str) -> str:
    return json.loads((data_dir() / "workspaces" / f"{doc_hash}.json").read_text(encoding="utf-8"))[
        "test_cases"][0]["title"]


def test_a_new_copy_does_not_replace_a_saved_file():
    ws = _titled("Saved")
    save_workspace(ws)
    with pytest.raises(storage.WorkspaceConflict):
        save_workspace(_titled("New copy"))  # e.g. analyzed again in another tab at the same time
    assert _saved_title(ws.document_hash) == "Saved"
    assert not list((data_dir() / "workspaces").glob(".tmp-*"))  # the temporary copy is cleaned up


def test_first_save_waits_for_a_writer_holding_the_lock_and_then_refuses_its_file():
    import threading

    from spec_to_test import filelock

    ws = _titled("Ours")
    path = data_dir() / "workspaces" / f"{ws.document_hash}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    holding, release = threading.Event(), threading.Event()

    def other_writer():
        with filelock.locked(path):  # another writer checks, then creates the file under the lock
            holding.set()
            path.write_text(_titled("Theirs").model_dump_json(), encoding="utf-8")
            release.wait(timeout=5)

    writer = threading.Thread(target=other_writer)
    writer.start()
    holding.wait(timeout=5)
    threading.Timer(0.2, release.set).start()  # the other writer lets go after a moment
    with pytest.raises(storage.WorkspaceConflict):
        save_workspace(ws)  # waits for the lock, then sees the file that now exists
    writer.join(5)
    assert _saved_title(ws.document_hash) == "Theirs"


def test_unsaved_copy_sits_beside_the_documents_and_is_not_a_document():
    ws = _titled("Saved")
    save_workspace(ws)
    path = storage.keep_unsaved_copy(_titled("Unsaved"))
    assert path.parent == data_dir() / "conflicts"
    assert path.name.startswith(f"{ws.document_hash}.unsaved-") and path.suffix == ".json"
    assert json.loads(path.read_text(encoding="utf-8"))["test_cases"][0]["title"] == "Unsaved"
    assert [d.document_hash for d in storage.list_documents("default")] == [ws.document_hash]
    assert _saved_title(ws.document_hash) == "Saved"


def test_unsaved_copies_never_replace_each_other():
    first = storage.keep_unsaved_copy(_titled("First edit"))
    again = storage.keep_unsaved_copy(_titled("First edit"))
    second = storage.keep_unsaved_copy(_titled("Second edit"))
    assert first == again  # the same edit is written once
    assert second != first
    assert json.loads(first.read_text(encoding="utf-8"))["test_cases"][0]["title"] == "First edit"


def test_unsaved_copy_of_another_project_is_kept_in_its_folder():
    ws = _titled("Unsaved")
    path = storage.keep_unsaved_copy(ws, "proj1")
    assert path.parent == data_dir() / "projects" / "proj1" / "conflicts"
    assert "proj1" not in [p.id for p in storage.list_projects()]  # a copy does not create a project


def test_my_version_replaces_the_saved_file_and_keeps_the_replaced_one():
    saved = _titled("Saved")
    save_workspace(saved)
    elsewhere = storage.load_workspace(saved.document_hash)
    elsewhere.test_cases[0].title = "Elsewhere"
    save_workspace(elsewhere)  # another writer saves a newer version
    mine = _titled("Mine")  # a copy from before: it has no digest yet
    replaced = storage.overwrite_workspace(mine)
    assert _saved_title(saved.document_hash) == "Mine"
    assert replaced is not None
    assert json.loads(replaced.read_text(encoding="utf-8"))["test_cases"][0]["title"] == "Elsewhere"
    save_workspace(mine)  # the copy now follows the saved file, so this is not a conflict
    assert _saved_title(saved.document_hash) == "Mine"


def test_overwrite_without_a_saved_file_keeps_nothing():
    first = _titled("First")
    assert storage.overwrite_workspace(first) is None
    assert _saved_title(first.document_hash) == "First"


def test_conflict_copies_are_not_written_in_session_mode(monkeypatch):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "session")
    assert storage.keep_unsaved_copy(_titled("Unsaved")) is None
    assert storage.overwrite_workspace(_titled("Mine")) is None
    assert not (data_dir() / "conflicts").exists()
