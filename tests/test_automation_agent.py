"""The Claude request builder and the browser gate (no network, no browser)."""

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from automation_fakes import FAKE_API_KEY, SECRET_VALUE, SERVER_TOOLS, config, resolver
from spec_to_test.ai_analysis import AIConfig, AIError
from spec_to_test.automation.browser import MAX_RESULT_CHARS, BrowserGate, mcp_server_config
from spec_to_test.automation.claude import FALLBACK_BETA, ClaudeAgent
from spec_to_test.automation.security import Redactor, build_egress_policy


class FakeMessages:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.response = response or SimpleNamespace(stop_reason="tool_use", content=[])
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def agent(model: str, **options):
    messages = FakeMessages(**options)
    client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))
    config = AIConfig(provider="anthropic", model=model, api_key=SecretStr(FAKE_API_KEY))
    return ClaudeAgent(config, client_factory=lambda cfg: client), messages


def test_default_model_uses_server_side_fallback_caching_and_effort():
    claude, messages = agent("claude-opus-5-5")
    claude.create("system", [{"role": "user", "content": "hi"}], [{"name": "t"}])
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["max_tokens"] == 16000
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert call["cache_control"] == {"type": "ephemeral"}
    assert call["output_config"] == {"effort": "high"}
    assert "thinking" not in call and "tool_choice" not in call  # adaptive default; forced tool use is a 400


def test_other_models_skip_options_they_do_not_support():
    claude, messages = agent("claude-haiku-4-5")
    claude.create("s", [], [])
    assert "fallbacks" not in messages.calls[0] and "output_config" not in messages.calls[0]


@pytest.mark.parametrize(("stop", "code"), [("refusal", "refused"), ("max_tokens", "truncated")])
def test_stop_reasons_that_cannot_continue_become_errors(stop, code):
    claude, _ = agent("claude-opus-5-5", response=SimpleNamespace(stop_reason=stop, content=[]))
    with pytest.raises(AIError) as error:
        claude.create("s", [], [])
    assert error.value.code == code


def test_sdk_errors_become_codes_without_request_data():
    class RateLimitError(Exception):
        pass

    claude, _ = agent("claude-opus-5-5", error=RateLimitError(f"echo {SECRET_VALUE}"))
    with pytest.raises(AIError) as error:
        claude.create("s", [], [])
    assert error.value.code == "rate_limit" and SECRET_VALUE not in str(error.value)
    assert error.value.__cause__ is None


@pytest.fixture
def gate(tmp_path):
    cfg = config(tmp_path)
    policy = build_egress_policy("https://staging.example.com/", cfg, resolver())
    return BrowserGate(policy, Redactor(cfg.secret_values()), allow_destructive=False), policy, cfg


def test_gate_offers_only_safe_tools_without_file_arguments(gate):
    browser_gate, _, _ = gate
    definitions = browser_gate.tool_definitions(SERVER_TOOLS)
    assert [d["name"] for d in definitions] == ["browser_click", "browser_navigate", "browser_snapshot", "browser_type"]
    for definition in definitions:
        assert "filename" not in definition["input_schema"]["properties"]
        assert "code" not in definition["input_schema"]["properties"]


def test_gate_sanitizes_arguments_and_limits_waits(gate):
    browser_gate, _, _ = gate
    args, refusal = browser_gate.check("browser_wait_for", {"time": 600, "filename": "/etc/x"})
    assert refusal is None and args == {"time": 10}
    _, refusal = browser_gate.check("browser_evaluate", {"function": "() => fetch('//evil')"})
    assert refusal and "not available" in refusal


def test_gate_refuses_destructive_dialogs_and_options(gate):
    browser_gate, _, _ = gate
    assert browser_gate.check("browser_select_option", {"element": "Action", "target": "e1", "values": ["Delete all"]})[1]
    assert browser_gate.check("browser_press_key", {"key": "Enter"})[1] is None


def test_gate_caps_and_masks_output(gate):
    browser_gate, _, _ = gate
    text = browser_gate.observe("- button \"Save\" [ref=e7]\n" + SECRET_VALUE + "x" * (MAX_RESULT_CHARS + 10))
    assert SECRET_VALUE not in text and text.endswith("to see a part of the page.]")
    assert browser_gate.refs["e7"] == 'button "Save"'


def test_mcp_server_config_is_headless_isolated_and_pinned(gate, tmp_path):
    _, policy, cfg = gate
    settings = mcp_server_config(policy, cfg, {"STAGING_PASSWORD": SECRET_VALUE}, tmp_path / "out")
    browser = settings["browser"]
    assert browser["isolated"] and browser["launchOptions"]["headless"]
    assert browser["launchOptions"]["args"] == policy.browser_args()
    assert browser["contextOptions"]["serviceWorkers"] == "block"
    assert settings["capabilities"] == ["core"]
    assert settings["network"]["allowedOrigins"] == ["https://staging.example.com"]
