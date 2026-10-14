"""A stand-in for the model that replays scripted replies (no network, no key).

It answers through the same code path as the real Anthropic SDK client
(`client.messages.parse(..., output_format=...)`), so the evaluation exercises
`llm.providers.request_structured`, schema validation and error mapping exactly
as production does. Replies are picked per request type, in call order; when a
type runs out of replies the model answers with an empty list.
"""

from types import SimpleNamespace
from typing import Any

from pydantic import SecretStr

from spec_to_test.llm.config import AIConfig

SCRIPTED_MODEL = "scripted-model"
# Request type of each structured output format the Grill AI uses.
REQUEST_TYPES = {
    "AIInterviewQuestions": "interview",
    "AIQuestions": "questions",
    "AIReview": "review",
    "AITestCases": "test_cases",
}
_EMPTY: dict[str, dict[str, list[Any]]] = {
    "interview": {"questions": []},
    "questions": {"questions": []},
    "review": {"findings": []},
    "test_cases": {"test_cases": []},
}
# Simulated failures: the SDK exception class name request_structured maps to each error code.
_ERRORS = {
    "rate_limit": "RateLimitError",
    "auth": "AuthenticationError",
    "connection": "APIConnectionError",
    "model_not_found": "NotFoundError",
    "api": "InternalServerError",
}


def scripted_config() -> AIConfig:
    return AIConfig(provider="anthropic", model=SCRIPTED_MODEL, api_key=SecretStr("scripted-no-key"))


class ScriptedModel:
    """Replays `replies` ({request type: [reply, ...]}) and records every request."""

    def __init__(self, replies: dict[str, list[dict]]) -> None:
        self.replies = {kind: list(items) for kind, items in replies.items()}
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        output = kwargs["output_format"]
        kind = REQUEST_TYPES.get(output.__name__, output.__name__)
        self.calls.append({"type": kind, "system": kwargs.get("system", ""), "messages": kwargs.get("messages", [])})
        queue = self.replies.get(kind, [])
        reply = queue.pop(0) if queue else _EMPTY.get(kind, {})
        if "error" in reply:
            raise type(_ERRORS.get(str(reply["error"]), "APIError"), (Exception,), {})("scripted failure")
        return SimpleNamespace(stop_reason="end_turn", parsed_output=output.model_validate(reply))

    def factory(self, config: AIConfig) -> "ScriptedModel":
        return self
