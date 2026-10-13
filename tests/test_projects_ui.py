"""Projects in the app: create, switch, add requirement documents, rename, delete."""

import pytest
from test_app_features import button, new_app
from test_grill_ui import OTHER_DOC

from conftest import goto, home
from spec_to_test.i18n import t
from spec_to_test.projects import DEFAULT_PROJECT_ID


def project_select(at):
    return at.sidebar.selectbox(key="project_select")


def document_select(at):
    return at.sidebar.selectbox(key="project_document_select")


def analyze(at, text):
    home(at).text_area(key="requirements_text").input(text).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception, at.exception
    return at


def create_project(at, name, description=""):
    at.sidebar.text_input(key="project_new_name").input(name)
    at.sidebar.text_input(key="project_new_description").input(description)
    button(at, "project_create").click().run()
    assert not at.exception, at.exception
    return at


def workspace(at):
    return at.session_state["workspace"] if "workspace" in at.session_state else None


def test_default_project_holds_the_first_document(example_text):
    at = new_app()
    assert project_select(at).options == ["My project"]
    assert document_select(at).value == "__new__"
    assert any("Project: My project" in c.value for c in at.caption)

    analyze(at, example_text)
    ws = workspace(at)
    assert ws.title == "Password Reset — Requirements"
    assert ws.created_at
    assert document_select(at).value == ws.document_hash  # the sidebar shows it right away
    assert document_select(at).options[0] == f"({len(ws.requirements)}) Password Reset — Requirements"
    assert at.session_state["project_id"] == DEFAULT_PROJECT_ID


def test_new_project_starts_empty_and_keeps_its_own_documents(example_text):
    at = analyze(new_app(), example_text)
    button(at, "bug_generate").click().run()
    first = workspace(at)
    assert first.defects

    create_project(at, "Mobile banking", "iOS and Android app")
    assert project_select(at).value != DEFAULT_PROJECT_ID
    assert "Mobile banking" in project_select(at).options
    assert any("Mobile banking" in s.value for s in at.sidebar.success)
    assert any("iOS and Android app" == c.value for c in at.sidebar.caption)
    assert workspace(at) is None
    assert at.sidebar.radio(key="app_mode").value == "home"  # a new project starts on Home
    assert any(t("input.empty_state") in i.value for i in at.info)
    assert at.sidebar.text_input(key="project_new_name").value == ""

    analyze(at, example_text)  # the same text in another project is separate work
    assert not workspace(at).defects
    analyze(at, OTHER_DOC)
    assert len(document_select(at).options) == 3  # two documents + "New requirements"

    project_select(at).set_value(DEFAULT_PROJECT_ID).run()
    assert not at.exception
    assert workspace(at) == first  # the default project reopens with its bug reports
    assert len(document_select(at).options) == 2


def test_switching_documents_inside_a_project(example_text):
    at = analyze(new_app(), example_text)
    first = workspace(at)

    document_select(at).set_value("__new__").run()
    assert workspace(at) is None
    analyze(at, OTHER_DOC)
    second = workspace(at)
    assert second.document_hash != first.document_hash
    assert [o.split(") ", 1)[-1] for o in document_select(at).options] == [
        "Password Reset — Requirements", "REQ-1: The user must be able to log out.", "➕ New requirements"
    ]

    document_select(at).set_value(first.document_hash).run()
    assert workspace(at) == first
    assert not at.exception

    create_project(at, "Other")  # switching project and back returns to the document used last
    project_select(at).set_value(DEFAULT_PROJECT_ID).run()
    assert workspace(at) == first


def test_reanalyzing_a_document_of_the_project_restores_its_work(example_text):
    at = analyze(new_app(), example_text)
    button(at, "bug_generate").click().run()
    analyze(at, OTHER_DOC)
    analyze(at, example_text)
    assert workspace(at).defects
    assert any("Restored" in i.value for i in at.info)


@pytest.mark.parametrize(
    ("name", "error"),
    [("   ", "Enter a project name."), ("my PROJECT", "A project with this name already exists.")],
)
def test_project_name_is_checked(name, error):
    at = create_project(new_app(), "My project")
    create_project(at, name)
    assert any(error == e.value for e in at.sidebar.error)
    assert len(project_select(at).options) == 1


def test_rename_project(example_text):
    at = goto(analyze(new_app(), example_text), "settings")  # project settings live on Settings
    at.text_input(key=f"project_name_{DEFAULT_PROJECT_ID}").input("Legacy portal")
    at.text_input(key=f"project_description_{DEFAULT_PROJECT_ID}").input("Old web portal")
    button(at, "project_save").click().run()
    assert not at.exception
    assert any("Legacy portal" in s.value for s in at.sidebar.success)
    assert any("Project: Legacy portal" in c.value for c in goto(at, "home").caption)
    assert any("Old web portal" == c.value for c in at.sidebar.caption)
    assert workspace(at) is not None  # renaming keeps the open document


def test_deleting_needs_confirmation(example_text):
    at = analyze(new_app(), example_text)
    create_project(at, "Throwaway")
    goto(analyze(at, OTHER_DOC), "settings")
    assert button(at, "project_delete").disabled
    assert button(at, "project_delete_document").disabled

    at.checkbox(key="project_confirm_delete").check().run()
    button(at, "project_delete_document").click().run()
    assert not at.exception
    assert workspace(at) is None
    assert document_select(at).options == ["➕ New requirements"]
    assert at.sidebar.radio(key="app_mode").value == "home"  # no document left: add one on Home

    goto(analyze(at, OTHER_DOC), "settings")
    assert at.checkbox(key="project_confirm_delete").value is False  # asked again
    at.checkbox(key="project_confirm_delete").check().run()
    button(at, "project_delete").click().run()
    assert not at.exception
    assert project_select(at).options == ["My project"]
    assert any("Throwaway" in s.value for s in at.sidebar.success)
    assert workspace(at).title == "Password Reset — Requirements"  # back in the default project


def test_local_mode_reopens_the_last_project_and_document(example_text, tmp_path):
    at = create_project(new_app(), "Payments")
    analyze(at, OTHER_DOC)
    project_id = project_select(at).value

    again = new_app()  # a new browser session
    assert project_select(again).value == project_id
    assert workspace(again).document_hash == document_select(at).value
    assert any("Restored" in i.value for i in again.info)
    assert (tmp_path / "data" / "projects" / project_id / "project.json").exists()


def test_local_mode_reopens_an_empty_project(tmp_path):
    at = create_project(new_app(), "Empty")
    again = new_app()
    assert project_select(again).value == project_select(at).value
    assert workspace(again) is None


def test_session_mode_keeps_projects_in_the_browser_session(monkeypatch, example_text, tmp_path):
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)
    at = analyze(new_app(), example_text)
    first = workspace(at)
    create_project(at, "Private")
    private = at.session_state["project_id"]
    analyze(at, OTHER_DOC)
    second = workspace(at)

    project_select(at).set_value(DEFAULT_PROJECT_ID).run()
    assert workspace(at) == first
    project_select(at).set_value(private).run()
    assert workspace(at) == second  # kept while the session lives
    assert not (tmp_path / "data").exists()

    other = new_app()  # another visitor sees none of it
    assert project_select(other).options == ["My project"]
    assert workspace(other) is None


def test_an_empty_default_project_gives_way_to_the_first_real_one():
    at = create_project(new_app(), "Payments")
    assert project_select(at).options == ["Payments"]


@pytest.mark.parametrize(("lang", "name"), [("uk", "Мій проєкт"), ("ru", "Мой проект")])
def test_default_project_name_is_translated(lang, name):
    at = new_app()
    at.selectbox(key="language").select(lang).run()
    assert project_select(at).label == t("projects.project", lang)
    assert project_select(at).options == [name]
    assert any(name in c.value for c in at.caption)


def test_input_is_emptied_when_another_document_or_project_opens(example_text):
    """The last analyzed text must not look like part of the next document or project."""
    at = analyze(new_app(), example_text)
    goto(at, "dashboard")  # the input keeps its text while Home is not shown
    assert home(at).text_area(key="requirements_text").value == example_text  # kept for re-analyzing
    first = workspace(at)

    document_select(at).set_value("__new__").run()
    assert at.sidebar.radio(key="app_mode").value == "home"
    assert at.text_area(key="requirements_text").value == ""
    analyze(at, OTHER_DOC)
    document_select(at).set_value(first.document_hash).run()
    assert home(at).text_area(key="requirements_text").value == ""
    assert workspace(at) == first  # its requirements are in the tabs, not in the input

    home(at).text_area(key="requirements_text").input("REQ-9: half typed").run()
    create_project(at, "Fresh")
    assert at.text_area(key="requirements_text").value == ""
    assert workspace(at) is None


def test_uploaded_file_is_dropped_when_another_project_opens(example_text):
    at = new_app()
    home(at).file_uploader[0].upload("spec.md", example_text.encode("utf-8"), "text/markdown").run()
    home(at).button(key="analyze").click().run()
    assert workspace(at).title == "spec.md"
    create_project(at, "Fresh")
    assert not home(at).file_uploader[0].value
    home(at).button(key="analyze").click().run()  # nothing left to analyze
    assert workspace(at) is None


def test_documents_saved_before_projects_are_named_by_their_first_requirement(tmp_path):
    from spec_to_test.models import Requirement, Workspace
    from spec_to_test.storage import document_hash

    old = Workspace(
        document_hash=document_hash("old"),
        requirements=[Requirement(id="REQ-1", text="Пользователь может восстановить пароль через почту и смс")],
    )
    folder = tmp_path / "data" / "workspaces"
    folder.mkdir(parents=True)
    (folder / f"{old.document_hash}.json").write_text(old.model_dump_json(exclude={"title", "created_at"}))

    at = new_app()
    document_select(at).set_value(old.document_hash).run()
    assert document_select(at).options[0] == (
        "(1) Пользователь может восстановить пароль через почту и смс"
    )
