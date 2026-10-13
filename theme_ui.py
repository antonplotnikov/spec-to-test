"""Design system for the Streamlit app: tokens, scoped CSS and small components.

Colors, radii and shadows are defined once in TOKENS and exposed to CSS as
`--stt-*` custom properties; .streamlit/config.toml holds the same base colors
for Streamlit's own theme (kept in sync by tests/test_theme.py).

All CSS is scoped to Streamlit test IDs or to `st-key-*` classes of keyed
containers, so it never leaks into widgets it was not written for. Components
render native Streamlit elements (metrics, progress bars, Markdown badges), so
text stays readable by screen readers and by AppTest; raw HTML is used only for
decoration that carries no information of its own.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from html import escape

import streamlit as st

from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import t
from spec_to_test.quality import DIMENSIONS, QualityScore, average_score, dimension_scores, grade_of

TOKENS: dict[str, str] = {
    # Workspace
    "bg": "#F4F6FB",
    "surface": "#FFFFFF",
    "surface-muted": "#F8F9FC",
    "border": "#E2E7F0",
    "border-strong": "#CDD5E3",
    "text": "#121933",
    "text-muted": "#58627F",
    # Blue-violet accent
    "accent": "#5B50E6",
    "accent-strong": "#4A3FD0",
    "accent-soft": "#EFEEFE",
    "accent-on-dark": "#A49EFF",
    "focus": "#7C74FF",
    # Sidebar
    "nav-bg": "#0D1431",
    "nav-raised": "#172046",
    "nav-border": "#242E5C",
    "nav-text": "#C9D0E8",
    "nav-muted": "#8D96BC",
    "nav-active": "rgba(124, 116, 255, 0.18)",
    # Status
    "success": "#0F7A55",
    "success-soft": "#E5F5EE",
    "warning": "#9A5B06",
    "warning-soft": "#FDF3E0",
    "danger": "#BE2B2B",
    "danger-soft": "#FCEBEB",
    "info": "#2457C5",
    "info-soft": "#EAF1FD",
    "neutral": "#58627F",
    "neutral-soft": "#EEF1F6",
    # Shape
    "radius-sm": "8px",
    "radius": "12px",
    "radius-lg": "16px",
    "shadow-sm": "0 1px 2px rgba(16, 24, 40, 0.05)",
    "shadow": "0 1px 2px rgba(16, 24, 40, 0.04), 0 6px 16px -8px rgba(16, 24, 40, 0.10)",
}

# Markdown badge colors for each tone (Streamlit's own palette, readable on light and dark).
TONES = {
    "success": "green", "warning": "orange", "danger": "red", "info": "blue",
    "accent": "violet", "neutral": "gray",
}
GRADE_TONES = {"good": "success", "fair": "warning", "poor": "danger"}


def _variables() -> str:
    return "\n".join(f"  --stt-{name}: {value};" for name, value in TOKENS.items())


CSS = """
:root {
%(variables)s
}

/* ---- Page frame -------------------------------------------------------- */
[data-testid="stMain"] .block-container {
  max-width: min(100%%, 1680px);
  padding: 4rem clamp(1rem, 2.6vw, 2.5rem) 3rem;
}
[data-testid="stHeader"] { background: var(--stt-bg); }
:focus-visible { outline: 2px solid var(--stt-focus) !important; outline-offset: 2px; }

/* ---- Sidebar (dark navy; colors of its widgets come from [theme.sidebar]) - */
[data-testid="stSidebar"] { border-right: 1px solid var(--stt-nav-border); }
[data-testid="stSidebarUserContent"] { padding-top: 0.25rem; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color: var(--stt-nav-muted); }
.stt-brand { display: flex; align-items: center; gap: 0.7rem; padding: 0.15rem 0 0.35rem; }
.stt-brand-mark {
  width: 36px; height: 36px; border-radius: 10px; flex: none;
  display: grid; place-items: center; color: #fff; font-weight: 700; font-size: 0.95rem;
  background: linear-gradient(135deg, var(--stt-accent) 0%%, #7B5CF0 100%%);
  box-shadow: 0 4px 14px -6px rgba(124, 116, 255, 0.8);
}
.stt-brand-name { color: #fff; font-weight: 700; font-size: 1.05rem; letter-spacing: -0.01em; line-height: 1.2; }
.stt-brand-tagline { color: var(--stt-nav-muted); font-size: 0.78rem; line-height: 1.3; }
.stt-nav-label {
  color: var(--stt-nav-muted); font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; margin: 0.4rem 0 -0.4rem;
}

/* Navigation: a radio group styled as a menu (keeps arrow-key navigation). */
.st-key-app_mode [data-testid="stRadioGroup"] { gap: 2px; width: 100%%; }
.st-key-app_mode [data-testid="stRadioGroup"] > div { width: 100%%; }
.st-key-app_mode [data-testid="stRadioOption"] {
  width: 100%%; margin: 0; padding: 0.5rem 0.7rem; border-radius: var(--stt-radius-sm);
  color: var(--stt-nav-text); cursor: pointer; transition: background-color 0.12s ease;
}
.st-key-app_mode [data-testid="stRadioOption"] > div > div:first-child { display: none; }
.st-key-app_mode [data-testid="stRadioOption"] p { font-size: 0.92rem; font-weight: 500; }
.st-key-app_mode [data-testid="stRadioOption"] [role="img"] { margin-right: 0.45rem; opacity: 0.85; }
.st-key-app_mode [data-testid="stRadioOption"]:hover { background: rgba(255, 255, 255, 0.05); color: #fff; }
.st-key-app_mode [data-testid="stRadioOption"][data-selected="true"] {
  background: var(--stt-nav-active); color: #fff; box-shadow: inset 3px 0 0 var(--stt-accent-on-dark);
}
.st-key-app_mode [data-testid="stRadioOption"][data-selected="true"] [role="img"] { color: var(--stt-accent-on-dark); opacity: 1; }
.st-key-app_mode [data-testid="stRadioOption"]:has(input:focus-visible) {
  outline: 2px solid var(--stt-accent-on-dark); outline-offset: 1px;
}
.st-key-sidebar_status {
  background: var(--stt-nav-raised); border: 1px solid var(--stt-nav-border);
  border-radius: var(--stt-radius); padding: 0.7rem 0.8rem;
}
.st-key-sidebar_status p { color: var(--stt-nav-text); }
.st-key-sidebar_status .stMarkdownBadge { white-space: normal; }

/* ---- Header ----------------------------------------------------------- */
.st-key-page_header { padding-bottom: 0.9rem; margin-bottom: 0.35rem; border-bottom: 1px solid var(--stt-border); }
.st-key-page_header h1 { font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; padding: 0; }
.st-key-page_header [data-testid="stCaptionContainer"] p { font-size: 0.95rem; color: var(--stt-text-muted); }
.st-key-header_actions { justify-content: flex-end; }

/* ---- Cards: keyed containers whose key starts with "card" -------------- */
[class*="st-key-card"] {
  background: var(--stt-surface); border: 1px solid var(--stt-border) !important;
  border-radius: var(--stt-radius-lg); box-shadow: var(--stt-shadow);
}
[class*="st-key-card"] h4, [class*="st-key-card"] h5 { padding-top: 0; letter-spacing: -0.01em; }
[class*="st-key-card"] h4 { font-size: 1.12rem; font-weight: 650; }
[class*="st-key-card"] h5 { font-size: 0.98rem; font-weight: 600; }
[class*="st-key-card"] h5 [role="img"], [class*="st-key-card"] h4 [role="img"] { color: var(--stt-accent); }
.st-key-card_question { border: 1px solid #CFCBFB !important; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 10px 24px -14px rgba(91, 80, 230, 0.45); }
.st-key-card_question [data-testid="stMarkdownContainer"] h3 { font-size: 1.22rem; line-height: 1.45; font-weight: 650; padding: 0.15rem 0 0.1rem; }
.st-key-card_requirement { background: var(--stt-surface-muted); }
.st-key-card_requirement blockquote {
  border-left: 3px solid var(--stt-accent); margin: 0.2rem 0 0.4rem; padding: 0.1rem 0 0.1rem 0.85rem;
  color: var(--stt-text);
}

/* Metrics as KPI cards */
[data-testid="stMetric"] {
  background: var(--stt-surface); border-radius: var(--stt-radius); box-shadow: var(--stt-shadow-sm);
  padding: 0.6rem 0.85rem;
}
[data-testid="stMetricLabel"] p {
  white-space: normal; overflow-wrap: normal; word-break: normal; hyphens: auto;
  color: var(--stt-text-muted); font-weight: 500; font-size: 0.85rem;
}
[data-testid="stMetricValue"] { font-weight: 700; color: var(--stt-text); font-size: 1.75rem; }
[data-testid="stMetricLabel"] { max-width: 100%%; width: 100%%; }
[data-testid="stMetricLabel"] [data-testid="stMarkdownContainer"] {
  overflow: visible !important; text-overflow: clip !important; white-space: normal !important;
}
[class*="st-key-kpi_"] [data-testid="stMetric"] { border: 1px solid var(--stt-border); }
[class*="st-key-kpi_score"] [data-testid="stMetric"] { box-shadow: none; padding: 0; background: transparent; border: 0; }
.st-key-kpi_confirmed [data-testid="stMetricValue"] { color: var(--stt-success); }
.st-key-kpi_assumptions [data-testid="stMetricValue"] { color: var(--stt-warning); }
.st-key-kpi_unknowns [data-testid="stMetricValue"] { color: var(--stt-neutral); }
.st-key-kpi_conflicts [data-testid="stMetricValue"] { color: var(--stt-danger); }
[class*="st-key-kpi_score"] [data-testid="stMetricValue"] { color: var(--stt-accent); font-size: 2.2rem; }

/* Tabs */
[data-testid="stTabs"] [role="tablist"] { gap: 0.25rem; border-bottom: 1px solid var(--stt-border); }
[data-testid="stTab"] { padding: 0.45rem 0.8rem; }
[data-testid="stTab"] p { font-weight: 500; }
[data-testid="stTab"][aria-selected="true"] p { color: var(--stt-accent); font-weight: 600; }

/* Progress bars */
[data-testid="stProgress"] p { font-size: 0.85rem; color: var(--stt-text-muted); }

/* Tables */
[data-testid="stTable"] td { vertical-align: top; white-space: pre-wrap; }
[data-testid="stTable"] tbody td:first-child, [data-testid="stTable"] tbody td:first-child * { white-space: nowrap; }
/* Grill tables start with a question or a field, not an ID: let it wrap. */
.st-key-card_grill_previous [data-testid="stTable"] tbody td:first-child,
.st-key-card_grill_previous [data-testid="stTable"] tbody td:first-child * { white-space: pre-wrap; min-width: 14rem; }

/* Expanders */
[data-testid="stExpander"] details { background: var(--stt-surface); border-radius: var(--stt-radius); }

/* Buttons */
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] { font-weight: 600; }
.st-key-analyze button { padding: 0.55rem 2.25rem; }

/* Empty states */
[class*="st-key-empty_"] { padding: 1.25rem 1.25rem 1rem; background: var(--stt-surface-muted); border-style: dashed !important; }

/* List items (list_item): one record per row, badges first */
[class*="st-key-item_"] { padding: 0.15rem 0 0.35rem; border-bottom: 1px solid var(--stt-border); }
[class*="st-key-item_"]:last-child { border-bottom: 0; }

/* Saved interviews and save status */
[class*="st-key-grill_saved_"] { background: var(--stt-surface-muted); border-radius: var(--stt-radius); }
[class*="st-key-grill_saved_"] p strong { overflow-wrap: anywhere; }
.st-key-grill_save_controls { flex-wrap: wrap; gap: 0.5rem; }
.st-key-finding_actions { flex-wrap: wrap; gap: 0.5rem; }
.st-key-card_finding_changes { border-left: 3px solid var(--stt-accent) !important; }

/* Respect a reduced-motion preference */
@media (prefers-reduced-motion: reduce) {
  .st-key-app_mode [data-testid="stRadioOption"] { transition: none; }
  [data-testid="stProgress"] div { transition: none !important; }
}

/* ---- Small screens: everything stacks; keep things inside the viewport -- */
@media (max-width: 640px) {
  [data-testid="stMain"] .block-container { padding: 4rem 0.85rem 2rem; }
  .st-key-page_header h1 { font-size: 1.3rem; }
  .st-key-card_question [data-testid="stMarkdownContainer"] h3 { font-size: 1.08rem; }
}
"""


def inject() -> None:
    """Add the design system's CSS to the page (once per run)."""
    st.html(f"<style>{CSS % {'variables': _variables()}}</style>")


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def badge(text: str, tone: str = "neutral", icon: str = "") -> str:
    """Markdown for a small colored label; `text` is shown literally."""
    safe = escape_markdown(text).replace("[", "(").replace("]", ")")
    prefix = f"{icon} " if icon else ""
    return f":{TONES.get(tone, 'gray')}-badge[{prefix}{safe}]"


def badges(*items: str) -> None:
    """One line of badges built with `badge()` (empty items are left out)."""
    line = " ".join(item for item in items if item)
    if line:
        st.markdown(line)


def brand(tagline: str) -> None:
    st.html(
        '<div class="stt-brand"><div class="stt-brand-mark" aria-hidden="true">ST</div>'
        f'<div><div class="stt-brand-name">Spec-to-Test</div><div class="stt-brand-tagline">{escape(tagline)}</div></div></div>'
    )


def nav_label(text: str) -> None:
    st.html(f'<div class="stt-nav-label">{escape(text)}</div>')


@contextmanager
def card(key: str, *, border: bool = True) -> Iterator[None]:
    """A white, rounded card. The key must be unique on the page."""
    with st.container(border=border, key=f"card_{key}"):
        yield


def section(title: str, icon: str = "", caption: str = "") -> None:
    st.markdown(f"##### {icon + ' ' if icon else ''}{title}")
    if caption:
        st.caption(caption)


def empty_state(title: str, body: str, icon: str = ":material/inbox:", key: str = "page") -> None:
    with st.container(border=True, key=f"empty_{key}"):
        st.markdown(f"#### {icon} {title}")
        st.caption(body)


def list_item(key: str, badges_md: list[str], text: str = "", caption: str = "") -> None:
    """One row of a list: badges (built with `badge()`), literal text and an optional caption.

    Keeps lists of findings, assumptions, open questions and saved work looking the same
    everywhere; `text` and `caption` are escaped, so user input shows exactly as written.
    """
    with st.container(key=f"item_{key}"):
        line = " ".join(b for b in badges_md if b)
        if text:
            line = f"{line} {escape_markdown(text)}" if line else escape_markdown(text)
        if line:
            st.markdown(line)
        if caption:
            st.caption(escape_markdown(caption))


def score_bars(items: list[tuple[str, int]]) -> None:
    """Labeled bars: (label, percent 0-100)."""
    for label, percent in items:
        st.progress(max(0, min(percent, 100)) / 100, text=f"{label} · {percent}%")


def quality_card(lang: str, scores: list[QualityScore], key: str, caption: str = "") -> None:
    """Overall quality and its four dimensions, from the explainable quality score."""
    with card(key):
        section(t("ui.quality.heading", lang), ":material/grading:")
        overall = average_score(scores)
        if overall is None:
            st.caption(t("ui.quality.none", lang))
            return
        grade = grade_of(overall)
        with st.container(key=f"kpi_score_{key}"):
            st.metric(t("ui.quality.score", lang), f"{overall}/100", help=t("quality.explainer", lang))
        badges(badge(t(f"grade.{grade}", lang), GRADE_TONES[grade]),
               badge(t("ui.quality.scope", lang, count=len(scores)), "neutral"))
        score_bars([(t(f"ui.dimension.{d.key}", lang), d.percent) for d in dimension_scores(scores)])
        st.caption(caption or t("ui.quality.dimensions_help", lang, **{
            dim: ", ".join(t(f"criterion.{c}", lang) for c in criteria) for dim, criteria in DIMENSIONS.items()
        }))
