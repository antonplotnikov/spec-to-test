"""Bug Reports page with the opt-in Claude Code generator, driven by a fake CLI (no real `claude`, no requests)."""

import json
import subprocess

import pytest
from test_app_features import button, new_app
from test_bug_reports_ui import BUG, editor, save, saved

from conftest import goto
from spec_to_test.llm import claude_code
from spec_to_test.models import Severity, Source

STATUS = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "pro"}
DRAFT = {
    "title": "Export on the Orders page fails with a 500 error",
    "what": {"value": "Export fails with a 500 error", "quotes": ["I get a 500 error"]},
    "where": {"value": "Orders page", "quotes": ["the Orders page"]},
    "when": {"value": "Every time since release 2.3.1", "quotes": ["Happens every time since release 2.3.1"]},
    "preconditions": [{"text": "Logged in as admin", "quote": "I logged in as admin"}],
    "steps": [{"text": "Open the Orders page", "quote": "opened the Orders page"},
              {"text": "Click Export", "quote": "clicked Export"}],
    "actual_result": {"value": "500 error instead of the CSV file", "quotes": ["500 error instead of the CSV file"]},
    "expected_result": {"value": "", "quotes": []},
    "environment": [{"text": "Chrome 120", "quote": "Chrome 120"}, {"text": "Firefox 119", "quote": "Chrome 120"}],
    "severity": {"level": "high", "quotes": ["500 error"]},
    "priority": {"level": None, "quotes": []},
}


def usage_report(session: int, weekly: int) -> dict:
    return {"rate_limits": {"limits": [
        {"kind": "session", "group": "session", "percent": session, "resets_at": "2026-10-17T18:40:00+00:00",
         "scope": None, "severity": "normal", "is_active": True},
        {"kind": "weekly_all", "group": "weekly", "percent": weekly, "resets_at": "2026-10-23T04:00:00+00:00",
         "scope": None, "severity": "normal", "is_active": False},
    ], "extra_usage": None}}


RESULT_USAGE = {"input_tokens": 1800, "output_tokens": 545, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0}


class FakeCLI:
    """`auth status`, `/usage` (session 36% → 38%) and the generation request."""

    def __init__(self, result: str | None = None, is_error: bool = False, usage: bool = True):
        self.result = json.dumps(DRAFT) if result is None else result
        self.is_error = is_error
        self.usage = usage
        self.session = [36, 38]
        self.calls: list[list[str]] = []
        self.inputs: list[str] = []

    def __call__(self, args, *, input, timeout, env, cwd):
        self.calls.append(args)
        self.inputs.append(input)
        if args[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(STATUS), "")
        init = {"type": "system", "subtype": "init", "apiKeySource": "none"}
        if input == "/usage":
            session = self.session.pop(0) if len(self.session) > 1 else self.session[0]
            reply = {"type": "assistant", "message": {"content": []}}
            if self.usage:
                reply["usage_report"] = usage_report(session, 27)
            result = {"type": "result", "subtype": "success", "is_error": False, "result": "", "num_turns": 0,
                      "local_command": "usage", "usage": {"input_tokens": 0, "output_tokens": 0}}
            return subprocess.CompletedProcess(args, 0, "\n".join(map(json.dumps, [init, reply, result])), "")
        result = {"type": "result", "subtype": "success", "is_error": self.is_error, "result": self.result,
                  "usage": RESULT_USAGE, "modelUsage": {"claude-sonnet-5-5": {}}, "total_cost_usd": 0.0123,
                  "duration_ms": 12300}
        return subprocess.CompletedProcess(args, 1 if self.is_error else 0,
                                           "\n".join(map(json.dumps, [init, result])), "")

    @property
    def kinds(self) -> list[str]:
        return ["auth" if c[1] == "auth" else ("usage" if i == "/usage" else "request")
                for c, i in zip(self.calls, self.inputs, strict=True)]


@pytest.fixture
def cli(monkeypatch):
    fake = FakeCLI()
    monkeypatch.setenv("SPEC_TO_TEST_CLAUDE_CODE", "1")
    monkeypatch.setattr(claude_code, "find_binary", lambda *_: "/opt/fake/bin/claude")
    monkeypatch.setattr(claude_code, "run_cli", fake)
    return fake


def open_page(text: str = BUG):
    at = goto(new_app(), "bug_reports")
    at.text_area(key="bug_report_text").input(text).run()
    return at


def checkbox(at, key: str):
    return next(c for c in at.checkbox if c.key == key)


def generate_with_claude(at):
    checkbox(at, "bug_cc_consent").check().run()
    button(at, "bug_cc_generate").click().run()
    assert not at.exception, at.exception
    return at


def test_hidden_unless_opted_in(monkeypatch):
    called = []
    monkeypatch.setattr(claude_code, "run_cli", lambda *a, **k: called.append(a))
    at = open_page()
    assert not any(b.key == "bug_cc_generate" for b in at.button)
    assert called == []


def test_missing_cli_is_explained(monkeypatch):
    monkeypatch.setenv("SPEC_TO_TEST_CLAUDE_CODE", "1")
    monkeypatch.setattr(claude_code, "find_binary", lambda *_: "")
    at = open_page()
    assert any("`claude` command was not found" in w.value for w in at.warning)
    assert not any(b.key == "bug_cc_generate" for b in at.button)


def test_consent_is_required(cli):
    at = open_page()
    assert button(at, "bug_cc_generate").disabled
    assert cli.calls == []
    assert any("counts toward your plan's usage limits" in c.value for c in at.caption)


def test_generates_a_checked_draft(cli):
    at = generate_with_claude(open_page())
    assert cli.kinds == ["usage", "auth", "request", "usage"]
    usage_args = cli.calls[0]
    assert "--disable-slash-commands" not in usage_args  # /usage needs slash commands; tools stay off
    assert usage_args[usage_args.index("--tools") + 1] == "" and "--strict-mcp-config" in usage_args
    assert editor(at, "text_input", "title").value == "Export on the Orders page fails with a 500 error"
    assert editor(at, "text_area", "steps").value == "Open the Orders page\nClick Export"
    assert editor(at, "text_area", "environment").value == "Chrome 120"  # Firefox 119 was invented
    assert editor(at, "text_area", "expected_result").value == ""
    assert editor(at, "selectbox", "severity").value == Severity.HIGH
    assert any("Removed because the description does not support them" in w.value and "Environment" in w.value
               for w in at.warning)
    assert any("Generated by Claude (Claude Code)" in c.value for c in at.caption)
    assert saved() == []


def test_saving_keeps_the_claude_origin(cli):
    at = save(generate_with_claude(open_page()))
    [report] = saved()
    assert report.generated_by == "claude_code" and report.source == Source.AI
    assert report.environment == ["Chrome 120"]
    assert any("Generated by Claude (Claude Code), not edited yet" in c.value for c in at.caption)


@pytest.mark.parametrize(("message", "expected"), [
    ("You've hit your session limit · resets 3pm", "usage limit is reached"),
    ("Not logged in · Please run /login", "not signed in"),
])
def test_errors_are_shown_and_nothing_is_drafted(monkeypatch, message, expected):
    fake = FakeCLI(result=message, is_error=True)
    monkeypatch.setenv("SPEC_TO_TEST_CLAUDE_CODE", "1")
    monkeypatch.setattr(claude_code, "find_binary", lambda *_: "/opt/fake/bin/claude")
    monkeypatch.setattr(claude_code, "run_cli", fake)
    at = generate_with_claude(open_page())
    assert any(expected in e.value for e in at.error)
    assert any("rule-based generator above still works" in c.value for c in at.caption)
    assert not any(w.key and w.key.startswith("br_title_") for w in at.text_input)


def test_empty_description_is_not_sent(cli):
    at = goto(new_app(), "bug_reports")
    generate_with_claude(at)
    assert any("Describe the bug first" in e.value for e in at.error)
    assert cli.calls == []


def test_shows_tokens_and_plan_percent_of_the_generation(cli):
    at = generate_with_claude(open_page())
    [panel] = [i.value for i in at.info if "Usage of this generation" in i.value]
    assert "2,345 tokens: 1,800 input, 545 output, 0 cache" in panel
    assert "claude-sonnet-5-5" in panel and "12.3 s" in panel
    assert "Session limit: 36% → 38% (+2%)" in panel
    assert "Weekly limit (all models): 27% → 27% (less than 1%)" in panel
    assert any("≈ $0.0123 at API prices" in c.value and "other Claude sessions" in c.value for c in at.caption)


def test_usage_is_saved_with_the_report_and_listed(cli):
    at = save(generate_with_claude(open_page()))
    [report] = saved()
    usage = report.generation_usage
    assert usage.tokens.total_tokens == 2345 and usage.tokens.output_tokens == 545
    assert [lim.percent for lim in usage.before.limits] == [36, 27]
    assert [lim.percent for lim in usage.after.limits] == [38, 27]
    table = at.table[0].value
    assert list(table["Tokens"]) == ["2,345"]
    assert any("Usage of this generation" in i.value for i in at.info)  # still shown when reopened


def test_tokens_without_plan_limits(monkeypatch):
    fake = FakeCLI(usage=False)
    monkeypatch.setenv("SPEC_TO_TEST_CLAUDE_CODE", "1")
    monkeypatch.setattr(claude_code, "find_binary", lambda *_: "/opt/fake/bin/claude")
    monkeypatch.setattr(claude_code, "run_cli", fake)
    at = generate_with_claude(open_page())
    [panel] = [i.value for i in at.info if "Usage of this generation" in i.value]
    assert "2,345 tokens" in panel and "Plan limits could not be read" in panel


def test_check_plan_limits_sends_nothing_to_the_model(cli):
    at = open_page()
    button(at, "bug_cc_limits").click().run()
    assert not at.exception
    assert cli.kinds == ["usage"] and cli.inputs == ["/usage"]  # the description is not sent
    assert any("Plan limits now" in c.value and "Session limit: 36% used" in c.value for c in at.caption)


def test_failed_generation_still_reports_its_tokens(monkeypatch):
    fake = FakeCLI(result="not a report")
    monkeypatch.setenv("SPEC_TO_TEST_CLAUDE_CODE", "1")
    monkeypatch.setattr(claude_code, "find_binary", lambda *_: "/opt/fake/bin/claude")
    monkeypatch.setattr(claude_code, "run_cli", fake)
    at = generate_with_claude(open_page())
    assert any("not a valid bug report" in e.value for e in at.error)
    assert any("still used 2,345 tokens" in c.value for c in at.caption)


def test_russian_number_format(cli):
    at = goto(new_app(), "settings")
    at.selectbox(key="language").select("ru").run()
    at = generate_with_claude(open_page_in(at))
    [panel] = [i.value for i in at.info if "Расход на эту генерацию" in i.value]
    assert "2 345 токенов: 1 800 входных, 545 выходных" in panel
    assert "Лимит сессии: 36% → 38% (+2%)" in panel


def open_page_in(at, text: str = BUG):
    goto(at, "bug_reports")
    at.text_area(key="bug_report_text").input(text).run()
    return at
