"""AI mode of the QA agent: provider configuration, the provider adapter, checking the reply,
failures, the end-to-end run of `on_change --ai` and the AI review on the QA task page, against a
local OpenAI-compatible server. No real provider is contacted."""

import functools
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto, home
from spec_to_test.llm import providers
from spec_to_test.llm.providers import AIError, ConfiguredProvider, StructuredProvider, load_provider
from spec_to_test.qa_agent import on_change
from spec_to_test.qa_agent.ai_review import (
    MAX_INPUT_CHARS,
    AIReview,
    add_ai_step,
    ai_review,
    build_message,
)
from spec_to_test.qa_agent.on_change import build_workspace, main
from spec_to_test.qa_agent.tasks import run_task

EXAMPLE = PROJECT_ROOT / "examples" / "password_reset.md"
KEY = "sk-local-secret-123"


@pytest.fixture
def workspace():
    return build_workspace(EXAMPLE.read_text(encoding="utf-8"), "password_reset.md", "en")


@pytest.fixture
def docs(tmp_path):
    old, new = tmp_path / "spec_v1.md", tmp_path / "spec.md"
    text = EXAMPLE.read_text(encoding="utf-8")
    old.write_text(text, encoding="utf-8")
    new.write_text(text.replace("at least 8 characters", "at least 10 characters"), encoding="utf-8")
    return old, new


def _review(workspace, **parts) -> AIReview:
    req = workspace.requirements[0]
    data = {
        "problems": [{"category": "ambiguity", "ids": [req.id], "description": "Unclear.", "quote": ""}],
        "questions": [{"ids": [req.id], "question": "Which limit applies?"}],
        "recommendations": [{"ids": [], "text": "Ask the product owner."}],
    }
    data.update(parts)
    return AIReview.model_validate(data)


class FakeProvider:
    label = "Fake · model-1"

    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error
        self.calls: list[tuple[str, str]] = []

    def request(self, system, user, output, max_tokens):
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.reply


# --- Configuration --------------------------------------------------------------------------

@pytest.mark.parametrize(("environ", "code"), [
    ({}, "not_configured"),
    ({"AI_PROVIDER": "none", "ANTHROPIC_API_KEY": KEY}, "not_configured"),
    ({"AI_PROVIDER": "anthropic"}, "key_missing"),
    ({"AI_PROVIDER": "openai_compatible", "OPENAI_COMPATIBLE_MODEL": "qwen"}, "url_missing"),
    ({"AI_PROVIDER": "openai_compatible", "OPENAI_COMPATIBLE_BASE_URL": "http://localhost:1234/v1"},
     "model_missing"),
    ({"AI_PROVIDER": "openai_compatible", "OPENAI_COMPATIBLE_BASE_URL": "http://example.com/v1",
      "OPENAI_COMPATIBLE_MODEL": "qwen", "OPENAI_COMPATIBLE_API_KEY": KEY}, "insecure_url"),
    ({"AI_PROVIDER": "gemini"}, "unsupported_provider"),
])
def test_a_missing_or_unusable_configuration_names_the_reason(environ, code):
    with pytest.raises(AIError) as err:
        load_provider(environ, env_file=None)
    assert err.value.code == code


def test_the_configured_provider_comes_from_the_environment_and_hides_the_key():
    provider = load_provider({
        "AI_PROVIDER": "openai_compatible", "OPENAI_COMPATIBLE_BASE_URL": "http://localhost:1234/v1",
        "OPENAI_COMPATIBLE_MODEL": "qwen2.5-7b", "OPENAI_COMPATIBLE_API_KEY": KEY,
    }, env_file=None)
    typed: StructuredProvider = provider  # mypy checks that the adapter implements the interface
    assert typed.label == "OpenAI-compatible server · qwen2.5-7b"
    assert provider.config.base_url == "http://localhost:1234/v1"
    assert KEY not in repr(provider.config) and KEY not in provider.label


# --- Adapter over a local OpenAI-compatible server --------------------------------------------

class Server:
    """Answers every POST /chat/completions with the next queued (status, body); records requests."""

    def __init__(self) -> None:
        self.replies: list[tuple[int, object]] = []
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server API
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                       "body": json.loads(body)})
                status, reply = outer.replies.pop(0) if outer.replies else (500, {"error": "none queued"})
                data = reply if isinstance(reply, bytes) else json.dumps(reply).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def answer(self, content: str, finish_reason: str = "stop") -> None:
        self.replies.append((200, {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}))


@pytest.fixture
def server(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)  # 127.0.0.1 must not go through a proxy
    srv = Server()
    yield srv
    srv.httpd.shutdown()
    srv.httpd.server_close()


def _local(server, key: str = "") -> ConfiguredProvider:
    environ = {"AI_PROVIDER": "openai_compatible", "OPENAI_COMPATIBLE_BASE_URL": server.url,
               "OPENAI_COMPATIBLE_MODEL": "qwen2.5-7b"}
    if key:
        environ["OPENAI_COMPATIBLE_API_KEY"] = key
    return load_provider(environ, env_file=None)


def test_the_adapter_sends_the_schema_and_returns_the_validated_reply(server, workspace):
    expected = _review(workspace)
    server.answer(expected.model_dump_json())
    reply = _local(server, KEY).request("system", "user", AIReview, 1000)
    assert reply == expected
    sent = server.requests[0]
    assert sent["path"] == "/v1/chat/completions" and sent["auth"] == f"Bearer {KEY}"
    assert sent["body"]["model"] == "qwen2.5-7b"
    assert sent["body"]["response_format"]["json_schema"]["schema"] == AIReview.model_json_schema()


@pytest.mark.parametrize(("reply", "code"), [
    ((200, {"choices": [{"message": {"content": "not json"}, "finish_reason": "stop"}]}), "invalid_response"),
    ((200, {"choices": [{"message": {"content": '{"problems": []}'}, "finish_reason": "stop"}]}),
     "invalid_response"),
    ((200, {"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]}), "truncated"),
    ((401, {"error": "bad key"}), "auth"),
    ((404, {"error": "no model"}), "model_not_found"),
])
def test_the_adapter_turns_bad_replies_into_error_codes(server, reply, code):
    server.replies.append(reply)
    with pytest.raises(AIError) as err:
        _local(server).request("system", "user", AIReview, 1000)
    assert err.value.code == code


# --- Checking the reply ---------------------------------------------------------------------------

def test_the_message_holds_the_specification_test_cases_and_changes(docs):
    old, new = docs
    workspace = on_change.load_document(on_change.Request(document=new, previous=old))[0]
    payload = json.loads(build_message(workspace, workspace.change_impact).split("\n", 2)[2].rsplit("\n", 1)[0])
    assert [r["id"] for r in payload["requirements"]] == [r.id for r in workspace.requirements]
    assert {tc["id"] for tc in payload["test_cases"]} == {tc.id for tc in workspace.test_cases}
    changes = payload["changes_since_previous_version"]["changes"]
    assert any(c["kind"] == "modified" and "10 characters" in c["new_text"] for c in changes)


def test_items_without_known_ids_or_with_invented_quotes_are_rejected(workspace):
    req = workspace.requirements[0]
    words = " ".join(req.text.split()[:3])
    reply = _review(workspace, problems=[
        {"category": "contradiction", "ids": [req.id, "REQ-999"], "description": " Conflicts. ", "quote": words},
        {"category": "ambiguity", "ids": ["REQ-999"], "description": "No such requirement.", "quote": ""},
        {"category": "missing_scenario", "ids": [req.id], "description": "Made up.", "quote": "not in the text"},
    ], questions=[{"ids": [], "question": "About what?"}],
        recommendations=[{"ids": ["TC-999"], "text": "Fix TC-999."}, {"ids": [], "text": "Review it."}])
    step = ai_review(workspace, FakeProvider(reply))
    assert step.status == "ok" and step.tool == "ai"
    assert [(p.ref, p.refs, p.params) for p in step.problems] == [
        (req.id, [], {"text": "Conflicts.", "quote": words}),
    ]
    assert step.problems[0].topic == "qatask.ai.category.contradiction"
    assert step.unknowns == []
    assert [r.params["text"] for r in step.recommendations] == ["Review it."]
    assert step.summary.key == "qatask.summary.ai_rejected"
    assert step.summary.params == {"model": "Fake · model-1", "problems": "1", "questions": "0", "rejected": "4"}


@pytest.mark.parametrize(("error", "code"), [
    (AIError("auth"), "auth"), (AIError("invalid_response"), "invalid_response"), (RuntimeError("boom"), "api"),
])
def test_a_failed_request_is_a_failed_step_with_the_reason(workspace, error, code):
    step = ai_review(workspace, FakeProvider(error=error))
    assert (step.status, step.error, step.summary.terms) == ("error", code, [f"ai.error.{code}"])


def test_a_reply_of_another_type_is_invalid(workspace):
    assert ai_review(workspace, FakeProvider(reply={"problems": []})).error == "invalid_response"


def test_a_document_too_large_is_not_sent(workspace):
    workspace.requirements[0].text = "x" * MAX_INPUT_CHARS
    provider = FakeProvider(_review(workspace))
    assert ai_review(workspace, provider).error == "input_too_large"
    assert provider.calls == []


def test_a_failed_ai_step_keeps_the_rule_based_result(workspace):
    rule_based = run_task("Full check", workspace)
    combined = add_ai_step(rule_based.model_copy(deep=True), ai_review(workspace, FakeProvider(error=AIError("auth"))))
    assert combined.status == "partial"
    assert combined.steps[:-1] == rule_based.steps and combined.problems == rule_based.problems


# --- End to end: on_change --ai --------------------------------------------------------------

@pytest.fixture
def ai_env(monkeypatch, server):
    monkeypatch.setattr(on_change, "load_provider", functools.partial(load_provider, env_file=None))
    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", server.url)
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "qwen2.5-7b")
    return server


def test_on_change_with_ai_adds_the_checked_ai_findings_to_the_report(docs, tmp_path, ai_env, capsys):
    old, new = docs
    workspace = on_change.load_document(on_change.Request(document=new, previous=old))[0]
    changed = next(c.new_id for c in workspace.change_impact.changes if c.kind == "modified")
    ai_env.answer(json.dumps({
        "problems": [{"category": "change_risk", "ids": [changed], "description": "Old tests use 8 characters.",
                      "quote": "10 characters"},
                     {"category": "ambiguity", "ids": ["REQ-404"], "description": "Invented.", "quote": ""}],
        "questions": [{"ids": [changed], "question": "Does the new minimum apply to existing passwords?"}],
        "recommendations": [{"ids": [], "text": "Update the boundary test cases."}],
    }))
    out = tmp_path / "runs"
    code = main(["--document", str(new), "--previous", str(old), "--out", str(out), "--ai"])

    assert code == 0
    assert "AI review: OpenAI-compatible server · qwen2.5-7b" in capsys.readouterr().out
    sent = ai_env.requests[0]["body"]["messages"][1]["content"]
    assert "changes_since_previous_version" in sent and "10 characters" in sent
    entry = json.loads((out / on_change.JOURNAL_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert (entry["status"], entry["ai"], entry["ai_error"]) == ("done", "OpenAI-compatible server · qwen2.5-7b", "")
    report = (out / "runs" / entry["run_id"] / "report.md").read_text(encoding="utf-8")
    assert "**AI review**: OpenAI-compatible server · qwen2.5-7b: 1 problems, 1 questions; 1 items" in report
    assert f"**{changed} · AI · Change risk**: Old tests use 8 characters. (“10 characters”)" in report
    assert "Does the new minimum apply to existing passwords?" in report
    assert "Update the boundary test cases." in report and "Invented." not in report
    assert "**Requirements analysis**" in report  # the rule-based steps are still there
    result = json.loads((out / "runs" / entry["run_id"] / "result.json").read_text(encoding="utf-8"))
    assert [s["tool"] for s in result["steps"]][-1] == "ai"


def test_on_change_with_ai_but_no_provider_reports_why_and_keeps_the_rule_based_report(docs, tmp_path,
                                                                                      monkeypatch, capsys):
    monkeypatch.setattr(on_change, "load_provider", functools.partial(load_provider, env_file=None))
    old, new = docs
    out = tmp_path / "runs"
    code = main(["--document", str(new), "--previous", str(old), "--out", str(out), "--ai"])

    assert code == 1
    assert "AI review failed: AI is not configured. Set AI_PROVIDER" in capsys.readouterr().out
    entry = json.loads((out / on_change.JOURNAL_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert (entry["status"], entry["ai"], entry["ai_error"]) == ("partial", "", "not_configured")
    report = (out / "runs" / entry["run_id"] / "report.md").read_text(encoding="utf-8")
    assert "**AI review**: not done: AI is not configured." in report
    assert "The rule-based checks are not affected." in report
    assert "**Change Impact**" in report and entry["problems"] > 0


def test_on_change_with_ai_reports_an_invalid_reply(docs, tmp_path, ai_env):
    ai_env.answer("I think the spec is fine.")
    old, new = docs
    out = tmp_path / "runs"
    assert main(["--document", str(new), "--previous", str(old), "--out", str(out), "--ai"]) == 1
    entry = json.loads((out / on_change.JOURNAL_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert entry["ai_error"] == "invalid_response"
    assert "The AI response could not be read." in (out / "runs" / entry["run_id"] / "report.md").read_text(
        encoding="utf-8")


def test_without_ai_nothing_is_sent(docs, tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "request_structured", lambda *a, **k: pytest.fail("AI was called"))
    monkeypatch.setattr(on_change, "load_provider", lambda: pytest.fail("AI was loaded"))
    old, new = docs
    out = tmp_path / "runs"
    assert main(["--document", str(new), "--previous", str(old), "--out", str(out)]) == 0
    entry = json.loads((out / on_change.JOURNAL_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert (entry["ai"], entry["ai_error"]) == ("", "")


# --- The QA task page: AI review in the app --------------------------------------------------

def _task_page(example_text: str) -> AppTest:
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=60)
    at.run()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    goto(at, "qa_agent")
    at.segmented_control(key="qa_mode").set_value("task").run()
    at.text_area(key="qa_task_text").input("Full check").run()
    assert not at.exception
    return at


def _run(at: AppTest) -> AppTest:
    next(b for b in at.button if b.key == "qa_task_run").click().run()
    assert not at.exception
    return at


def _conclusions(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


@pytest.fixture
def page_ai(monkeypatch, server):
    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", server.url)
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "qwen2.5-7b")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", KEY)
    return server


def test_the_page_offers_no_ai_review_without_a_provider(example_text):
    at = _task_page(example_text)
    assert not any(c.key == "qa_task_ai_consent" for c in at.checkbox)
    assert any("AI review is not available" in c.value for c in at.caption)
    assert "AI review" not in _conclusions(_run(at))


def test_the_page_sends_nothing_without_consent(example_text, page_ai):
    at = _task_page(example_text)
    assert at.checkbox(key="qa_task_ai_consent").value is False  # off by default
    _run(at)
    assert page_ai.requests == []
    assert "**AI review**" not in _conclusions(at)


def test_the_page_adds_the_ai_review_after_consent(example_text, page_ai):
    at = _task_page(example_text)
    workspace = at.session_state["workspace"]
    req, tc = workspace.requirements[0], workspace.test_cases[0]
    page_ai.answer(json.dumps({
        "problems": [{"category": "ambiguity", "ids": [req.id], "description": "Which reset channel?", "quote": ""},
                     {"category": "test_gap", "ids": ["TC-999"], "description": "Invented.", "quote": ""}],
        "questions": [{"ids": [req.id], "question": "Is SMS reset allowed?"}],
        "recommendations": [{"ids": [tc.id], "text": f"Approve {tc.id} after the review."}],
    }))
    at.checkbox(key="qa_task_ai_consent").check().run()
    _run(at)

    assert len(page_ai.requests) == 1
    text = _conclusions(at)
    assert "**AI review**: OpenAI-compatible server · qwen2.5-7b: 1 problems, 1 questions; 1 items" in text
    assert f"**{req.id} · AI · Ambiguity**: Which reset channel?" in text and "Invented." not in text
    assert "**Requirements analysis**" in text  # rule-based steps are kept
    assert any("suggestions of the model" in i.value for i in at.info)
    assert at.checkbox(key="qa_task_ai_consent").value is False  # asked again before the next run
    assert not any(b.key == "qa_task_apply" for b in at.button)  # the model's advice changes nothing
    assert tc.review_status == at.session_state["workspace"].test_cases[0].review_status
    assert KEY not in text


def test_the_page_explains_a_failed_ai_review_and_keeps_the_checks(example_text, page_ai):
    page_ai.replies.append((401, {"error": "bad key"}))
    at = _task_page(example_text)
    at.checkbox(key="qa_task_ai_consent").check().run()
    _run(at)
    text = _conclusions(at)
    assert "**AI review**: not done: The AI provider rejected the API key." in text
    assert "**Requirements analysis**" in text and "**Test Case Critic**" in text
    assert any("Done in part" in w.value for w in at.warning)
    assert KEY not in text
