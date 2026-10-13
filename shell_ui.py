"""App shell: sidebar navigation, the AI status and the page header.

Navigation is one radio group (`app_mode`) styled as a menu, so the page
choice lives in session state, survives reruns and works with the keyboard
(arrow keys move between pages). Code that wants to change the page uses
`go_to()` (after which it reruns) or `nav_callback` (as a widget callback);
both run before the menu is drawn, as Streamlit requires.
"""

import streamlit as st

import llm_ui
import theme_ui
from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import LANGUAGES, t
from spec_to_test.llm.config import AIConfig, LLMSettings

NAV = "app_mode"
PENDING = "app_mode_pending"
PAGES: dict[str, str] = {
    "home": ":material/space_dashboard:",
    "analysis": ":material/fact_check:",
    "grill": ":material/forum:",
    "tests": ":material/checklist:",
    "rtm": ":material/account_tree:",
    "dashboard": ":material/monitoring:",
    "export": ":material/ios_share:",
    "settings": ":material/settings:",
}


def go_to(page: str) -> None:
    """Open `page` on the next run (call st.rerun() afterwards)."""
    st.session_state[PENDING] = page


def nav_callback(page: str) -> None:
    """Widget callback that opens `page`."""
    st.session_state[NAV] = page


def apply_pending() -> None:
    if (page := st.session_state.pop(PENDING, None)) in PAGES:
        st.session_state[NAV] = page


def page_title(page: str, lang: str) -> str:
    return t(f"ui.page.{page}", lang)


def render_brand(lang: str) -> None:
    with st.sidebar:
        theme_ui.brand(t("ui.tagline", lang))


def render_nav(lang: str) -> str:
    with st.sidebar:
        theme_ui.nav_label(t("ui.nav.heading", lang))
        page = st.radio(
            t("ui.nav.heading", lang), list(PAGES), key=NAV, label_visibility="collapsed", width="stretch",
            format_func=lambda p: f"{PAGES[p]} {page_title(p, lang)}",
        )
    return str(page or "home")


def render_sidebar_footer(lang: str, settings: LLMSettings, config: AIConfig | None) -> str:
    """AI status, storage note, language and version. Returns the chosen language."""
    sidebar = st.sidebar
    state = llm_ui.status(lang, settings, config)
    with sidebar.container(key="sidebar_status"):
        st.markdown(theme_ui.badge(state.label, state.tone, state.icon))
        if config is not None:
            st.caption(f"{escape_markdown(config.provider_name)} · {escape_markdown(config.model)}")
        else:
            st.caption(state.detail)
    current = st.session_state.get("language", "en")
    lang = sidebar.selectbox(
        t("sidebar.language", current), options=list(LANGUAGES), format_func=lambda code: LANGUAGES[code],
        key="language",
    ) or "en"
    return lang


def render_header(
    page: str, lang: str, settings: LLMSettings, config: AIConfig | None, subtitle: str | None = None
) -> None:
    """Title, subtitle, AI status with a quick provider/model switcher, and a Settings shortcut."""
    state = llm_ui.status(lang, settings, config)
    with st.container(key="page_header"):
        left, right = st.columns([3, 2], vertical_alignment="center", gap="medium")
        with left:
            st.title(page_title(page, lang), anchor=False)
            st.caption(subtitle or t(f"ui.page.{page}.subtitle", lang))
        with right, st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center",
                                 key="header_actions"):
            st.markdown(theme_ui.badge(state.label, state.tone, state.icon), help=state.detail)
            if page != "settings" and settings.enabled:
                label = config.model if config is not None else t("ui.ai.rule_based", lang)
                with st.popover(label, icon=":material/tune:", help=t("ui.header.ai_help", lang)):
                    llm_ui.render_controls(lang, settings)
            st.button(
                t("ui.header.settings", lang), key="header_settings", icon=":material/settings:",
                on_click=nav_callback, args=("settings",), disabled=page == "settings",
            )
