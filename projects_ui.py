"""Projects: pick a project and one of its requirement documents in the sidebar,
create one there; rename or delete on the Settings page.

The open document's workspace is `st.session_state["workspace"]` (see app.py);
it always belongs to the project in `st.session_state["project_id"]`. Every
change happens in a widget callback, so the page below already sees the new
project and document when it renders.
"""

import streamlit as st

from spec_to_test.i18n import t
from spec_to_test.models import DocumentSummary, Project
from spec_to_test.projects import (
    DEFAULT_PROJECT_ID,
    ProjectError,
    ProjectStore,
    check_description,
    check_name,
    document_title,
    new_project,
    summary_of,
)
from spec_to_test.qa_agent.memory import open_memory_store

ACTIVE = "project_id"
WORKSPACE = "workspace"  # the analysis page's workspace (see app.py)
LAST_DOCUMENT = "project_last_document"  # project id -> document hash, this session
MESSAGE = "project_message"
PROJECT_SELECT = "project_select"
DOCUMENT_SELECT = "project_document_select"
NEW_NAME = "project_new_name"
NEW_DESCRIPTION = "project_new_description"
CONFIRM_DELETE = "project_confirm_delete"
NEW_DOCUMENT = "__new__"
INPUT_TEXT = "requirements_text"  # the analysis page's input (see app.py)
INPUT_ROUND = "requirements_input_round"  # a new file uploader key empties it
NAV = "app_mode"  # the page shown (see shell_ui.py)


def keep_input() -> None:
    """Keep typed requirements while Home is not shown (call before any widget)."""
    if INPUT_TEXT in st.session_state:
        st.session_state[INPUT_TEXT] = st.session_state[INPUT_TEXT]


def project_name(project: Project, lang: str) -> str:
    return project.name or t("projects.default_name", lang)


def active_project_id() -> str:
    return str(st.session_state.get(ACTIVE) or DEFAULT_PROJECT_ID)


def _message(level: str, key: str, **params: object) -> None:
    st.session_state[MESSAGE] = (level, key, params)


def input_file_key() -> str:
    return f"requirements_file_{st.session_state.get(INPUT_ROUND, 0)}"


def _forget_document_state() -> None:
    """What belongs to the previous document must not carry over to the next one."""
    st.session_state.pop("restored", None)
    # The input holds the text last analyzed; left there, it reads as part of the next
    # document or project.
    st.session_state[INPUT_TEXT] = ""
    st.session_state[INPUT_ROUND] = st.session_state.get(INPUT_ROUND, 0) + 1
    st.session_state["ai_consent"] = False  # consent is per document and per run


def open_document(store: ProjectStore, project_id: str, doc_hash: str) -> None:
    """Make `doc_hash` ("" = none, ready for new requirements on Home) the open document.

    Runs in widget callbacks or before the navigation is drawn, so it may change the page.
    """
    _forget_document_state()
    st.session_state[ACTIVE] = project_id
    workspace = store.load(project_id, doc_hash) if doc_hash else None
    if workspace is None:
        st.session_state.pop(WORKSPACE, None)
        doc_hash = ""
        st.session_state[NAV] = "home"  # requirements are added on Home
    else:
        st.session_state[WORKSPACE] = workspace
    st.session_state.setdefault(LAST_DOCUMENT, {})[project_id] = doc_hash
    try:
        store.set_last_opened(project_id, doc_hash)
    except (OSError, ValueError):
        pass  # only a convenience for the next start


def remember_document(project_id: str, doc_hash: str) -> None:
    st.session_state.setdefault(LAST_DOCUMENT, {})[project_id] = doc_hash


def _open_project(store: ProjectStore, project_id: str) -> None:
    """Open the document last used in this project (this session), else its newest one."""
    documents = [d.document_hash for d in store.documents(project_id)]
    last = st.session_state.get(LAST_DOCUMENT, {}).get(project_id, None)
    if last is None:
        last = documents[-1] if documents else ""
    open_document(store, project_id, last if last in documents else "")


def restore_last_opened(store: ProjectStore) -> None:
    """Once per browser session: reopen the project and document used last ("local" mode)."""
    if st.session_state.get("restore_checked"):
        return
    st.session_state["restore_checked"] = True
    if (pointer := store.last_opened()) is None:
        return
    project_id, doc_hash = pointer
    if project_id not in {p.id for p in store.projects()}:
        return
    st.session_state[ACTIVE] = project_id
    if doc_hash and (workspace := store.load(project_id, doc_hash)) is not None:
        st.session_state[WORKSPACE] = workspace
        st.session_state["restored"] = "disk"
        remember_document(project_id, doc_hash)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _on_project_change(store: ProjectStore) -> None:
    _open_project(store, str(st.session_state[PROJECT_SELECT]))


def _on_document_change(store: ProjectStore, project_id: str) -> None:
    choice = str(st.session_state[DOCUMENT_SELECT])
    open_document(store, project_id, "" if choice == NEW_DOCUMENT else choice)


def _on_create(store: ProjectStore) -> None:
    try:
        project = new_project(
            str(st.session_state.get(NEW_NAME, "")), str(st.session_state.get(NEW_DESCRIPTION, "")), store.projects()
        )
        store.save_project(project)
    except ProjectError as error:
        _message("error", f"projects.error.{error.code}")
        return
    except (OSError, ValueError):
        _message("error", "projects.error.save_failed")
        return
    st.session_state[NEW_NAME] = ""
    st.session_state[NEW_DESCRIPTION] = ""
    open_document(store, project.id, "")
    _message("success", "projects.created", name=project.name)


def _on_edit(store: ProjectStore, project: Project) -> None:
    others = [p for p in store.projects() if p.id != project.id]
    try:
        updated = project.model_copy(
            update={
                "name": check_name(str(st.session_state.get(f"project_name_{project.id}", "")), others),
                "description": check_description(str(st.session_state.get(f"project_description_{project.id}", ""))),
            }
        )
        store.save_project(updated)
    except ProjectError as error:
        _message("error", f"projects.error.{error.code}")
        return
    except (OSError, ValueError):
        _message("error", "projects.error.save_failed")
        return
    _message("success", "projects.saved", name=updated.name)


def _on_delete_document(store: ProjectStore, project_id: str, doc_hash: str) -> None:
    st.session_state[CONFIRM_DELETE] = False
    try:
        store.delete_document(project_id, doc_hash)
    except (OSError, ValueError):
        _message("error", "projects.error.delete_failed")
        return
    open_document(store, project_id, "")
    _message("success", "projects.document_deleted")


def _on_delete_project(store: ProjectStore, project_id: str, name: str) -> None:
    st.session_state[CONFIRM_DELETE] = False
    try:
        store.delete_project(project_id)
        open_memory_store(st.session_state).delete_project(project_id)  # QA Agent memory goes with the project
    except (OSError, ValueError):
        _message("error", "projects.error.delete_failed")
        return
    st.session_state.get(LAST_DOCUMENT, {}).pop(project_id, None)
    _open_project(store, store.projects()[0].id)
    _message("success", "projects.deleted", name=name)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def _document_label(document: DocumentSummary, lang: str) -> str:
    # Documents saved before projects existed have no title: name them by their first requirement.
    title = document.title or document_title(document.first_requirement)
    title = title or t("projects.untitled", lang, id=document.document_hash[:6])
    return t("projects.document_option", lang, title=title, count=document.requirements)


def render_projects(lang: str, store: ProjectStore) -> None:
    """Sidebar: the open project and document, and a quick "new project" form."""
    projects = store.projects()
    by_id = {p.id: p for p in projects}
    if active_project_id() not in by_id:  # deleted elsewhere, or never chosen
        _open_project(store, projects[0].id)
    project = by_id[active_project_id()]
    st.session_state[ACTIVE] = project.id

    sidebar = st.sidebar
    if message := st.session_state.pop(MESSAGE, None):
        level, key, params = message
        getattr(sidebar, level)(t(key, lang, **params))

    st.session_state[PROJECT_SELECT] = project.id
    sidebar.selectbox(
        t("projects.project", lang), list(by_id),
        format_func=lambda pid: project_name(by_id[pid], lang),
        key=PROJECT_SELECT, on_change=_on_project_change, args=(store,),
    )
    if project.description:
        sidebar.caption(project.description)

    documents = _documents(store, project)
    current = _current_document()
    st.session_state[DOCUMENT_SELECT] = current
    sidebar.selectbox(
        t("projects.document", lang), [*documents, NEW_DOCUMENT],
        format_func=lambda h: t("projects.new_document", lang) if h == NEW_DOCUMENT else _document_label(documents[h], lang),
        key=DOCUMENT_SELECT, on_change=_on_document_change, args=(store, project.id),
        help=t("projects.document_help", lang),
    )
    sidebar.caption(t("projects.document_count", lang, count=len(documents)))

    with sidebar.popover(t("projects.new_heading", lang), icon=":material/create_new_folder:", width="stretch"):
        st.text_input(t("projects.name", lang), key=NEW_NAME, max_chars=80, placeholder=t("projects.name_placeholder", lang))
        st.text_input(t("projects.description", lang), key=NEW_DESCRIPTION, max_chars=500)
        st.button(
            t("projects.create", lang), key="project_create", icon=":material/add:", type="primary",
            on_click=_on_create, args=(store,), width="stretch",
        )


def _documents(store: ProjectStore, project: Project) -> dict[str, DocumentSummary]:
    documents = {d.document_hash: d for d in store.documents(project.id)}
    workspace = st.session_state.get(WORKSPACE)
    if workspace is not None and workspace.document_hash and workspace.document_hash not in documents:
        documents[workspace.document_hash] = summary_of(workspace)  # open, but its save failed
    return documents


def _current_document() -> str:
    workspace = st.session_state.get(WORKSPACE)
    return workspace.document_hash if workspace is not None and workspace.document_hash else NEW_DOCUMENT


def render_project_settings(lang: str, store: ProjectStore) -> None:
    """Settings page: rename the open project, delete the open document or the project."""
    project = next(p for p in store.projects() if p.id == active_project_id())
    current = _current_document()
    st.text_input(t("projects.name", lang), value=project.name, key=f"project_name_{project.id}", max_chars=80)
    st.text_input(
        t("projects.description", lang), value=project.description,
        key=f"project_description_{project.id}", max_chars=500,
    )
    st.button(
        t("projects.save", lang), key="project_save", icon=":material/save:",
        on_click=_on_edit, args=(store, project),
    )
    st.divider()
    st.markdown(f"**{t('ui.settings.danger_zone', lang)}**")
    confirmed = st.checkbox(t("projects.confirm_delete", lang), key=CONFIRM_DELETE)
    cols = st.columns(2)
    cols[0].button(
        t("projects.delete_document", lang), key="project_delete_document", icon=":material/draft:",
        disabled=not confirmed or current == NEW_DOCUMENT,
        on_click=_on_delete_document, args=(store, project.id, current), width="stretch",
    )
    cols[1].button(
        t("projects.delete_project", lang), key="project_delete", icon=":material/delete:",
        disabled=not confirmed, on_click=_on_delete_project,
        args=(store, project.id, project_name(project, lang)), width="stretch",
    )
