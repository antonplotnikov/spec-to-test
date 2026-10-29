"""The lock around saved files: exclusion, timeouts, release, and the lost-update regression it prevents."""

import threading

import pytest

from spec_to_test import filelock, storage
from spec_to_test.filelock import LockBusy, locked
from spec_to_test.models import Requirement, Workspace
from spec_to_test.storage import load_workspace, save_workspace


def make(title: str) -> Workspace:
    return Workspace(document_hash="race01", title=title, requirements=[Requirement(id="REQ-1", text="x")])


def test_a_held_lock_excludes_a_second_holder_in_the_same_process(tmp_path):
    target = tmp_path / "doc.json"
    with locked(target):
        with pytest.raises(LockBusy):
            with locked(target, timeout=0.05):
                pass  # a second acquisition in the same process must wait, not pass


def test_the_lock_is_released_when_the_block_fails(tmp_path):
    target = tmp_path / "doc.json"
    with pytest.raises(RuntimeError):
        with locked(target):
            raise RuntimeError("boom")
    with locked(target, timeout=0.05):  # free again
        pass


def test_the_lock_file_is_not_a_document(tmp_path):
    target = tmp_path / "doc.json"
    with locked(target):
        pass
    assert (tmp_path / ".doc.json.lock").exists()
    assert not target.exists()


def test_a_save_waits_for_the_lock_and_fails_cleanly_when_it_stays_busy(monkeypatch):
    save_workspace(make("base"))
    monkeypatch.setattr(filelock, "LOCK_TIMEOUT_S", 0.05)
    path = storage.data_dir() / "workspaces" / "race01.json"
    copy = load_workspace("race01")
    copy.title = "edit"
    with locked(path):
        with pytest.raises(LockBusy):
            save_workspace(copy)  # LockBusy is an OSError: the app shows "could not save"
    assert load_workspace("race01").title == "base"  # nothing was written
    assert copy._stored_digest == load_workspace("race01")._stored_digest


def test_overwrite_waits_for_the_lock_too(monkeypatch):
    save_workspace(make("base"))
    monkeypatch.setattr(filelock, "LOCK_TIMEOUT_S", 0.05)
    path = storage.data_dir() / "workspaces" / "race01.json"
    with locked(path):
        with pytest.raises(LockBusy):
            storage.overwrite_workspace(make("mine"))
    assert load_workspace("race01").title == "base"


def test_two_saves_of_one_document_never_lose_an_edit_silently(monkeypatch):
    """Regression: the first writer passes its check, and the second one saves meanwhile.

    Without the lock the second save succeeded and the first one then overwrote it with no
    conflict reported, so the second edit vanished. With the lock the second save must wait and then
    report a conflict, and the first edit stays on disk.
    """
    save_workspace(make("base"))
    a_copy, b_copy = load_workspace("race01"), load_workspace("race01")
    a_copy.title, b_copy.title = "from A", "from B"
    real_write = storage._write_atomic
    a_writing, b_done = threading.Event(), threading.Event()
    outcome: dict[str, str] = {}

    def paused_write(path, content):
        if threading.current_thread().name == "A" and not a_writing.is_set():
            a_writing.set()  # A has passed its check and holds the lock
            b_done.wait(timeout=0.5)  # B tries to save meanwhile
        real_write(path, content)

    monkeypatch.setattr(storage, "_write_atomic", paused_write)

    def attempt(name, copy):
        try:
            save_workspace(copy)
            outcome[name] = "saved"
        except storage.WorkspaceConflict:
            outcome[name] = "conflict"
        if name == "B":
            b_done.set()

    threads = [threading.Thread(target=attempt, args=("A", a_copy), name="A"),
               threading.Thread(target=attempt, args=("B", b_copy), name="B")]
    threads[0].start()
    assert a_writing.wait(5)  # B starts only once A is inside its write
    threads[1].start()
    for thread in threads:
        thread.join(10)
    assert outcome == {"A": "saved", "B": "conflict"}  # B waited for A's write, then saw A's version
    assert load_workspace("race01").title == "from A"
