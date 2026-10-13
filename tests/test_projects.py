"""Projects: models, both stores, the on-disk layout and backward compatibility."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from spec_to_test import storage
from spec_to_test.models import Project, Requirement, Workspace
from spec_to_test.projects import (
    DEFAULT_PROJECT_ID,
    DiskProjectStore,
    ProjectError,
    SessionProjectStore,
    check_name,
    document_title,
    new_project,
    open_store,
)
from spec_to_test.storage import document_hash


def workspace(text: str = "REQ-1: The system must save drafts.", title: str = "Spec", created_at: str = "1") -> Workspace:
    return Workspace(
        document_hash=document_hash(text),
        title=title,
        created_at=created_at,
        requirements=[Requirement(id="REQ-1", text=text)],
    )


@pytest.fixture(params=["disk", "session"])
def store(request, monkeypatch):
    if request.param == "session":
        monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)
        return SessionProjectStore()
    return DiskProjectStore()


# --- Behaviour shared by both stores -----------------------------------------------------

def test_there_is_always_a_default_project(store):
    assert [p.id for p in store.projects()] == [DEFAULT_PROJECT_ID]
    assert store.projects()[0].name == ""  # the UI names it in the reader's language
    assert store.documents(DEFAULT_PROJECT_ID) == []


def test_projects_keep_their_documents_apart(store):
    app = new_project("Mobile app", "iOS and Android", store.projects())
    web = new_project("Web shop", "", [*store.projects(), app])
    store.save_project(app)
    store.save_project(web)
    assert {p.name for p in store.projects()} == {"Mobile app", "Web shop"}

    same_text = workspace()
    store.save(app.id, same_text)
    edited = same_text.model_copy(deep=True)
    edited.requirements[0].text = "Edited only in the web shop"
    store.save(web.id, edited)

    assert store.load(app.id, same_text.document_hash) == same_text
    assert store.load(web.id, same_text.document_hash) == edited
    assert [d.title for d in store.documents(app.id)] == ["Spec"]
    assert store.documents(app.id)[0].requirements == 1
    assert store.load(DEFAULT_PROJECT_ID, same_text.document_hash) is None


def test_documents_are_listed_oldest_first(store):
    store.save(DEFAULT_PROJECT_ID, workspace("REQ-1: b", title="Second", created_at="2026-10-13T10:00:01"))
    store.save(DEFAULT_PROJECT_ID, workspace("REQ-1: a", title="First", created_at="2026-10-13T10:00:00"))
    assert [d.title for d in store.documents(DEFAULT_PROJECT_ID)] == ["First", "Second"]


def test_saved_copy_does_not_change_with_unsaved_edits(store):
    ws = workspace()
    store.save(DEFAULT_PROJECT_ID, ws)
    ws.title = "Not saved"
    loaded = store.load(DEFAULT_PROJECT_ID, ws.document_hash)
    assert loaded is not None and loaded.title == "Spec"
    loaded.title = "Also not saved"
    assert store.load(DEFAULT_PROJECT_ID, ws.document_hash).title == "Spec"


def test_delete_document_and_project(store):
    project = new_project("Billing", "", store.projects())
    store.save_project(project)
    first, second = workspace("REQ-1: one"), workspace("REQ-1: two")
    store.save(project.id, first)
    store.save(project.id, second)

    store.delete_document(project.id, first.document_hash)
    assert [d.document_hash for d in store.documents(project.id)] == [second.document_hash]

    store.delete_project(project.id)
    assert project.id not in {p.id for p in store.projects()}
    assert store.documents(project.id) == []
    assert store.load(project.id, second.document_hash) is None


def test_deleting_the_default_project_leaves_an_empty_default(store):
    store.save(DEFAULT_PROJECT_ID, workspace())
    store.delete_project(DEFAULT_PROJECT_ID)
    assert [p.id for p in store.projects()] == [DEFAULT_PROJECT_ID]
    assert store.documents(DEFAULT_PROJECT_ID) == []


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "ab cd", "ключ"])
def test_unsafe_document_hashes_are_refused(store, bad):
    with pytest.raises(ValueError):
        store.save(DEFAULT_PROJECT_ID, Workspace(document_hash=bad))


# --- Names and titles -----------------------------------------------------------------

def test_names_are_cleaned_and_checked():
    existing = [Project(id="a1", name="Mobile App")]
    assert check_name("  New   project ", existing) == "New project"
    for name, code in [("   ", "name_required"), ("x" * 81, "name_too_long"), ("mobile app", "name_taken")]:
        with pytest.raises(ProjectError) as error:
            check_name(name, existing)
        assert error.value.code == code
    assert check_name("Mobile App", existing, project_id="a1") == "Mobile App"  # renaming itself


def test_description_is_limited():
    with pytest.raises(ProjectError) as error:
        new_project("Name", "x" * 501, [])
    assert error.value.code == "description_too_long"


def test_new_projects_get_safe_unique_ids():
    ids = {new_project(f"P{i}", "", []).id for i in range(50)}
    assert len(ids) == 50
    assert all(pid.isalnum() and pid.isascii() and pid != DEFAULT_PROJECT_ID for pid in ids)


@pytest.mark.parametrize(
    ("text", "file_name", "expected"),
    [
        ("REQ-1: x", "spec.docx", "spec.docx"),
        ("\n\n# Password reset\nREQ-1: x", None, "Password reset"),
        ("REQ-1:   The   system", None, "REQ-1: The system"),
        ("a" * 100, None, "a" * 59 + "…"),
        ("   ", None, ""),
    ],
)
def test_document_title(text, file_name, expected):
    assert document_title(text, file_name) == expected


# --- On disk ----------------------------------------------------------------------------

def test_disk_layout_and_last_opened(tmp_path):
    store = DiskProjectStore()
    project = new_project("Mobile app", "", [])
    store.save_project(project)
    ws = workspace()
    store.save(project.id, ws)

    data = tmp_path / "data"
    assert json.loads((data / "projects" / project.id / "project.json").read_text())["name"] == "Mobile app"
    assert (data / "projects" / project.id / "workspaces" / f"{ws.document_hash}.json").exists()
    assert store.last_opened() == (project.id, ws.document_hash)
    assert storage.load_latest() == ws

    store.set_last_opened(project.id, "")
    assert store.last_opened() == (project.id, "")
    assert storage.load_latest() is None


def test_work_saved_before_projects_opens_in_the_default_project(tmp_path):
    """Older versions wrote workspaces/<hash>.json and latest.json without a project."""
    ws = workspace()
    data = tmp_path / "data"
    (data / "workspaces").mkdir(parents=True)
    (data / "workspaces" / f"{ws.document_hash}.json").write_text(
        ws.model_dump_json(exclude={"title", "created_at"}), encoding="utf-8"
    )
    (data / "latest.json").write_text(json.dumps({"document_hash": ws.document_hash}))

    store = DiskProjectStore()
    assert [p.id for p in store.projects()] == [DEFAULT_PROJECT_ID]
    assert store.last_opened() == (DEFAULT_PROJECT_ID, ws.document_hash)
    assert store.documents(DEFAULT_PROJECT_ID)[0].title == ""
    assert storage.load_latest() == ws.model_copy(update={"title": "", "created_at": ""})


def test_renamed_default_project_keeps_its_documents(tmp_path):
    store = DiskProjectStore()
    ws = workspace()
    store.save(DEFAULT_PROJECT_ID, ws)
    store.save_project(Project(id=DEFAULT_PROJECT_ID, name="Legacy"))
    assert [(p.id, p.name) for p in store.projects()] == [(DEFAULT_PROJECT_ID, "Legacy")]
    assert store.load(DEFAULT_PROJECT_ID, ws.document_hash) == ws


def test_broken_files_are_skipped(tmp_path):
    store = DiskProjectStore()
    project = new_project("P", "", [])
    store.save_project(project)
    store.save(project.id, workspace())
    folder = tmp_path / "data" / "projects" / project.id
    (folder / "workspaces" / "deadbeef.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "data" / "projects" / "broken").mkdir()
    (tmp_path / "data" / "projects" / "broken" / "project.json").write_text("[]", encoding="utf-8")
    (tmp_path / "data" / "projects" / "other").mkdir()
    (tmp_path / "data" / "projects" / "other" / "project.json").write_text(
        Project(id="spoofed", name="X").model_dump_json(), encoding="utf-8"
    )
    assert [p.id for p in store.projects()] == [project.id]
    assert len(store.documents(project.id)) == 1


def test_pointer_cannot_escape_the_data_folder(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "latest.json").write_text(json.dumps({"project_id": "../..", "document_hash": "abc"}))
    assert DiskProjectStore().last_opened() is None
    assert storage.load_latest() is None


# --- Session mode never touches the disk ------------------------------------------------

def test_session_store_performs_no_disk_io(tmp_path, monkeypatch):
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("disk access in session mode")

    for target in ("read_text", "write_text", "mkdir", "unlink", "open", "iterdir", "glob"):
        monkeypatch.setattr(Path, target, forbidden)
    monkeypatch.setattr(os, "replace", forbidden)
    monkeypatch.setattr(tempfile, "mkstemp", forbidden)

    state: dict = {}
    store = open_store(state)
    assert isinstance(store, SessionProjectStore)
    assert open_store(state) is store  # one store per browser session
    project = new_project("P", "", store.projects())
    store.save_project(project)
    store.save(project.id, workspace())
    store.set_last_opened(project.id, workspace().document_hash)
    assert store.last_opened() is None
    assert len(store.documents(project.id)) == 1
    store.delete_project(project.id)


def test_local_mode_uses_the_disk_store(monkeypatch):
    assert isinstance(open_store({}), DiskProjectStore)
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "session")
    assert isinstance(open_store({}), SessionProjectStore)
