"""One structured request to Claude, OpenAI, an OpenAI-compatible server or Ollama.

Every provider gets the same system prompt and user message and must answer
with JSON matching a Pydantic model; the result is validated against that
model before anyone sees it. Self-hosted servers (OpenAI-compatible, Ollama)
are called over plain HTTP: no SDK, and nothing from the environment (such as
OPENAI_API_KEY or OPENAI_CUSTOM_HEADERS, which the OpenAI SDK would add) goes
along. They get the JSON schema as a plain `response_format`/`format`, and the
reply is validated here, since not all of them support OpenAI's strict schemas. Every failure becomes an `AIError` whose `code`
maps to an `ai.error.<code>` translation. SDK error details are dropped: they
can echo request data, and the API key must never reach a message or a log.

Callers check consent first; this module only sends what it is given.
"""

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, SecretStr, ValidationError

from spec_to_test.llm.config import DEFAULT_TIMEOUT_S, ENV_FILE, AIConfig, load_settings
from spec_to_test.llm.usage import Usage, estimate_input_tokens

T = TypeVar("T", bound=BaseModel)
ClientFactory = Callable[[AIConfig], Any]

TIMEOUT_S = DEFAULT_TIMEOUT_S
MAX_RETRIES = 2
MAX_RESPONSE_BYTES = 5_000_000
# Reasoning models on local servers may think aloud or fence the JSON.
_THINKING = re.compile(r"^\s*<think>.*?</think>", re.DOTALL)
_FENCED = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class AIError(Exception):
    """Failure with a `code` that maps to an `ai.error.<code>` translation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an error: following it would resend the key to another address."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _post_json(url: str, payload: dict[str, Any], timeout: float, key: str = "") -> dict[str, Any]:
    """POST JSON and read a JSON object back. Every failure becomes an AIError."""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
    try:
        with _OPENER.open(request, timeout=timeout) as response:  # operator-set http(s) URL
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise AIError(_http_code(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        raise AIError("connection") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise AIError("invalid_response")
    try:
        data = json.loads(raw)
    except ValueError:
        raise AIError("invalid_response") from None
    if not isinstance(data, dict):
        raise AIError("invalid_response")
    return data


class OllamaClient:
    """Minimal client for Ollama's /api/chat (no SDK needed)."""

    def __init__(self, base_url: str, timeout: float = TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, model: str, messages: list[dict[str, str]], schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
        return _post_json(f"{self.base_url}/api/chat", {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": schema,  # structured output: the reply must match this JSON schema
            "options": {"temperature": 0, "num_predict": max_tokens},
        }, self.timeout)


class CompatibleClient:
    """Minimal client for /chat/completions of an OpenAI-compatible server (LM Studio, vLLM, llama.cpp ...)."""

    def __init__(self, base_url: str, api_key: SecretStr | None = None, timeout: float = TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._api_key = api_key or SecretStr("")

    def chat(self, model: str, messages: list[dict[str, str]], schema: dict[str, Any], name: str,
             max_tokens: int) -> dict[str, Any]:
        # `max_tokens` and a non-strict json_schema are what these servers all accept;
        # OpenAI's own `parse()` assumes support for strict schemas.
        return _post_json(f"{self.base_url}/chat/completions", {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
        }, self.timeout, self._api_key.get_secret_value())


def _http_code(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "model_not_found"  # Ollama answers 404 for a model that is not pulled
    if status == 429:
        return "rate_limit"
    return "api"  # including a redirect, which is not followed


def default_client_factory(config: AIConfig) -> Any:
    """The provider's client. SDKs are optional extras (requirements-ai.txt)."""
    key = config.api_key.get_secret_value()
    if config.provider == "anthropic":
        try:
            import anthropic
        except ImportError as exc:
            raise AIError("sdk_missing") from exc
        return anthropic.Anthropic(api_key=key, max_retries=MAX_RETRIES, timeout=config.timeout)
    if config.provider == "openai":
        try:
            import openai
        except ImportError as exc:
            raise AIError("sdk_missing") from exc
        return openai.OpenAI(
            api_key=key, base_url=config.base_url or None, max_retries=MAX_RETRIES, timeout=config.timeout,
        )
    if config.provider == "openai_compatible":
        return CompatibleClient(config.base_url, config.api_key, timeout=config.timeout)
    if config.provider == "ollama":
        return OllamaClient(config.base_url, timeout=config.timeout)
    raise AIError("unsupported_provider")


# ---------------------------------------------------------------------------
# One request per provider
# ---------------------------------------------------------------------------

def _count(value: object) -> int | None:
    """A token count as the provider reported it; anything else is unknown, never zero."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage(source: object, input_name: str, output_name: str) -> Usage:
    """Usage from an SDK object's attributes."""
    return Usage(input_tokens=_count(getattr(source, input_name, None)),
                 output_tokens=_count(getattr(source, output_name, None)))


def _usage_dict(source: object, input_key: str, output_key: str) -> Usage:
    """Usage from a JSON object of the answer."""
    if not isinstance(source, dict):
        return Usage()
    return Usage(input_tokens=_count(source.get(input_key)), output_tokens=_count(source.get(output_key)))


def _anthropic(client: Any, config: AIConfig, system: str, user: str, output: type[T], max_tokens: int) -> tuple[Any, Usage]:
    message = client.messages.parse(
        model=config.model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=output,
    )
    if getattr(message, "stop_reason", None) == "refusal":
        raise AIError("refused")
    if getattr(message, "stop_reason", None) == "max_tokens":
        raise AIError("truncated")
    usage = _usage(getattr(message, "usage", None), "input_tokens", "output_tokens")
    return getattr(message, "parsed_output", None), usage


def _parse_json(content: Any, output: type[T]) -> T:
    if not isinstance(content, str):
        raise AIError("invalid_response")
    text = _THINKING.sub("", content, count=1)
    if fenced := _FENCED.match(text):
        text = fenced.group(1)
    try:
        return output.model_validate_json(text)
    except ValidationError:
        raise AIError("invalid_response") from None


def _openai(client: Any, config: AIConfig, system: str, user: str, output: type[T], max_tokens: int) -> tuple[Any, Usage]:
    completion = client.chat.completions.parse(
        model=config.model,
        max_completion_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=output,
    )
    choices = getattr(completion, "choices", None) or []
    if not choices:
        raise AIError("invalid_response")
    choice = choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise AIError("truncated")
    message = getattr(choice, "message", None)
    if getattr(choice, "finish_reason", None) == "content_filter" or getattr(message, "refusal", None):
        raise AIError("refused")
    usage = _usage(getattr(completion, "usage", None), "prompt_tokens", "completion_tokens")
    return getattr(message, "parsed", None), usage


def _openai_compatible(client: Any, config: AIConfig, system: str, user: str, output: type[T],
                       max_tokens: int) -> tuple[Any, Usage]:
    data = client.chat(
        model=config.model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        schema=output.model_json_schema(),
        name=output.__name__,
        max_tokens=max_tokens,
    )
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AIError("invalid_response")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        message = {}
    if choice.get("finish_reason") == "length":
        raise AIError("truncated")
    if choice.get("finish_reason") == "content_filter" or message.get("refusal"):
        raise AIError("refused")
    usage = _usage_dict(data.get("usage"), "prompt_tokens", "completion_tokens")
    return _parse_json(message.get("content"), output), usage


def _ollama(client: Any, config: AIConfig, system: str, user: str, output: type[T], max_tokens: int) -> tuple[Any, Usage]:
    data = client.chat(
        model=config.model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        schema=output.model_json_schema(),
        max_tokens=max_tokens,
    )
    if data.get("done_reason") == "length":
        raise AIError("truncated")
    usage = Usage(input_tokens=_count(data.get("prompt_eval_count")), output_tokens=_count(data.get("eval_count")))
    return _parse_json((data.get("message") or {}).get("content"), output), usage


_SENDERS: dict[str, Callable[..., Any]] = {
    "anthropic": _anthropic, "openai": _openai, "openai_compatible": _openai_compatible, "ollama": _ollama,
}


def request_structured(
    config: AIConfig,
    system: str,
    user_message: str,
    output_format: type[T],
    client_factory: ClientFactory = default_client_factory,
    max_tokens: int = 16000,
) -> T:
    """One structured request to the configured provider. Every failure becomes an AIError.

    With a usage ledger on the configuration, the request reserves its worst case before it is sent,
    so the app's limits hold even for parallel requests. The answer's tokens then replace the
    reservation (see spec_to_test.llm.usage).
    """
    send = _SENDERS.get(config.provider)
    if send is None:
        raise AIError("unsupported_provider")
    ledger = config.ledger
    ticket = None
    if ledger is not None:
        estimate = estimate_input_tokens(system, user_message, json.dumps(output_format.model_json_schema()))
        ticket = ledger.reserve(config.provider, config.model, estimate, max_tokens)
        if ticket is None:
            raise AIError("budget_exceeded")
    try:
        client = client_factory(config)
        parsed, usage = send(client, config, system, user_message, output_format, max_tokens)
    except AIError as error:
        if ledger is not None and ticket is not None:
            # An answer arrived but could not be used: its tokens were spent, so they stay counted at their
            # worst case. Without an answer (connection, authorization, ...) nothing was spent.
            if error.code in _ANSWERED_CODES:
                ledger.settle(ticket, Usage())
            else:
                ledger.release(ticket)
        raise
    except Exception as exc:  # noqa: BLE001 - SDK errors; details may echo request data
        if ledger is not None and ticket is not None:
            ledger.release(ticket)
        raise AIError(error_code(exc)) from None
    if ledger is not None and ticket is not None:
        ledger.settle(ticket, usage)
    if not isinstance(parsed, output_format):
        raise AIError("invalid_response")
    return parsed


# Failures after the provider has answered: the tokens of that answer were used.
_ANSWERED_CODES = frozenset({"truncated", "refused", "invalid_response"})


def error_code(exc: Exception) -> str:
    """Map an SDK exception to an error code. Anthropic's and OpenAI's SDKs share these names."""
    name = type(exc).__name__
    if name in ("AuthenticationError", "PermissionDeniedError", "OAuthError"):
        return "auth"
    if name == "RateLimitError":
        return "rate_limit"
    if name in ("APIConnectionError", "APITimeoutError"):
        return "connection"
    if name == "NotFoundError":
        return "model_not_found"
    if name == "LengthFinishReasonError":
        return "truncated"
    if name == "ContentFilterFinishReasonError":
        return "refused"
    return "api"


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------

class _Ping(BaseModel):
    ok: bool


def check_connection(config: AIConfig, client_factory: ClientFactory = default_client_factory) -> None:
    """Send a tiny request with no user data. Raises AIError when the provider cannot be used."""
    request_structured(
        config,
        'Connection test. Reply with {"ok": true}.',
        "ping",
        _Ping,
        client_factory,
        max_tokens=2000,  # room for models that reason before answering
    )


# ---------------------------------------------------------------------------
# Provider interface for features
# ---------------------------------------------------------------------------

class StructuredProvider(Protocol):
    """What a feature needs from a model: one request answered with JSON validated against `output`.

    Implementations raise AIError on every failure. Features depend on this
    interface only, so another provider or model needs no change in them.
    """

    @property
    def label(self) -> str: ...

    def request(self, system: str, user: str, output: type[T], max_tokens: int) -> T: ...


class ConfiguredProvider:
    """The StructuredProvider for one AIConfig (any provider of `spec_to_test.llm.config`)."""

    def __init__(self, config: AIConfig, client_factory: ClientFactory = default_client_factory) -> None:
        self.config = config
        self._client_factory = client_factory

    @property
    def label(self) -> str:
        return f"{self.config.provider_name} · {self.config.model}"

    def request(self, system: str, user: str, output: type[T], max_tokens: int) -> T:
        return request_structured(self.config, system, user, output, self._client_factory, max_tokens)


def load_provider(environ: dict[str, str] | None = None, env_file: Path | None = ENV_FILE,
                  client_factory: ClientFactory = default_client_factory) -> ConfiguredProvider:
    """The AI_PROVIDER provider from the environment (or .env).

    Raises AIError("not_configured") when AI_PROVIDER is unset or "none", and
    AIError(<problem>) when it cannot be used: key_missing, url_missing,
    model_missing, invalid_url, insecure_url or unsupported_provider.
    """
    settings = load_settings(environ, env_file)
    config = settings.default()
    if config is not None:
        return ConfiguredProvider(config, client_factory)
    if not settings.problems:
        raise AIError("not_configured")
    problem = settings.problems.get(settings.default_provider) or next(iter(settings.problems.values()))
    raise AIError("unsupported_provider" if problem == "unknown_provider" else problem)
