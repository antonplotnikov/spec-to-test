"""Which LLM providers the app may call, read from the environment.

AI is off unless AI_PROVIDER names a provider. That provider is the default;
any other provider whose credentials are present can be picked per browser
session in the sidebar (unless AI_LOCK_SETTINGS is set).

    AI_PROVIDER        none | anthropic (alias: claude) | openai | ollama
    AI_MODEL           model for the AI_PROVIDER provider (else its default)
    AI_LOCK_SETTINGS   true = the sidebar shows the settings but cannot change them
    ANTHROPIC_API_KEY  enables Claude;        ANTHROPIC_MODEL overrides its model
    OPENAI_API_KEY     enables OpenAI;        OPENAI_MODEL, OPENAI_BASE_URL (compatible gateways)
    OLLAMA_HOST        enables a local Ollama server (default http://localhost:11434); OLLAMA_MODEL

Keys are never entered in the UI, never shown and never logged: they are held
in SecretStr and read from the process environment, Streamlit secrets (which
app.py exposes as environment variables) or a local .env file.
"""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr

PROVIDERS = ("anthropic", "openai", "ollama")
ALIASES = {"claude": "anthropic"}
PROVIDER_NAMES = {"anthropic": "Claude (Anthropic)", "openai": "OpenAI", "ollama": "Ollama"}
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "openai": "gpt-5", "ollama": "llama3.1"}
KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
MODEL_VARIABLES = {"anthropic": "ANTHROPIC_MODEL", "openai": "OPENAI_MODEL", "ollama": "OLLAMA_MODEL"}
SDK_MODULES = {"anthropic": "anthropic", "openai": "openai"}  # Ollama is called over plain HTTP
DEFAULT_OLLAMA_URL = "http://localhost:11434"
ENV_KEYS = (
    "AI_PROVIDER", "AI_MODEL", "AI_LOCK_SETTINGS",
    "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL",
    "OLLAMA_HOST", "OLLAMA_MODEL",
)
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
# Model IDs as providers write them (claude-opus-5-5, gpt-5, llama3.1:8b, org/model@rev).
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}")
_TRUE = frozenset({"1", "true", "yes", "on"})


class AIConfig(BaseModel):
    """One provider and model. Built from the environment, never from user input."""

    provider: str
    model: str
    # SecretStr keeps the key out of repr(), logs and tracebacks. Empty for Ollama.
    api_key: SecretStr = SecretStr("")
    # OpenAI-compatible gateway or the Ollama server; "" = the provider's default.
    base_url: str = ""

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAMES.get(self.provider, self.provider)


class LLMSettings(BaseModel):
    # "none" (AI off) or one of PROVIDERS.
    default_provider: str = "none"
    # Providers that can be called, the default first.
    configs: dict[str, AIConfig] = Field(default_factory=dict)
    # Provider -> why it cannot be used ("key_missing", "invalid_url", "unknown_provider").
    problems: dict[str, str] = Field(default_factory=dict)
    locked: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.configs)

    def default(self) -> AIConfig | None:
        return self.configs.get(self.default_provider)


def read_env_file(path: Path) -> dict[str, str]:
    """The AI keys from a .env file (anything else in it is ignored)."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in ENV_KEYS:
            values[key.strip()] = value.strip().strip("'\"")
    return values


def normalize_provider(value: str) -> str:
    value = value.strip().lower()
    return ALIASES.get(value, value) or "none"


def valid_model(model: str) -> bool:
    return bool(_MODEL_ID.fullmatch(model.strip()))


def _http_url(raw: str, default_port: int | None = None) -> str | None:
    """A normalized http(s) base URL, or None if `raw` is not one."""
    raw = raw.strip()
    if "://" not in raw:
        raw = "http://" + raw  # OLLAMA_HOST is often written as host:port
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        return None
    if host in ("0.0.0.0", "::"):  # a bind-all address; the server is reachable locally
        host = "localhost"
    if ":" in host:
        host = f"[{host}]"
    port = port or default_port
    return f"{parts.scheme}://{host}{f':{port}' if port else ''}{parts.path.rstrip('/')}"


def load_settings(environ: dict[str, str] | None = None, env_file: Path | None = ENV_FILE) -> LLMSettings:
    """Read every provider's settings. Environment values win over the .env file."""
    values = read_env_file(env_file) if env_file else {}
    source = environ if environ is not None else os.environ
    values.update({k: v for k, v in source.items() if k in ENV_KEYS and v})
    default = normalize_provider(values.get("AI_PROVIDER", "none"))
    settings = LLMSettings(default_provider=default, locked=values.get("AI_LOCK_SETTINGS", "").strip().lower() in _TRUE)
    if default == "none":
        return settings  # AI off: nothing is offered, whatever keys are present
    if default not in PROVIDERS:
        settings.problems[default] = "unknown_provider"
        settings.default_provider = "none"
        return settings

    for provider in sorted(PROVIDERS, key=lambda p: p != default):
        model = values.get(MODEL_VARIABLES[provider], "").strip()
        if provider == default and values.get("AI_MODEL", "").strip():
            model = values["AI_MODEL"].strip()
        model = model or DEFAULT_MODELS[provider]
        if provider == "ollama":
            if provider != default and "OLLAMA_HOST" not in values:
                continue  # Ollama is offered only when asked for
            url = _http_url(values.get("OLLAMA_HOST", "") or DEFAULT_OLLAMA_URL, default_port=11434)
            if url is None:
                settings.problems[provider] = "invalid_url"
                continue
            settings.configs[provider] = AIConfig(provider=provider, model=model, base_url=url)
            continue
        secret = values.get(KEY_VARIABLES[provider], "").strip()
        if not secret:
            if provider == default:  # other providers without a key are simply not offered
                settings.problems[provider] = "key_missing"
            continue
        raw_url = values.get("OPENAI_BASE_URL", "").strip() if provider == "openai" else ""
        base_url = _http_url(raw_url) if raw_url else ""
        if base_url is None:
            settings.problems[provider] = "invalid_url"
            continue
        settings.configs[provider] = AIConfig(provider=provider, model=model, api_key=SecretStr(secret), base_url=base_url)
    return settings


def load_config(environ: dict[str, str] | None = None, env_file: Path | None = ENV_FILE) -> AIConfig | None:
    """The default provider's configuration, or None when AI is off or not usable."""
    return load_settings(environ, env_file).default()


def choose(
    settings: LLMSettings, *, enabled: bool = True, provider: str | None = None, model: str | None = None
) -> AIConfig | None:
    """The configuration one browser session uses.

    `enabled=False` is the rule-based fallback: no AI at all. A provider must be
    one the operator configured; a model must look like a model ID. Locked
    settings ignore both. Anything invalid falls back to the configured value.
    """
    if not enabled:
        return None
    if settings.locked or provider is None:
        provider = settings.default_provider
    config = settings.configs.get(provider) or settings.default()
    if config is None:
        return None
    model = (model or "").strip()
    if not settings.locked and model and model != config.model and valid_model(model):
        config = config.model_copy(update={"model": model})
    return config
