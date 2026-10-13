"""Design tokens and scoped CSS (theme_ui.py) stay consistent with Streamlit's theme."""

import re
import tomllib

import theme_ui
from conftest import PROJECT_ROOT

CONFIG = tomllib.loads((PROJECT_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))


def test_streamlit_theme_uses_the_design_tokens():
    theme, sidebar = CONFIG["theme"], CONFIG["theme"]["sidebar"]
    tokens = theme_ui.TOKENS
    assert theme["primaryColor"] == tokens["accent"]
    assert theme["backgroundColor"] == tokens["bg"]
    assert theme["textColor"] == tokens["text"]
    assert theme["borderColor"] == tokens["border"]
    assert sidebar["backgroundColor"] == tokens["nav-bg"]
    assert sidebar["secondaryBackgroundColor"] == tokens["nav-raised"]
    assert sidebar["textColor"] == tokens["nav-text"]
    assert sidebar["primaryColor"] == tokens["accent-on-dark"]


def test_every_token_is_a_css_variable_and_every_variable_used_exists():
    css = theme_ui.CSS % {"variables": theme_ui._variables()}
    used = set(re.findall(r"var\(--stt-([a-z-]+)\)", css))
    assert used <= set(theme_ui.TOKENS), used - set(theme_ui.TOKENS)


def test_css_is_scoped_to_streamlit_elements_or_keyed_containers():
    css = re.sub(r"/\*.*?\*/", "", theme_ui.CSS, flags=re.S)
    css = re.sub(r"@media[^{]+\{", "", css)
    selectors = [s.strip() for block in re.findall(r"([^{}]+)\{", css) for s in block.split(",")]
    allowed = ("[data-testid=", ".st-key-", "[class*=\"st-key-", ".stt-", ":root", ":focus-visible",
               ".stButton", ".stFormSubmitButton")
    unscoped = [s for s in selectors if s and not s.startswith(allowed)]
    assert not unscoped, unscoped


def test_badges_show_user_text_literally():
    assert theme_ui.badge("REQ-1", "info") == ":blue-badge[REQ-1]"
    assert theme_ui.badge("a [link](x) *b*", "danger") == r":red-badge[a \(link\)(x) \*b\*]"
    assert theme_ui.badge("x", "unknown-tone").startswith(":gray-badge[")


def test_focus_is_visible_and_navigation_keeps_a_keyboard_outline():
    assert ":focus-visible { outline: 2px solid var(--stt-focus)" in theme_ui.CSS
    assert ":has(input:focus-visible)" in theme_ui.CSS
