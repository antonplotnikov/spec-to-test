"""One structured request per provider. Fakes for Claude and OpenAI; Ollama and the real
OpenAI SDK talk to a local HTTP server on 127.0.0.1, so no real provider is contacted."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, SecretStr

from spec_to_test.llm import providers
from spec_to_test.llm.config import AIConfig
from spec_to_test.llm.providers import AIError, OllamaClient, check_connection, error_code, request_structured

CLAUDE_KEY = "test-key-123"
OPENAI_KEY = "oa-key-456"


class Answer(BaseModel):
    items: list[str]


def claude() -> AIConfig:
    return AIConfig(provider="anthropic", model="claude-opus-5-5", api_key=SecretStr(CLAUDE_KEY))


def openai_config(base_url: str = "") -> AIConfig:
    return AIConfig(provider="openai", model="gpt-5", api_key=SecretStr(OPENAI_KEY), base_url=base_url)


def ollama(base_url: str) -> AIConfig:
    return AIConfig(provider="ollama", model="llama3.1", base_url=base_url)


def compatible(base_url: str, key: str = "") -> AIConfig:
    return AIConfig(provider="openai_compatible", model="qwen2.5-7b", api_key=SecretStr(key), base_url=base_url)


# --- Local HTTP server ---------------------------------------------------------------------------

class Server:
    """Answers every POST with the next queued (status, body); records requests."""

    def __init__(self) -> None:
        self.replies: list[tuple[int, object]] = []
        self.requests: list[dict] = []
        self.delay = 0.0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server API
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                headers = {k.lower(): v for k, v in self.headers.items()}
                outer.requests.append({"path": self.path, "headers": headers, "body": json.loads(body or b"null")})
                time.sleep(outer.delay)
                status, reply = outer.replies.pop(0) if outer.replies else (500, {"error": "no reply queued"})
                data = reply if isinstance(reply, bytes) else json.dumps(reply).encode()
                self.send_response(status)
                if 300 <= status < 400:
                    self.send_header("Location", outer.url + "/elsewhere")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST  # noqa: N815 - records a followed redirect

            def log_message(self, *args: object) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)  # 127.0.0.1 must not go through a proxy
    srv = Server()
    yield srv
    srv.close()


# --- Claude ------------------------------------------------------------------------------------

class FakeAnthropic:
    def __init__(self, parsed=None, stop_reason="end_turn", error=None):
        self.parsed, self.stop_reason, self.error = parsed, stop_reason, error
        self.calls: list[dict] = []
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.parsed)


def test_claude_request_and_result():
    fake = FakeAnthropic(Answer(items=["a"]))
    result = request_structured(claude(), "system text", "user text", Answer, lambda c: fake)
    assert result == Answer(items=["a"])
    call = fake.calls[0]
    assert call["system"] == "system text" and call["messages"] == [{"role": "user", "content": "user text"}]
    assert call["output_format"] is Answer and call["model"] == "claude-opus-5-5"


@pytest.mark.parametrize(("stop", "code"), [("refusal", "refused"), ("max_tokens", "truncated")])
def test_claude_stop_reasons(stop, code):
    with pytest.raises(AIError) as err:
        request_structured(claude(), "s", "u", Answer, lambda c: FakeAnthropic(Answer(items=[]), stop_reason=stop))
    assert err.value.code == code


# --- OpenAI (fake client) ---------------------------------------------------------------------------

class FakeOpenAI:
    def __init__(self, completion=None, error=None):
        self.completion, self.error = completion, error
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=self)

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.completion


def completion(parsed=None, finish_reason="stop", refusal=None):
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason, message=message)])


def test_openai_request_and_result():
    fake = FakeOpenAI(completion(Answer(items=["x"])))
    result = request_structured(openai_config(), "system text", "user text", Answer, lambda c: fake, max_tokens=123)
    assert result == Answer(items=["x"])
    call = fake.calls[0]
    assert call["messages"] == [{"role": "system", "content": "system text"}, {"role": "user", "content": "user text"}]
    assert call["response_format"] is Answer and call["model"] == "gpt-5" and call["max_completion_tokens"] == 123


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (completion(Answer(items=[]), finish_reason="length"), "truncated"),
        (completion(None, finish_reason="content_filter"), "refused"),
        (completion(None, refusal="I can't help with that."), "refused"),
        (completion(None), "invalid_response"),
        (SimpleNamespace(choices=[]), "invalid_response"),
    ],
)
def test_openai_unusable_replies(reply, code):
    with pytest.raises(AIError) as err:
        request_structured(openai_config(), "s", "u", Answer, lambda c: FakeOpenAI(reply))
    assert err.value.code == code


# --- OpenAI (the real SDK against a local server) ----------------------------------------------------

def sdk_factory(config: AIConfig):
    openai = pytest.importorskip("openai")
    return openai.OpenAI(api_key=config.api_key.get_secret_value(), base_url=config.base_url, max_retries=0, timeout=5)


def chat_reply(content: str, finish_reason: str = "stop") -> dict:
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "gpt-5",
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": content, "refusal": None}}],
    }


def test_real_openai_sdk_round_trip(server):
    server.replies.append((200, chat_reply(json.dumps({"items": ["from the model"]}))))
    result = request_structured(openai_config(server.url + "/v1"), "sys", "usr", Answer, sdk_factory)
    assert result == Answer(items=["from the model"])
    request = server.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["headers"]["authorization"] == f"Bearer {OPENAI_KEY}"
    body = request["body"]
    assert body["model"] == "gpt-5" and body["max_completion_tokens"] == 16000
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    schema = body["response_format"]
    assert schema["type"] == "json_schema" and schema["json_schema"]["strict"] is True


@pytest.mark.parametrize(
    ("status", "code"), [(401, "auth"), (403, "auth"), (404, "model_not_found"), (429, "rate_limit"), (500, "api")]
)
def test_real_openai_sdk_errors_are_mapped_without_the_key(server, status, code):
    server.replies.append((status, {"error": {"message": f"bad key {OPENAI_KEY}", "type": "x"}}))
    with pytest.raises(AIError) as err:
        request_structured(openai_config(server.url + "/v1"), "s", "u", Answer, sdk_factory)
    assert err.value.code == code and OPENAI_KEY not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__  # SDK details are dropped


def test_real_openai_sdk_cut_off_reply(server):
    server.replies.append((200, chat_reply('{"items": ["unfinished', finish_reason="length")))
    with pytest.raises(AIError) as err:
        request_structured(openai_config(server.url + "/v1"), "s", "u", Answer, sdk_factory)
    assert err.value.code == "truncated"


def test_real_openai_sdk_unreachable_server():
    with pytest.raises(AIError) as err:
        request_structured(openai_config("http://127.0.0.1:9/v1"), "s", "u", Answer, sdk_factory)
    assert err.value.code == "connection"


# --- OpenAI-compatible server (plain HTTP) --------------------------------------------------------------

def test_compatible_server_round_trip_without_a_key(server, monkeypatch):
    for name, value in {"OPENAI_API_KEY": OPENAI_KEY, "OPENAI_ORG_ID": "org-1",
                        "OPENAI_CUSTOM_HEADERS": f"Authorization: Bearer {OPENAI_KEY}"}.items():
        monkeypatch.setenv(name, value)  # OpenAI settings must never reach a self-hosted server
    server.replies.append((200, chat_reply(json.dumps({"items": ["local"]}))))
    result = request_structured(compatible(server.url + "/v1"), "sys", "usr", Answer, max_tokens=700)
    assert result == Answer(items=["local"])
    request = server.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert "authorization" not in request["headers"] and "openai-organization" not in request["headers"]
    assert OPENAI_KEY not in json.dumps(request)
    body = request["body"]
    assert body["model"] == "qwen2.5-7b" and body["max_tokens"] == 700 and body["temperature"] == 0
    assert body["stream"] is False
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    assert body["response_format"] == {
        "type": "json_schema", "json_schema": {"name": "Answer", "schema": Answer.model_json_schema()},
    }


def test_compatible_server_gets_its_own_key(server):
    server.replies.append((200, chat_reply('{"items": []}')))
    request_structured(compatible(server.url + "/v1", key="vllm-key"), "s", "u", Answer)
    assert server.requests[0]["headers"]["authorization"] == "Bearer vllm-key"


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"items": ["a"]}\n```',
        '<think>The user wants a list.</think>\n{"items": ["a"]}',
        '<think>plan</think>```\n{"items": ["a"]}\n```',
    ],
)
def test_compatible_server_reply_may_be_fenced_or_preceded_by_thinking(server, content):
    server.replies.append((200, chat_reply(content)))
    assert request_structured(compatible(server.url + "/v1"), "s", "u", Answer) == Answer(items=["a"])


@pytest.mark.parametrize(
    ("status", "reply", "code"),
    [
        (200, chat_reply("Sure! Here are some items."), "invalid_response"),
        (200, chat_reply('{"wrong": 1}'), "invalid_response"),
        (200, {"choices": []}, "invalid_response"),
        (200, {"choices": ["x"]}, "invalid_response"),
        (200, b"<html>not json</html>", "invalid_response"),
        (200, chat_reply('{"items": ["cut', finish_reason="length"), "truncated"),
        (200, chat_reply("", finish_reason="content_filter"), "refused"),
        (404, {"error": {"message": "model not loaded"}}, "model_not_found"),
        (401, {"error": {"message": "bad key vllm-key"}}, "auth"),
        (400, {"error": {"message": "response_format not supported"}}, "api"),
        (302, {}, "api"),  # a redirect is not followed with the key
    ],
)
def test_compatible_server_failures(server, status, reply, code):
    server.replies.append((status, reply))
    with pytest.raises(AIError) as err:
        request_structured(compatible(server.url + "/v1", key="vllm-key"), "s", "u", Answer)
    assert err.value.code == code and "vllm-key" not in repr(err.value) and err.value.__cause__ is None
    assert len(server.requests) == 1


def test_compatible_server_not_running():
    with pytest.raises(AIError) as err:
        request_structured(compatible("http://127.0.0.1:9/v1"), "s", "u", Answer)
    assert err.value.code == "connection"


def test_compatible_server_key_is_not_in_the_client_repr():
    client = providers.default_client_factory(compatible("http://localhost:1234/v1", key="vllm-key"))
    assert isinstance(client, providers.CompatibleClient) and "vllm-key" not in repr(vars(client))


# --- Ollama (plain HTTP) ---------------------------------------------------------------------------------

def ollama_reply(content: str, done_reason: str = "stop") -> dict:
    return {"model": "llama3.1", "message": {"role": "assistant", "content": content}, "done": True,
            "done_reason": done_reason}


def test_ollama_round_trip(server):
    server.replies.append((200, ollama_reply(json.dumps({"items": ["local"]}))))
    result = request_structured(ollama(server.url), "sys", "usr", Answer, max_tokens=500)
    assert result == Answer(items=["local"])
    request = server.requests[0]
    assert request["path"] == "/api/chat"
    assert "authorization" not in request["headers"]
    body = request["body"]
    assert body["stream"] is False and body["model"] == "llama3.1"
    assert body["format"] == Answer.model_json_schema()  # structured output
    assert body["options"] == {"temperature": 0, "num_predict": 500}
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]


@pytest.mark.parametrize(
    ("status", "reply", "code"),
    [
        (404, {"error": "model 'llama3.1' not found, try pulling it first"}, "model_not_found"),
        (500, {"error": "boom"}, "api"),
        (401, {"error": "unauthorized"}, "auth"),
        (429, {"error": "busy"}, "rate_limit"),
        (200, b"not json", "invalid_response"),
        (200, ["a", "list"], "invalid_response"),
        (200, {"message": {}}, "invalid_response"),
        (200, ollama_reply('{"wrong": 1}'), "invalid_response"),
        (200, ollama_reply("not json at all"), "invalid_response"),
        (200, ollama_reply('```json\n{"wrong": 1}\n```'), "invalid_response"),
        (200, ollama_reply('{"items": ["cut', done_reason="length"), "truncated"),
    ],
)
def test_ollama_failures(server, status, reply, code):
    server.replies.append((status, reply))
    with pytest.raises(AIError) as err:
        request_structured(ollama(server.url), "s", "u", Answer)
    assert err.value.code == code


def test_ollama_not_running():
    with pytest.raises(AIError) as err:
        request_structured(ollama("http://127.0.0.1:9"), "s", "u", Answer)
    assert err.value.code == "connection"


def test_ollama_timeout(server):
    server.delay = 1.0
    server.replies.append((200, ollama_reply('{"items": []}')))
    with pytest.raises(AIError) as err:
        request_structured(ollama(server.url), "s", "u", Answer, lambda c: OllamaClient(c.base_url, timeout=0.2))
    assert err.value.code == "connection"


def test_ollama_oversized_reply_is_rejected(server, monkeypatch):
    monkeypatch.setattr(providers, "MAX_RESPONSE_BYTES", 100)
    server.replies.append((200, ollama_reply(json.dumps({"items": ["x" * 500]}))))
    with pytest.raises(AIError) as err:
        request_structured(ollama(server.url), "s", "u", Answer)
    assert err.value.code == "invalid_response"


# --- Shared behaviour ----------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("AuthenticationError", "auth"), ("PermissionDeniedError", "auth"), ("RateLimitError", "rate_limit"),
        ("APIConnectionError", "connection"), ("APITimeoutError", "connection"), ("NotFoundError", "model_not_found"),
        ("LengthFinishReasonError", "truncated"), ("ContentFilterFinishReasonError", "refused"),
        ("BadRequestError", "api"), ("ValueError", "api"),
    ],
)
def test_error_codes(name, code):
    assert error_code(type(name, (Exception,), {})()) == code


@pytest.mark.parametrize("make_config", [claude, openai_config])
def test_sdk_exceptions_never_carry_the_key(make_config):
    config = make_config()
    key = config.api_key.get_secret_value()
    error = type("AuthenticationError", (Exception,), {})(f"invalid key {key}")
    fake = FakeAnthropic(error=error) if config.provider == "anthropic" else FakeOpenAI(error=error)
    with pytest.raises(AIError) as err:
        request_structured(config, "s", "u", Answer, lambda c: fake)
    assert err.value.code == "auth" and key not in repr(err.value) and err.value.__cause__ is None


def test_unsupported_provider_is_rejected_before_any_client_is_made():
    made = []
    config = AIConfig(provider="gemini", model="m")
    with pytest.raises(AIError) as err:
        request_structured(config, "s", "u", Answer, lambda c: made.append(c))
    assert err.value.code == "unsupported_provider" and made == []
    with pytest.raises(AIError) as err:
        providers.default_client_factory(config)
    assert err.value.code == "unsupported_provider"


@pytest.mark.parametrize(("provider", "module"), [("anthropic", "anthropic"), ("openai", "openai")])
def test_missing_sdk_is_reported(monkeypatch, provider, module):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == module:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    config = claude() if provider == "anthropic" else openai_config()
    with pytest.raises(AIError) as err:
        providers.default_client_factory(config)
    assert err.value.code == "sdk_missing"


def test_configured_timeout_reaches_the_client():
    config = ollama("http://localhost:11434").model_copy(update={"timeout": 900.0})
    assert providers.default_client_factory(config).timeout == 900.0
    client = providers.default_client_factory(compatible("http://localhost:1234/v1").model_copy(update={"timeout": 45.0}))
    assert client.timeout == 45.0


def test_ollama_needs_no_sdk():
    client = providers.default_client_factory(ollama("http://localhost:11434"))
    assert isinstance(client, OllamaClient) and client.base_url == "http://localhost:11434"


def test_connection_check_sends_no_user_data():
    fake = FakeOpenAI(completion(providers._Ping(ok=True)))
    check_connection(openai_config(), lambda c: fake)
    assert [m["content"] for m in fake.calls[0]["messages"]][1] == "ping"


def test_connection_check_reports_failures():
    fake = FakeOpenAI(error=type("APIConnectionError", (Exception,), {})())
    with pytest.raises(AIError) as err:
        check_connection(openai_config(), lambda c: fake)
    assert err.value.code == "connection"
