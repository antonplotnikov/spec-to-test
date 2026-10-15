"""LLM provider settings: which providers are offered, with which model, and what the UI may change."""

import pytest

from spec_to_test.llm.config import (
    DEFAULT_MODELS,
    DEFAULT_OLLAMA_URL,
    AIConfig,
    LLMSettings,
    choose,
    load_config,
    load_settings,
    valid_model,
)

CLAUDE_KEY = "test-key-123"
OPENAI_KEY = "oa-key-456"


def settings(**env: str) -> LLMSettings:
    return load_settings(env, env_file=None)


# --- Which providers are offered --------------------------------------------------------------

@pytest.mark.parametrize("env", [{}, {"AI_PROVIDER": "none"}, {"AI_PROVIDER": " NONE "}])
def test_ai_is_off_unless_a_provider_is_named(env):
    # Keys alone do not switch AI on: AI_PROVIDER=none means fully offline.
    result = settings(
        **env, ANTHROPIC_API_KEY=CLAUDE_KEY, OPENAI_API_KEY=OPENAI_KEY, OLLAMA_HOST="localhost",
        OPENAI_COMPATIBLE_BASE_URL="http://localhost:1234/v1", OPENAI_COMPATIBLE_MODEL="m",
    )
    assert not result.enabled and result.default() is None and result.problems == {}


def test_unknown_provider_is_reported_and_ai_stays_off():
    result = settings(AI_PROVIDER="gemini", ANTHROPIC_API_KEY=CLAUDE_KEY)
    assert not result.enabled and result.problems == {"gemini": "unknown_provider"}


@pytest.mark.parametrize("name", ["anthropic", "claude", "Claude", " ANTHROPIC "])
def test_claude_is_enabled_with_its_key(name):
    config = settings(AI_PROVIDER=name, ANTHROPIC_API_KEY=CLAUDE_KEY).default()
    assert config is not None
    assert (config.provider, config.model, config.base_url) == ("anthropic", "claude-opus-5-5", "")
    assert config.api_key.get_secret_value() == CLAUDE_KEY


def test_openai_is_enabled_with_its_key_and_optional_gateway():
    config = settings(AI_PROVIDER="openai", OPENAI_API_KEY=OPENAI_KEY, OPENAI_BASE_URL="https://gw.example.com/v1/").default()
    assert config is not None
    assert (config.provider, config.model, config.base_url) == ("openai", DEFAULT_MODELS["openai"], "https://gw.example.com/v1")


def test_ollama_needs_no_key_and_defaults_to_localhost():
    config = settings(AI_PROVIDER="ollama").default()
    assert config is not None
    assert (config.provider, config.model, config.base_url) == ("ollama", "llama3.1", DEFAULT_OLLAMA_URL)
    assert config.api_key.get_secret_value() == ""


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("localhost:11434", "http://localhost:11434"),
        ("0.0.0.0", "http://localhost:11434"),  # a bind address, as Ollama itself accepts it
        ("http://gpu-box:8080/", "http://gpu-box:8080"),
        ("https://ollama.internal", "https://ollama.internal:11434"),
        ("[::1]:11434", "http://[::1]:11434"),
    ],
)
def test_ollama_host_is_normalized(host, url):
    config = settings(AI_PROVIDER="ollama", OLLAMA_HOST=host).default()
    assert config is not None and config.base_url == url


@pytest.mark.parametrize("host", ["ftp://box", "http://user:pw@box", "http://box:notaport", "http://"])
def test_invalid_server_addresses_are_rejected(host):
    result = settings(AI_PROVIDER="ollama", OLLAMA_HOST=host)
    assert result.default() is None and result.problems == {"ollama": "invalid_url"}
    result = settings(AI_PROVIDER="openai", OPENAI_API_KEY=OPENAI_KEY, OPENAI_BASE_URL=host)
    assert result.default() is None and result.problems["openai"] == "invalid_url"


def test_missing_key_is_reported_per_provider():
    result = settings(AI_PROVIDER="openai", ANTHROPIC_API_KEY=CLAUDE_KEY)
    assert result.default() is None  # the default provider cannot be used ...
    assert list(result.configs) == ["anthropic"]  # ... but Claude can be picked in the UI
    assert result.problems == {"openai": "key_missing"}


def test_every_provider_with_credentials_is_offered_default_first():
    result = settings(
        AI_PROVIDER="openai", ANTHROPIC_API_KEY=CLAUDE_KEY, OPENAI_API_KEY=OPENAI_KEY, OLLAMA_HOST="localhost",
    )
    assert list(result.configs) == ["openai", "anthropic", "ollama"]
    assert result.default() is result.configs["openai"]


def test_ollama_is_offered_besides_the_default_only_when_its_host_is_set():
    assert "ollama" not in settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY=CLAUDE_KEY).configs


def test_model_precedence():
    result = settings(
        AI_PROVIDER="anthropic", AI_MODEL="claude-sonnet-5-5", ANTHROPIC_MODEL="claude-haiku-5-5",
        OPENAI_API_KEY=OPENAI_KEY, ANTHROPIC_API_KEY=CLAUDE_KEY, OPENAI_MODEL="gpt-5-mini",
    )
    # AI_MODEL is for the default provider; per-provider variables apply to the others.
    assert result.configs["anthropic"].model == "claude-sonnet-5-5"
    assert result.configs["openai"].model == "gpt-5-mini"
    assert settings(AI_PROVIDER="ollama", OLLAMA_MODEL="qwen3:8b").default().model == "qwen3:8b"


def test_env_file_is_read_and_environment_wins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nAI_PROVIDER=openai\nOPENAI_API_KEY='from-file-1'\nOPENAI_MODEL=\"gpt-5\"\nUNRELATED=1\n",
        encoding="utf-8",
    )
    config = load_config({}, env_file=env_file)
    assert config is not None and config.api_key.get_secret_value() == "from-file-1"
    config = load_config({"OPENAI_API_KEY": "from-env-2", "OPENAI_MODEL": ""}, env_file=env_file)
    assert config is not None and config.api_key.get_secret_value() == "from-env-2"
    assert config.model == "gpt-5"  # an empty environment value does not erase the file's


def test_keys_never_appear_in_repr_or_dumps():
    result = settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY=CLAUDE_KEY, OPENAI_API_KEY=OPENAI_KEY)
    for text in (repr(result), str(result), result.model_dump_json(), repr(result.default())):
        assert CLAUDE_KEY not in text and OPENAI_KEY not in text


def test_lock_flag():
    assert settings(AI_PROVIDER="ollama", AI_LOCK_SETTINGS="true").locked
    assert settings(AI_PROVIDER="ollama", AI_LOCK_SETTINGS="1").locked
    assert not settings(AI_PROVIDER="ollama", AI_LOCK_SETTINGS="no").locked


# --- What one browser session uses --------------------------------------------------------------

def both() -> LLMSettings:
    return settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY=CLAUDE_KEY, OPENAI_API_KEY=OPENAI_KEY)


def test_choose_defaults_to_the_operator_setting():
    assert choose(both()) == both().default()


def test_choose_disabled_is_the_rule_based_fallback():
    assert choose(both(), enabled=False) is None


def test_choose_switches_provider_and_model():
    config = choose(both(), provider="openai", model="gpt-5-mini")
    assert isinstance(config, AIConfig)
    assert (config.provider, config.model) == ("openai", "gpt-5-mini")
    assert config.api_key.get_secret_value() == OPENAI_KEY  # the key stays the operator's


def test_choose_ignores_unconfigured_providers_and_bad_models():
    assert choose(both(), provider="ollama").provider == "anthropic"
    assert choose(both(), model="x; rm -rf /").model == "claude-opus-5-5"
    assert choose(both(), model="   ").model == "claude-opus-5-5"


def test_locked_settings_cannot_be_changed():
    locked = settings(
        AI_PROVIDER="anthropic", ANTHROPIC_API_KEY=CLAUDE_KEY, OPENAI_API_KEY=OPENAI_KEY, AI_LOCK_SETTINGS="true",
    )
    config = choose(locked, provider="openai", model="gpt-5-mini")
    assert (config.provider, config.model) == ("anthropic", "claude-opus-5-5")
    assert choose(locked, enabled=False) is None  # turning AI off is always allowed


@pytest.mark.parametrize("model", ["claude-opus-5-5", "gpt-5", "llama3.1:8b", "org/model@rev", "qwen2.5-coder:7b"])
def test_valid_model_ids(model):
    assert valid_model(model)


@pytest.mark.parametrize("model", ["", " ", "-flag", "a b", "a" * 101, "model\nX", "<script>"])
def test_invalid_model_ids(model):
    assert not valid_model(model)


# --- Self-hosted OpenAI-compatible servers --------------------------------------------------------

LM_STUDIO = "http://localhost:1234/v1"


@pytest.mark.parametrize("name", ["openai_compatible", "openai-compatible", "compatible", " Compatible "])
def test_compatible_server_needs_an_address_and_a_model_but_no_key(name):
    config = settings(
        AI_PROVIDER=name, OPENAI_COMPATIBLE_BASE_URL=LM_STUDIO + "/", OPENAI_COMPATIBLE_MODEL="qwen2.5-7b-instruct",
    ).default()
    assert config is not None
    assert (config.provider, config.model, config.base_url) == ("openai_compatible", "qwen2.5-7b-instruct", LM_STUDIO)
    assert config.api_key.get_secret_value() == ""


def test_compatible_server_model_may_come_from_ai_model():
    config = settings(AI_PROVIDER="compatible", OPENAI_COMPATIBLE_BASE_URL=LM_STUDIO, AI_MODEL="llama-3.2-3b").default()
    assert config is not None and config.model == "llama-3.2-3b"


@pytest.mark.parametrize(
    ("env", "problem"),
    [
        ({"OPENAI_COMPATIBLE_MODEL": "m"}, "url_missing"),
        ({"OPENAI_COMPATIBLE_BASE_URL": LM_STUDIO}, "model_missing"),  # a server has no default model
        ({"OPENAI_COMPATIBLE_BASE_URL": LM_STUDIO, "OPENAI_COMPATIBLE_MODEL": "a b"}, "model_missing"),
        ({"OPENAI_COMPATIBLE_BASE_URL": "ftp://box", "OPENAI_COMPATIBLE_MODEL": "m"}, "invalid_url"),
    ],
)
def test_compatible_server_problems_are_reported(env, problem):
    result = settings(AI_PROVIDER="openai_compatible", **env)
    assert result.default() is None and result.problems == {"openai_compatible": problem}


def test_compatible_server_is_offered_besides_the_default_only_when_its_address_is_set():
    assert "openai_compatible" not in settings(AI_PROVIDER="anthropic", ANTHROPIC_API_KEY=CLAUDE_KEY).configs
    result = settings(
        AI_PROVIDER="anthropic", ANTHROPIC_API_KEY=CLAUDE_KEY,
        OPENAI_COMPATIBLE_BASE_URL=LM_STUDIO, OPENAI_COMPATIBLE_MODEL="local-model",
    )
    assert list(result.configs) == ["anthropic", "openai_compatible"]
    assert choose(result, provider="openai_compatible").model == "local-model"


def test_real_openai_and_a_compatible_server_are_separate():
    result = settings(
        AI_PROVIDER="openai", OPENAI_API_KEY=OPENAI_KEY,
        OPENAI_COMPATIBLE_BASE_URL=LM_STUDIO, OPENAI_COMPATIBLE_MODEL="local-model",
    )
    assert list(result.configs) == ["openai", "openai_compatible"]
    assert result.configs["openai"].base_url == ""  # still api.openai.com
    # The OpenAI key is never reused for another server.
    assert result.configs["openai_compatible"].api_key.get_secret_value() == ""


@pytest.mark.parametrize(
    "url", ["https://llm.example.com/v1", "http://localhost:8000/v1", "http://127.0.0.1:8000/v1", "http://[::1]:8000/v1"],
)
def test_a_key_may_go_over_https_or_to_this_machine(url):
    result = settings(
        AI_PROVIDER="compatible", OPENAI_COMPATIBLE_BASE_URL=url, OPENAI_COMPATIBLE_MODEL="m",
        OPENAI_COMPATIBLE_API_KEY="vllm-key",
    )
    config = result.default()
    assert config is not None and config.api_key.get_secret_value() == "vllm-key"


@pytest.mark.parametrize("url", ["http://gpu-box:8000/v1", "http://10.0.0.5:8000/v1", "http://llm.example.com/v1"])
def test_a_key_is_never_sent_unencrypted_to_another_machine(url):
    result = settings(
        AI_PROVIDER="compatible", OPENAI_COMPATIBLE_BASE_URL=url, OPENAI_COMPATIBLE_MODEL="m",
        OPENAI_COMPATIBLE_API_KEY="vllm-key",
    )
    assert result.default() is None and result.problems == {"openai_compatible": "insecure_url"}
    result = settings(AI_PROVIDER="openai", OPENAI_API_KEY=OPENAI_KEY, OPENAI_BASE_URL=url)
    assert result.default() is None and result.problems == {"openai": "insecure_url"}
    # Without a key there is nothing to protect: a keyless server on the LAN is fine.
    config = settings(AI_PROVIDER="compatible", OPENAI_COMPATIBLE_BASE_URL=url, OPENAI_COMPATIBLE_MODEL="m").default()
    assert config is not None


def test_compatible_key_never_appears_in_repr_or_dumps():
    result = settings(
        AI_PROVIDER="compatible", OPENAI_COMPATIBLE_BASE_URL=LM_STUDIO, OPENAI_COMPATIBLE_MODEL="m",
        OPENAI_COMPATIBLE_API_KEY="loc-key-789",
    )
    assert result.default() is not None
    for text in (repr(result), result.model_dump_json(), repr(result.default())):
        assert "loc-key-789" not in text


# --- Request timeout -------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "seconds"),
    [("", 300.0), ("900", 900.0), (" 45.5 ", 45.5), ("1", 10.0), ("99999", 3600.0), ("soon", 300.0), ("nan", 300.0)],
)
def test_timeout_is_read_and_clamped(raw, seconds):
    result = settings(AI_PROVIDER="ollama", AI_TIMEOUT=raw, ANTHROPIC_API_KEY=CLAUDE_KEY)
    assert {c.timeout for c in result.configs.values()} == {seconds}
