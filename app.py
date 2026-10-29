"""Streamlit entry point. Run with: streamlit run app.py

The shell (sidebar navigation, header, AI status) is in shell_ui.py, the design
system in theme_ui.py, Grill Mode in grill_ui.py and every other page in
pages_ui.py. This file wires them together: settings, the open project and
document, the AI configuration of this browser session, and which page to draw.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

# Make the `src/` package (and the *_ui.py pages next to this file) importable without installing it.
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import llm_ui  # noqa: E402
import pages_ui  # noqa: E402
import shell_ui  # noqa: E402
import theme_ui  # noqa: E402
from grill_ui import render_grill  # noqa: E402
from projects_ui import active_project_id, keep_input, render_projects, restore_last_opened  # noqa: E402
from spec_to_test import __version__  # noqa: E402
from spec_to_test.formatting import escape_markdown  # noqa: E402
from spec_to_test.i18n import t  # noqa: E402
from spec_to_test.llm.config import load_settings  # noqa: E402
from spec_to_test.models import Workspace  # noqa: E402
from spec_to_test.projects import ProjectStore, open_store  # noqa: E402
from spec_to_test.storage import WorkspaceConflict, persistence_enabled  # noqa: E402

st.set_page_config(page_title="Spec-to-Test", page_icon="🧪", layout="wide", initial_sidebar_state="auto")
theme_ui.inject()


CONFLICTS_KEY = "save_conflicts"


@dataclass(frozen=True)
class SaveConflict:
    """Edits the saved document did not take. Kept in the session and in a copy on disk."""

    workspace: Workspace
    copy: str  # where the copy was written; "" when that failed (the edits then live in this session only)


def conflicts() -> dict[tuple[str, str], SaveConflict]:
    """(project id, document hash) -> SaveConflict, for documents changed elsewhere since they were opened."""
    if CONFLICTS_KEY not in st.session_state:
        st.session_state[CONFLICTS_KEY] = {}
    return st.session_state[CONFLICTS_KEY]


def persist(ws: Workspace) -> None:
    """Keep the session and the project's copy (on disk in "local" mode) in sync after every edit."""
    st.session_state["workspace"] = ws
    project_id = active_project_id()
    try:
        store.save(project_id, ws)
    except WorkspaceConflict:
        # Changed elsewhere (another tab or the QA on-change run). Nothing is replaced and nothing is dropped:
        # the edit stays in this session and in a copy on disk until the user chooses which version to keep.
        copy = ""
        try:
            copy = store.keep_unsaved(project_id, ws)
        except (OSError, ValueError):
            pages_ui.flash(t("storage.save_failed", lang), icon="⚠️")
        conflicts()[(project_id, ws.document_hash)] = SaveConflict(workspace=ws, copy=copy)
        pages_ui.flash(t("storage.changed_elsewhere", lang), icon="⚠️")
    except (OSError, ValueError):
        pages_ui.flash(t("storage.save_failed", lang), icon="⚠️")


def _where(conflict: SaveConflict, lang: str) -> str:
    return conflict.copy or t("storage.conflict.where_session", lang)


def overwrite_conflict(store: ProjectStore, lang: str, key: tuple[str, str]) -> None:
    """Save the user's version over the saved file; the replaced copy is kept on disk."""
    conflict = conflicts().get(key)
    if conflict is None:
        return
    try:
        replaced = store.overwrite(key[0], conflict.workspace)
    except (OSError, ValueError):
        pages_ui.flash(t("storage.save_failed", lang), icon="⚠️")
        return
    del conflicts()[key]
    if replaced:
        pages_ui.flash(t("storage.conflict.overwritten", lang, path=replaced), icon="✅")
    else:
        pages_ui.flash(t("storage.conflict.saved", lang), icon="✅")


def load_conflict(store: ProjectStore, lang: str, key: tuple[str, str]) -> None:
    """Show the saved version; the user's edits stay in their copy, so nothing is dropped."""
    conflict = conflicts().get(key)
    if conflict is None:
        return
    saved = store.load(key[0], key[1])
    if saved is None:
        pages_ui.flash(t("storage.conflict.unreadable", lang, where=_where(conflict, lang)), icon="⚠️")
        return
    del conflicts()[key]
    current = st.session_state.get("workspace")
    if current is not None and current.document_hash == key[1] and key[0] == active_project_id():
        st.session_state["workspace"] = saved
    pages_ui.flash(t("storage.conflict.loaded", lang, where=_where(conflict, lang)), icon="✅")


def render_conflicts(lang: str, store: ProjectStore) -> None:
    """One notice per document whose edits were not saved, with the two ways out."""
    for key, conflict in conflicts().items():
        project_id, doc_hash = key
        title = escape_markdown(conflict.workspace.title or doc_hash)
        with st.container(border=True):
            st.warning(
                t("storage.conflict.text", lang, title=title, where=escape_markdown(_where(conflict, lang))),
                icon="⚠️",
            )
            overwrite_col, load_col = st.columns(2)
            overwrite_col.button(
                t("storage.conflict.overwrite", lang), key=f"conflict_overwrite_{project_id}_{doc_hash}",
                icon=":material/save:", width="stretch", on_click=overwrite_conflict, args=(store, lang, key),
            )
            load_col.button(
                t("storage.conflict.load", lang), key=f"conflict_load_{project_id}_{doc_hash}",
                icon=":material/history:", width="stretch", on_click=load_conflict, args=(store, lang, key),
            )


# --- Settings and state ----------------------------------------------------
# Root-level secrets (Streamlit Cloud or .streamlit/secrets.toml) become environment
# variables, which is where the AI and storage settings are read from.
secrets_error = False
try:
    st.secrets.load_if_toml_exists()
except Exception:  # noqa: BLE001 - a malformed secrets file must not break the app
    secrets_error = True

llm_ui.keep_state()  # AI choices and typed requirements survive pages that do not show them
keep_input()
shell_ui.apply_pending()
lang: str = st.session_state.get("language", "en")
# Which LLM this browser session uses (None = rule-based only). Keys come from the
# environment / secrets / .env, never from the page.
llm_settings = load_settings()
# One usage ledger for the whole running app: the operator's key and budget are shared by every session.
usage = llm_ui.usage_ledger(llm_settings.budget)
for provider_config in llm_settings.configs.values():
    provider_config.ledger = usage
ai_config = llm_ui.resolve(llm_settings)
# The Automation agent loop is built on Claude's tool use, so it always uses Claude
# (when this session has AI on and a Claude key is configured).
automation_ai = ai_config if ai_config is None or ai_config.provider == "anthropic" else llm_settings.configs.get("anthropic")

# --- Sidebar ---------------------------------------------------------------
shell_ui.render_brand(lang)
# Projects hold the analyzed documents: on disk in "local" mode, else only in this session.
store = open_store(st.session_state)
restore_last_opened(store)
render_projects(lang, store)
page = shell_ui.render_nav(lang)
lang = shell_ui.render_sidebar_footer(lang, llm_settings, ai_config)
st.sidebar.caption(t("sidebar.storage" if persistence_enabled() else "sidebar.storage_session", lang))
llm_ui.render_usage(lang, usage)
if secrets_error:
    st.sidebar.warning(t("sidebar.secrets_invalid", lang))
st.sidebar.caption(t("sidebar.version", lang, version=__version__))

# --- Page ------------------------------------------------------------------
shell_ui.render_header(page, lang, llm_settings, ai_config)
pages_ui.show_flash()
# The notice sits above the page but is drawn after it: a save on this run can find a conflict.
conflict_notice = st.container()
context = pages_ui.Page(lang=lang, store=store, persist=persist, ai_config=ai_config, automation_ai=automation_ai)
if page == "grill":
    render_grill(lang, st.session_state.get("workspace"), ai_config, persist)
elif page == "settings":
    pages_ui.settings(context, llm_settings)
else:
    getattr(pages_ui, page)(context)
with conflict_notice:
    render_conflicts(lang, store)
