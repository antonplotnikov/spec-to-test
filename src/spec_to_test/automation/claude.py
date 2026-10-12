"""Claude for the automation agent loop (tool use over the Playwright MCP tools).

Reuses the app's AI configuration, client factory and error codes
(spec_to_test.ai_analysis), so the same key, model and messages apply. The
loop itself lives in orchestrator.py; this module sends one request.
"""

from collections.abc import Callable
from typing import Any

from spec_to_test.ai_analysis import AIConfig, AIError, _default_client_factory, _error_code

MAX_TOKENS = 16000
# Models that accept server-side refusal fallbacks ("default" routing) and effort.
FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORT_MODEL_PREFIXES = (
    "claude-fable", "claude-mythos", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-5",
)


class ClaudeAgent:
    """Sends one turn of the exploration conversation. Blocking; run it in a thread."""

    def __init__(self, config: AIConfig, client_factory: Callable[[AIConfig], Any] = _default_client_factory) -> None:
        self.config = config
        self._client_factory = client_factory
        self._client: Any = None

    @property
    def model(self) -> str:
        return self.config.model

    def create(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        if self._client is None:
            self._client = self._client_factory(self.config)
        params: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": messages,
            "tools": tools,
            # Caches tools, system prompt and history up to the latest turn.
            "cache_control": {"type": "ephemeral"},
        }
        if self.config.model.startswith(EFFORT_MODEL_PREFIXES):
            params["output_config"] = {"effort": "high"}
        try:
            if self.config.model in FALLBACK_MODELS:
                # A safety-classifier decline is retried on Anthropic's recommended model.
                response = self._client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
            else:
                response = self._client.messages.create(**params)
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK errors may echo request data; keep only a code
            raise AIError(_error_code(exc)) from None
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            raise AIError("refused")
        if stop == "max_tokens":
            raise AIError("truncated")
        return response
