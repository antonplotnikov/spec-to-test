"""One structured request to Claude, OpenAI or Ollama.

Every provider gets the same system prompt and user message and must answer
with JSON matching a Pydantic model; the result is validated against that
model before anyone sees it. Every failure becomes an `AIError` whose `code`
maps to an `ai.error.<code>` translation. SDK error details are dropped: they
can echo request data, and the API key must never reach a message or a log.

Callers check consent first; this module only sends what it is given.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from spec_to_test.llm.config import AIConfig

T = TypeVar("T", bound=BaseModel)
ClientFactory = Callable[[AIConfig], Any]

TIMEOUT_S = 300.0
MAX_RETRIES = 2
MAX_RESPONSE_BYTES = 5_000_000


class AIError(Exception):
    """Failure with a `code` that maps to an `ai.error.<code>` translation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

class OllamaClient:
    """Minimal client for Ollama's /api/chat (no SDK needed)."""

    def __init__(self, base_url: str, timeout: float = TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(self, model: str, messages: list[dict[str, str]], schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
        body = json.dumps({
            "model": model,
            "messages": messages,
            "stream": False,
            "format": schema,  # structured output: the reply must match this JSON schema
            "options": {"temperature": 0, "num_predict": max_tokens},
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat", data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - operator-set http(s) URL
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


def _http_code(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "model_not_found"  # Ollama answers 404 for a model that is not pulled
    if status == 429:
        return "rate_limit"
    return "api"


def default_client_factory(config: AIConfig) -> Any:
    """The provider's client. SDKs are optional extras (requirements-ai.txt)."""
    key = config.api_key.get_secret_value()
    if config.provider == "anthropic":
        try:
            import anthropic
        except ImportError as exc:
            raise AIError("sdk_missing") from exc
        return anthropic.Anthropic(api_key=key, max_retries=MAX_RETRIES, timeout=TIMEOUT_S)
    if config.provider == "openai":
        try:
            import openai
        except ImportError as exc:
            raise AIError("sdk_missing") from exc
        return openai.OpenAI(api_key=key, base_url=config.base_url or None, max_retries=MAX_RETRIES, timeout=TIMEOUT_S)
    if config.provider == "ollama":
        return OllamaClient(config.base_url, timeout=TIMEOUT_S)
    raise AIError("unsupported_provider")


# ---------------------------------------------------------------------------
# One request per provider
# ---------------------------------------------------------------------------

def _anthropic(client: Any, config: AIConfig, system: str, user: str, output: type[T], max_tokens: int) -> Any:
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
    return getattr(message, "parsed_output", None)


def _openai(client: Any, config: AIConfig, system: str, user: str, output: type[T], max_tokens: int) -> Any:
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
    return getattr(message, "parsed", None)


def _ollama(client: Any, config: AIConfig, system: str, user: str, output: type[T], max_tokens: int) -> Any:
    data = client.chat(
        model=config.model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        schema=output.model_json_schema(),
        max_tokens=max_tokens,
    )
    if data.get("done_reason") == "length":
        raise AIError("truncated")
    content = (data.get("message") or {}).get("content")
    if not isinstance(content, str):
        raise AIError("invalid_response")
    try:
        return output.model_validate_json(content)
    except ValidationError:
        raise AIError("invalid_response") from None


_SENDERS: dict[str, Callable[..., Any]] = {"anthropic": _anthropic, "openai": _openai, "ollama": _ollama}


def request_structured(
    config: AIConfig,
    system: str,
    user_message: str,
    output_format: type[T],
    client_factory: ClientFactory = default_client_factory,
    max_tokens: int = 16000,
) -> T:
    """One structured request to the configured provider. Every failure becomes an AIError."""
    send = _SENDERS.get(config.provider)
    if send is None:
        raise AIError("unsupported_provider")
    client = client_factory(config)
    try:
        parsed = send(client, config, system, user_message, output_format, max_tokens)
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001 - SDK errors; details may echo request data
        raise AIError(error_code(exc)) from None
    if not isinstance(parsed, output_format):
        raise AIError("invalid_response")
    return parsed


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
