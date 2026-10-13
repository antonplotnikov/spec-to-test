"""Streamlit entry point. Run with: streamlit run app.py

The shell (sidebar navigation, header, AI status) is in shell_ui.py, the design
system in theme_ui.py, Grill Mode in grill_ui.py and every other page in
pages_ui.py. This file wires them together: settings, the open project and
document, the AI configuration of this browser session, and which page to draw.
"""

import sys
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
from spec_to_test.i18n import t  # noqa: E402
from spec_to_test.llm.config import load_settings  # noqa: E402
from spec_to_test.models import Workspace  # noqa: E402
from spec_to_test.projects import open_store  # noqa: E402
from spec_to_test.storage import persistence_enabled  # noqa: E402

st.set_page_config(page_title="Spec-to-Test", page_icon="🧪", layout="wide", initial_sidebar_state="auto")
theme_ui.inject()


def persist(ws: Workspace) -> None:
    """Keep the session and the project's copy (on disk in "local" mode) in sync after every edit."""
    st.session_state["workspace"] = ws
    try:
        store.save(active_project_id(), ws)
    except (OSError, ValueError):
        pages_ui.flash(t("storage.save_failed", lang), icon="⚠️")


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
if secrets_error:
    st.sidebar.warning(t("sidebar.secrets_invalid", lang))
st.sidebar.caption(t("sidebar.version", lang, version=__version__))

# --- Page ------------------------------------------------------------------
shell_ui.render_header(page, lang, llm_settings, ai_config)
pages_ui.show_flash()
context = pages_ui.Page(lang=lang, store=store, persist=persist, ai_config=ai_config, automation_ai=automation_ai)
if page == "grill":
    render_grill(lang, st.session_state.get("workspace"), ai_config, persist)
elif page == "settings":
    pages_ui.settings(context, llm_settings)
else:
    getattr(pages_ui, page)(context)
