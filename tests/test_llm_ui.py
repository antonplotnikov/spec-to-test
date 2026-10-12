"""AI settings in the sidebar (AppTest; no request reaches a real provider)."""

import pytest
from streamlit.testing.v1 import AppTest
from test_grill_ui import grill, new_app

import automation_ui
import llm_ui
from spec_to_test.i18n import LANGUAGES, t
from spec_to_test.llm.providers import AIError
from test_localization import raw_keys, visible_text

CLAUDE_KEY = "test-key-123"
OPENAI_KEY = "oa-key-456"


@pytest.fixture
def two_providers(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", CLAUDE_KEY)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)


def ai_tab_text(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def analyzed(example_text: str) -> AppTest:
    at = new_app()
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
    assert not at.exception
    return at


# --- Without AI ------------------------------------------------------------------------------------

def test_without_ai_the_sidebar_only_explains_setup():
    at = new_app()
    assert any(t("llm.not_configured") in c.value for c in at.sidebar.caption)
    assert not at.sidebar.toggle and len(at.sidebar.selectbox) == 1  # only the language picker
    assert at.sidebar.info[0].value == t("sidebar.privacy")


def test_unusable_default_provider_is_reported(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")  # no OPENAI_API_KEY
    at = new_app()
    assert any("OPENAI_API_KEY" in c.value for c in at.sidebar.caption)
    assert at.sidebar.info[0].value == t("sidebar.privacy")  # AI stays off


# --- Choosing a provider and model -------------------------------------------------------------------

def test_default_provider_is_used(two_providers, example_text):
    at = analyzed(example_text)
    assert at.sidebar.toggle(key="llm_enabled").value is True
    assert at.sidebar.selectbox(key="llm_provider").options == ["Claude (Anthropic)", "OpenAI"]
    assert at.sidebar.info[0].value == t("sidebar.privacy_ai")
    assert "Claude (Anthropic)" in ai_tab_text(at) and "claude-opus-5-5" in ai_tab_text(at)


def test_switching_provider_and_model_applies_to_this_session(two_providers, example_text):
    at = analyzed(example_text)
    at.sidebar.selectbox(key="llm_provider").set_value("openai").run()
    assert at.sidebar.text_input(key="llm_model_openai").value == "gpt-5"
    at.sidebar.text_input(key="llm_model_openai").input("gpt-5-mini").run()
    assert "OpenAI" in ai_tab_text(at) and "gpt-5-mini" in ai_tab_text(at)

    other = analyzed(example_text)  # another browser session keeps the operator's default
    assert "Claude (Anthropic)" in ai_tab_text(other)


def test_invalid_model_falls_back_to_the_configured_one(two_providers, example_text):
    at = analyzed(example_text)
    at.sidebar.text_input(key="llm_model_anthropic").input("bad model; rm -rf").run()
    assert any(t("llm.model_invalid", model="claude-opus-5-5") == w.value for w in at.sidebar.warning)
    assert "claude-opus-5-5" in ai_tab_text(at)


def test_turning_ai_off_is_the_rule_based_mode(two_providers, example_text):
    at = analyzed(example_text)
    at.sidebar.toggle(key="llm_enabled").set_value(False).run()
    assert at.sidebar.info[0].value == t("sidebar.privacy")
    assert any(t("llm.fallback") == c.value for c in at.sidebar.caption)
    assert any(t("ai.not_configured") == i.value for i in at.info)  # AI tab
    assert not any(c.key == "ai_consent" for c in at.checkbox)
    at = grill(at)
    assert any(t("grill.ui.mode_deterministic") in i.value for i in at.info)


def test_locked_settings_show_but_do_not_offer_changes(two_providers, monkeypatch, example_text):
    monkeypatch.setenv("AI_LOCK_SETTINGS", "true")
    at = analyzed(example_text)
    assert not [s for s in at.sidebar.selectbox if s.key == "llm_provider"]
    assert not at.sidebar.text_input
    assert any(t("llm.locked") == c.value for c in at.sidebar.caption)
    assert at.sidebar.toggle(key="llm_enabled").value is True  # turning AI off stays possible


def test_ollama_needs_no_key(monkeypatch, example_text):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    at = analyzed(example_text)
    assert "Ollama" in ai_tab_text(at) and "qwen3:8b" in ai_tab_text(at)
    assert any("http://localhost:11434" in c.value for c in at.sidebar.caption)


# --- Keys ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_keys_are_never_shown_and_settings_are_translated(two_providers, example_text, lang):
    at = analyzed(example_text)
    at.sidebar.selectbox[0].select(lang).run()
    texts = visible_text(at) + [str(c.value) for c in at.sidebar.caption]
    joined = "\n".join(texts)
    assert CLAUDE_KEY not in joined and OPENAI_KEY not in joined
    assert "ANTHROPIC_API_KEY" in joined  # where the key comes from is shown, not the key
    assert not raw_keys(texts)
    assert not any(CLAUDE_KEY in str(v) or OPENAI_KEY in str(v) for v in at.session_state.values())


# --- Connection test -------------------------------------------------------------------------------------

def test_connection_test_success_and_failure(two_providers, monkeypatch):
    calls = []
    outcome: dict = {"error": None}

    def fake_check(config):
        calls.append((config.provider, config.model))
        if outcome["error"]:
            raise AIError(outcome["error"])

    monkeypatch.setattr(llm_ui, "check_connection", fake_check)
    at = new_app()
    at.sidebar.button(key="llm_test").click().run()
    assert calls == [("anthropic", "claude-opus-5-5")]
    assert at.sidebar.success[0].value == t("llm.test_ok", model="claude-opus-5-5")

    outcome["error"] = "auth"
    at.sidebar.selectbox(key="llm_provider").set_value("openai").run()
    assert not at.sidebar.success  # the earlier result was for another provider
    at.sidebar.button(key="llm_test").click().run()
    assert at.sidebar.error[0].value == t("ai.error.auth")


# --- Automation always uses Claude ---------------------------------------------------------------------------

def test_automation_gets_claude_even_when_openai_is_selected(two_providers, monkeypatch, example_text):
    seen = []
    monkeypatch.setattr(automation_ui, "render_automation", lambda lang, ws, ai, persist: seen.append(ai))
    at = analyzed(example_text)
    at.sidebar.selectbox(key="llm_provider").set_value("openai").run()
    assert seen[-1] is not None and seen[-1].provider == "anthropic"
    at.sidebar.toggle(key="llm_enabled").set_value(False).run()
    assert seen[-1] is None  # AI off means no automation agent either
