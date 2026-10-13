"""AI settings: header popover, Settings page and status (AppTest; no request reaches a real provider)."""

import pytest
from streamlit.testing.v1 import AppTest
from test_grill_ui import grill, new_app

import automation_ui
import llm_ui
from conftest import goto, home
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
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    return at


# --- Without AI ------------------------------------------------------------------------------------

def settings_text(at: AppTest) -> list[str]:
    goto(at, "settings")
    return [c.value for c in at.caption]


def test_without_ai_the_settings_only_explain_setup():
    at = new_app()
    assert not at.toggle  # no AI switch anywhere
    assert [s.key for s in at.sidebar.selectbox if not s.key.startswith("project_")] == ["language"]
    assert any(t("ui.ai.rule_based") in m.value for m in at.sidebar.markdown)  # sidebar status
    assert any(t("llm.not_configured") in c for c in settings_text(at))
    assert at.info[0].value == t("sidebar.privacy")


def test_unusable_default_provider_is_reported(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")  # no OPENAI_API_KEY
    at = new_app()
    assert any("OPENAI_API_KEY" in c for c in settings_text(at))
    assert at.info[0].value == t("sidebar.privacy")  # AI stays off


# --- Choosing a provider and model -------------------------------------------------------------------

def test_default_provider_is_used(two_providers, example_text):
    at = analyzed(example_text)
    assert at.toggle(key="llm_enabled").value is True  # in the header's AI popover
    assert at.selectbox(key="llm_provider").options == ["Claude (Anthropic)", "OpenAI"]
    assert "Claude (Anthropic)" in ai_tab_text(at) and "claude-opus-5-5" in ai_tab_text(at)
    goto(at, "settings")
    assert at.info[0].value == t("sidebar.privacy_ai")


def test_switching_provider_and_model_applies_to_this_session(two_providers, example_text):
    at = analyzed(example_text)
    at.selectbox(key="llm_provider").set_value("openai").run()
    assert at.text_input(key="llm_model_openai").value == "gpt-5"
    at.text_input(key="llm_model_openai").input("gpt-5-mini").run()
    assert "OpenAI" in ai_tab_text(at) and "gpt-5-mini" in ai_tab_text(at)

    other = analyzed(example_text)  # another browser session keeps the operator's default
    assert "Claude (Anthropic)" in ai_tab_text(other)


def test_the_choice_survives_switching_pages(two_providers, example_text):
    at = analyzed(example_text)
    at.selectbox(key="llm_provider").set_value("openai").run()
    at.text_input(key="llm_model_openai").input("gpt-5-mini").run()
    goto(at, "settings")  # the same controls, now on the page itself
    assert at.selectbox(key="llm_provider").value == "openai"
    assert at.text_input(key="llm_model_openai").value == "gpt-5-mini"
    goto(at, "home")
    goto(at, "analysis")
    assert "OpenAI" in ai_tab_text(at) and "gpt-5-mini" in ai_tab_text(at)


def test_invalid_model_falls_back_to_the_configured_one(two_providers, example_text):
    at = analyzed(example_text)
    at.text_input(key="llm_model_anthropic").input("bad model; rm -rf").run()
    assert any(t("llm.model_invalid", model="claude-opus-5-5") == w.value for w in at.warning)
    assert "claude-opus-5-5" in ai_tab_text(at)


def test_turning_ai_off_is_the_rule_based_mode(two_providers, example_text):
    at = analyzed(example_text)
    at.toggle(key="llm_enabled").set_value(False).run()
    assert any(t("llm.fallback") == c.value for c in at.caption)
    assert any(t("ai.not_configured") == i.value for i in at.info)  # AI tab
    assert not any(c.key == "ai_consent" for c in at.checkbox)
    assert any(t("ui.ai.rule_based") in m.value for m in at.sidebar.markdown)
    at = grill(at)
    assert any(t("grill.ui.mode_deterministic") in i.value for i in at.info)
    goto(at, "settings")
    assert at.toggle(key="llm_enabled").value is False  # still off on another page
    assert at.info[0].value == t("sidebar.privacy")


def test_locked_settings_show_but_do_not_offer_changes(two_providers, monkeypatch, example_text):
    monkeypatch.setenv("AI_LOCK_SETTINGS", "true")
    at = analyzed(example_text)
    assert not [s for s in at.selectbox if s.key == "llm_provider"]
    assert not [ti for ti in at.text_input if ti.key and ti.key.startswith("llm_")]
    assert any(t("llm.locked") == c.value for c in at.caption)
    assert at.toggle(key="llm_enabled").value is True  # turning AI off stays possible


def test_ollama_needs_no_key(monkeypatch, example_text):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    at = analyzed(example_text)
    assert "Ollama" in ai_tab_text(at) and "qwen3:8b" in ai_tab_text(at)
    assert any("http://localhost:11434" in c for c in settings_text(at))


# --- Status ---------------------------------------------------------------------------------------------

def test_status_says_connected_only_after_a_successful_test(two_providers, monkeypatch):
    monkeypatch.setattr(llm_ui, "check_connection", lambda config: None)
    at = new_app()
    badge = lambda: next(m.value for m in at.sidebar.markdown if "badge[" in m.value)  # noqa: E731
    assert t("ui.ai.ready", provider="Claude (Anthropic)") in badge()
    goto(at, "settings").button(key="llm_test").click().run()
    assert t("ui.ai.connected", provider="Claude (Anthropic)") in badge()
    at.selectbox(key="llm_provider").set_value("openai").run()
    assert t("ui.ai.ready", provider="OpenAI") in badge()  # the earlier test was for Claude


# --- Keys ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_keys_are_never_shown_and_settings_are_translated(two_providers, example_text, lang):
    at = analyzed(example_text)
    at.selectbox(key="language").select(lang).run()
    texts = visible_text(at)
    goto(at, "settings")
    texts += visible_text(at)
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
    at = goto(new_app(), "settings")
    at.button(key="llm_test").click().run()
    assert calls == [("anthropic", "claude-opus-5-5")]
    assert at.success[0].value == t("llm.test_ok", model="claude-opus-5-5")

    outcome["error"] = "auth"
    at.selectbox(key="llm_provider").set_value("openai").run()
    assert not at.success  # the earlier result was for another provider
    at.button(key="llm_test").click().run()
    assert at.error[0].value == t("ai.error.auth")


# --- Automation always uses Claude ---------------------------------------------------------------------------

def test_automation_gets_claude_even_when_openai_is_selected(two_providers, monkeypatch, example_text):
    seen = []
    monkeypatch.setattr(automation_ui, "render_automation", lambda lang, ws, ai, persist: seen.append(ai))
    at = analyzed(example_text)
    goto(at, "tests")  # Automation is a tab of the Test Cases page
    at.selectbox(key="llm_provider").set_value("openai").run()
    assert seen[-1] is not None and seen[-1].provider == "anthropic"
    at.toggle(key="llm_enabled").set_value(False).run()
    assert seen[-1] is None  # AI off means no automation agent either
