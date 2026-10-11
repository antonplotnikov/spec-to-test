import json

from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestType, Workspace
from spec_to_test.storage import (
    data_dir,
    document_hash,
    load_latest,
    load_workspace,
    save_workspace,
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

def test_session_mode_never_writes_or_reads(tmp_path, monkeypatch):
    from spec_to_test.storage import persistence_enabled

    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "session")
    assert not persistence_enabled()
    save_workspace(sample())
    assert not (tmp_path / "data").exists()
    assert load_latest() is None
    assert load_workspace(sample().document_hash) is None


def test_local_mode_is_default_on_a_computer(monkeypatch):
    from spec_to_test.storage import storage_mode

    monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)
    assert storage_mode() == "local"


def test_streamlit_cloud_defaults_to_session(monkeypatch):
    from pathlib import Path

    from spec_to_test import storage

    monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)
    assert storage.is_streamlit_cloud(Path("/mount/src/spec-to-test/src/spec_to_test/storage.py"))
    assert not storage.is_streamlit_cloud(Path("/home/user/spec-to-test/src/spec_to_test/storage.py"))
    monkeypatch.setattr(storage, "is_streamlit_cloud", lambda app_file=None: True)
    assert storage.storage_mode() == "session"
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "local")  # explicit setting wins
    assert storage.storage_mode() == "local"


def test_unknown_mode_falls_back_to_default(monkeypatch):
    from spec_to_test.storage import storage_mode

    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "everywhere")
    assert storage_mode() == "local"
