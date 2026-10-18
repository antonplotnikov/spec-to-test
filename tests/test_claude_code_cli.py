"""Claude Code CLI adapter: isolation, login checks and error handling, all with a fake CLI.

No test starts the real `claude` binary or sends a request.
"""

import json
import os
import subprocess

import pytest
from pydantic import BaseModel

from spec_to_test.llm import claude_code
from spec_to_test.llm.claude_code import (
    ADDED_VARIABLES,
    REMOVED_VARIABLES,
    ClaudeCodeProvider,
    ClaudeCodeSettings,
    child_environment,
    failure_code,
    load_claude_code_settings,
    parse_output,
)
from spec_to_test.llm.providers import AIError

BINARY = "/opt/fake/bin/claude"
SUBSCRIPTION = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
                "email": "someone@example.com", "orgId": "org-1", "subscriptionType": "pro"}


class Answer(BaseModel):
    ok: bool


def stream(result: str = '{"ok": true}', *, api_key_source: str = "none", subtype: str = "success",
           is_error: bool = False) -> str:
    events = [
        {"type": "system", "subtype": "init", "apiKeySource": api_key_source, "tools": []},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": result}]}},
        {"type": "result", "subtype": subtype, "is_error": is_error, "result": result},
    ]
    return "\n".join(json.dumps(e) for e in events) + "\n"


class FakeCLI:
    """Stands in for subprocess.run: answers `auth status` and `-p` and records every call."""

    def __init__(self, status: dict | None = None, stdout: str | None = None, returncode: int = 0,
                 stderr: str = "", error: Exception | None = None, status_error: Exception | None = None):
        self.status = SUBSCRIPTION if status is None else status
        self.stdout = stream() if stdout is None else stdout
        self.returncode = returncode
        self.stderr = stderr
        self.error = error
        self.status_error = status_error
        self.calls: list[dict] = []

    def __call__(self, args, *, input, timeout, env, cwd):
        self.calls.append({"args": args, "input": input, "timeout": timeout, "env": env, "cwd": cwd,
                           "cwd_exists": os.path.isdir(cwd), "cwd_files": os.listdir(cwd)})
        if args[1:3] == ["auth", "status"]:
            if self.status_error:
                raise self.status_error
            return subprocess.CompletedProcess(args, 0, json.dumps(self.status), "")
        if self.error:
            raise self.error
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)

    @property
    def request(self) -> dict:
        return next(c for c in self.calls if c["args"][1] == "-p")


def provider(cli: FakeCLI, environ: dict | None = None, **settings) -> ClaudeCodeProvider:
    values = {"enabled": True, "binary": BINARY} | settings
    return ClaudeCodeProvider(ClaudeCodeSettings(**values), runner=cli, environ=environ or {"PATH": "/usr/bin"})


def code_of(call) -> str:
    with pytest.raises(AIError) as error:
        call()
    return error.value.code


# --- Settings ------------------------------------------------------------------------

def test_off_unless_opted_in(monkeypatch):
    monkeypatch.setattr(claude_code, "find_binary", lambda *_: BINARY)
    assert load_claude_code_settings({}).enabled is False
    assert load_claude_code_settings({"SPEC_TO_TEST_CLAUDE_CODE": "no"}).usable is False
    settings = load_claude_code_settings({"SPEC_TO_TEST_CLAUDE_CODE": "1"})
    assert settings.usable and settings.binary == BINARY and settings.model == ""
    assert settings.timeout == claude_code.DEFAULT_TIMEOUT_S


def test_settings_model_and_timeout_are_validated(monkeypatch):
    monkeypatch.setattr(claude_code, "find_binary", lambda *_: "")
    settings = load_claude_code_settings({
        "SPEC_TO_TEST_CLAUDE_CODE": "true", "SPEC_TO_TEST_CLAUDE_CODE_MODEL": "sonnet; rm -rf /",
        "SPEC_TO_TEST_CLAUDE_CODE_TIMEOUT": "99999",
    })
    assert settings.enabled and not settings.usable  # no binary
    assert settings.model == "" and settings.timeout == claude_code.TIMEOUT_RANGE_S[1]
    settings = load_claude_code_settings({"SPEC_TO_TEST_CLAUDE_CODE": "1", "SPEC_TO_TEST_CLAUDE_CODE_MODEL": "sonnet",
                                          "SPEC_TO_TEST_CLAUDE_CODE_TIMEOUT": "abc"})
    assert settings.model == "sonnet" and settings.timeout == claude_code.DEFAULT_TIMEOUT_S


def test_disabled_or_missing_binary_never_runs_anything():
    cli = FakeCLI()
    assert code_of(lambda: provider(cli, enabled=False).request("s", "u", Answer)) == "disabled"
    assert code_of(lambda: provider(cli, binary="").request("s", "u", Answer)) == "missing"
    assert cli.calls == []


# --- Isolation -----------------------------------------------------------------------

def test_request_has_no_tools_and_keeps_nothing():
    cli = FakeCLI()
    assert provider(cli).request("SYSTEM", "the bug text", Answer) == Answer(ok=True)
    args = cli.request["args"]
    assert args[0] == BINARY and args[1] == "-p"
    joined = " ".join(args)
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--disallowedTools") + 1] == "*"
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert args[args.index("--max-turns") + 1] == "1"
    assert json.loads(args[args.index("--settings") + 1]) == {"disableAllHooks": True}
    assert args[args.index("--system-prompt") + 1] == "SYSTEM"
    for unsafe in ("--allowedTools", "--dangerously-skip-permissions", "bypassPermissions", "--add-dir",
                   "--mcp-config", "--bare", "--continue", "--resume"):
        assert unsafe not in joined
    # The description goes through stdin, never the command line.
    assert cli.request["input"] == "the bug text" and "the bug text" not in joined


def test_runs_in_an_empty_temporary_folder_that_is_removed():
    cli = FakeCLI()
    provider(cli).request("s", "u", Answer)
    call = cli.request
    assert call["cwd_exists"] and call["cwd_files"] == []
    assert os.path.realpath(call["cwd"]) != os.path.realpath(os.getcwd())
    assert not os.path.exists(call["cwd"])


def test_api_credentials_never_reach_the_cli():
    environ = {name: "secret-value" for name in REMOVED_VARIABLES} | {
        "PATH": "/usr/bin", "HOME": "/home/me", "SPEC_TO_TEST_CLAUDE_CODE": "1",
    }
    cli = FakeCLI()
    provider(cli, environ=environ).request("s", "u", Answer)
    for call in cli.calls:  # auth status and the request
        env = call["env"]
        assert not set(REMOVED_VARIABLES) & set(env)
        assert "secret-value" not in env.values()
        assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/me"
        assert all(env[name] == value for name, value in ADDED_VARIABLES.items())
        assert "SPEC_TO_TEST_CLAUDE_CODE" not in env


def test_child_environment_defaults_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("SOME_SETTING", "kept")
    env = child_environment()
    assert "ANTHROPIC_API_KEY" not in env and env["SOME_SETTING"] == "kept"


def test_model_is_passed_only_when_set():
    cli = FakeCLI()
    provider(cli).request("s", "u", Answer)
    assert "--model" not in cli.request["args"]
    cli = FakeCLI()
    p = provider(cli, model="sonnet")
    p.request("s", "u", Answer)
    args = cli.request["args"]
    assert args[args.index("--model") + 1] == "sonnet"
    assert p.label == "Claude Code · sonnet"


def test_default_runner_uses_subprocess_without_a_shell(monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs, args=args)
        stdout = json.dumps(SUBSCRIPTION) if args[1] == "auth" else stream()
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
    p = ClaudeCodeProvider(ClaudeCodeSettings(enabled=True, binary=BINARY, timeout=42), environ={})
    assert p.request("s", "u", Answer).ok
    assert seen["timeout"] == 42 and seen["input"] == "u" and seen["capture_output"] and seen["text"]
    assert not seen.get("shell") and isinstance(seen["args"], list)


# --- Login checks --------------------------------------------------------------------

def test_login_check_reads_only_the_plan():
    cli = FakeCLI()
    assert provider(cli).check_login() == "pro"
    assert cli.calls[0]["args"] == [BINARY, "auth", "status", "--json"]


@pytest.mark.parametrize(("status", "code"), [
    ({"loggedIn": False}, "not_logged_in"),
    ({"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"}, "not_subscription"),
    ({"loggedIn": True, "authMethod": "apiKeyHelper"}, "not_subscription"),
    ({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "bedrock"}, "not_subscription"),
])
def test_request_is_not_sent_without_a_claude_plan_login(status, code):
    cli = FakeCLI(status=status)
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == code
    assert [c["args"][1] for c in cli.calls] == ["auth"]  # stopped before `-p`


def test_unreadable_status_is_an_error():
    cli = FakeCLI()
    cli.status = "not an object"  # type: ignore[assignment]
    assert code_of(lambda: provider(cli).check_login()) == "invalid_response"

    def failing_status(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "Error: not authenticated", "")

    p = ClaudeCodeProvider(ClaudeCodeSettings(enabled=True, binary=BINARY), runner=failing_status, environ={})
    assert code_of(p.check_login) == "not_logged_in"


def test_api_key_reported_by_the_run_is_rejected():
    cli = FakeCLI(stdout=stream(api_key_source="ANTHROPIC_API_KEY"))
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == "not_subscription"


# --- Failures ------------------------------------------------------------------------

@pytest.mark.parametrize(("message", "code"), [
    ("You've hit your session limit · resets 3pm", "limit"),
    ("You've hit your weekly limit", "limit"),
    ("Claude AI usage limit reached|1760000000", "limit"),
    ("Credit balance is too low", "limit"),
    ("API Error: Request rejected (429)", "rate_limit"),
    ("Server is temporarily limiting requests", "rate_limit"),
    ("API Error: 529 overloaded", "rate_limit"),
    ("Not logged in · Please run /login", "not_logged_in"),
    ("Login expired · Please run /login", "not_logged_in"),
    ("Failed to authenticate: OAuth session expired and could not be refreshed", "not_logged_in"),
    ("Something else went wrong", "failed"),
])
def test_failed_runs_map_to_codes(message, code):
    cli = FakeCLI(stdout=stream(message, subtype="success", is_error=True), returncode=1)
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == code


def test_max_turns_and_other_error_subtypes():
    assert failure_code("", "error_max_turns") == "invalid_response"
    cli = FakeCLI(stdout=stream("", subtype="error_during_execution"))
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == "failed"


def test_crash_without_a_result_uses_stderr():
    cli = FakeCLI(stdout="", returncode=1, stderr="Error: You've hit your session limit")
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == "limit"
    cli = FakeCLI(stdout="", returncode=0)
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == "invalid_response"


def test_timeout_and_missing_binary():
    cli = FakeCLI(error=subprocess.TimeoutExpired(cmd="claude", timeout=1))
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == "timeout"
    cli = FakeCLI(status_error=FileNotFoundError())
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == "missing"
    cli = FakeCLI(status_error=subprocess.TimeoutExpired(cmd="claude", timeout=1))
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == "timeout"


def test_error_messages_never_carry_cli_output():
    cli = FakeCLI(stdout=stream("secret prompt text echoed back", is_error=True), returncode=1)
    with pytest.raises(AIError) as error:
        provider(cli).request("s", "u", Answer)
    assert "secret" not in str(error.value) and error.value.__cause__ is None


def test_oversized_output_is_rejected():
    cli = FakeCLI(stdout="x" * (claude_code.MAX_OUTPUT_CHARS + 1))
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == "invalid_response"


# --- Parsing the answer --------------------------------------------------------------

@pytest.mark.parametrize("text", [
    '{"ok": true}',
    '```json\n{"ok": true}\n```',
    'Here is the report:\n{"ok": true}\nDone.',
])
def test_json_answer_forms(text):
    assert parse_output(text, Answer) == Answer(ok=True)


@pytest.mark.parametrize("text", ["", "no json here", '{"ok": "maybe"}', None, '{"other": 1}'])
def test_invalid_answers(text):
    with pytest.raises(AIError) as error:
        parse_output(text, Answer)
    assert error.value.code == "invalid_response"


def test_answer_is_validated_against_the_model():
    cli = FakeCLI(stdout=stream('{"ok": "not a bool"}'))
    assert code_of(lambda: provider(cli).request("s", "u", Answer)) == "invalid_response"


def test_every_error_code_is_translated():
    from spec_to_test.i18n import TRANSLATIONS

    codes = {"disabled", "missing", "not_logged_in", "not_subscription", "limit", "rate_limit", "timeout",
             "failed", "invalid_response"}
    for code in codes:
        assert set(TRANSLATIONS[f"claude_code.error.{code}"]) == {"en", "uk", "ru"}


# --- Finding the binary (apps opened from Finder have a minimal PATH) ------------------

def executable(path):
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return str(path)


def test_recorded_binary_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code, "FALLBACK_BINARY", tmp_path / "none")
    recorded = executable(tmp_path / "claude-recorded")
    on_path = tmp_path / "bin"
    on_path.mkdir()
    executable(on_path / "claude")
    assert claude_code.find_binary({"SPEC_TO_TEST_CLAUDE_BIN": recorded, "PATH": str(on_path)}) == recorded
    assert claude_code.find_binary({"SPEC_TO_TEST_CLAUDE_BIN": str(tmp_path / "gone"), "PATH": str(on_path)}) \
        == str(on_path / "claude")


def test_fallback_to_the_native_install_location(tmp_path, monkeypatch):
    fallback = tmp_path / ".local" / "bin"
    fallback.mkdir(parents=True)
    monkeypatch.setattr(claude_code, "FALLBACK_BINARY", fallback / "claude")
    assert claude_code.find_binary({"PATH": str(tmp_path / "empty")}) == ""
    executable(fallback / "claude")
    assert claude_code.find_binary({"PATH": str(tmp_path / "empty")}) == str(fallback / "claude")


def test_binary_setting_is_not_passed_to_the_cli():
    env = child_environment({"SPEC_TO_TEST_CLAUDE_BIN": "/x/claude", "PATH": "/usr/bin"})
    assert "SPEC_TO_TEST_CLAUDE_BIN" not in env


# --- Usage: tokens of a request, plan limits from /usage --------------------------------

from spec_to_test.llm.claude_code import (  # noqa: E402
    GenerationUsage,
    PlanLimit,
    PlanUsage,
    plan_limits,
    token_usage,
)

LIMITS = [
    {"kind": "session", "group": "session", "percent": 36, "resets_at": "2026-10-17T18:40:00+00:00",
     "scope": None, "severity": "normal", "is_active": True},
    {"kind": "weekly_scoped", "group": "weekly", "percent": 12.5, "resets_at": None,
     "scope": {"model": {"display_name": "Opus"}, "surface": None}, "severity": "normal", "is_active": False},
]


def usage_stream(limits=LIMITS, api_key_source="none") -> str:
    events = [{"type": "system", "subtype": "init", "apiKeySource": api_key_source},
              {"type": "assistant", "message": {"content": []},
               "usage_report": {"session": {}, "rate_limits": {"limits": limits}}},
              {"type": "result", "subtype": "success", "num_turns": 0, "local_command": "usage", "result": ""}]
    return "\n".join(json.dumps(e) for e in events)


def test_token_usage_from_the_result_event():
    tokens = token_usage({"usage": {"input_tokens": 1800, "output_tokens": 545, "cache_read_input_tokens": 10,
                                    "cache_creation_input_tokens": 5},
                          "modelUsage": {"claude-sonnet-5-5": {}}, "total_cost_usd": 0.0123, "duration_ms": 12300})
    assert tokens.total_tokens == 2360 and tokens.models == ["claude-sonnet-5-5"]
    assert tokens.cost_usd_estimate == 0.0123 and tokens.duration_ms == 12300
    odd = token_usage({"usage": {"input_tokens": "many", "output_tokens": -3}, "total_cost_usd": "x"})
    assert odd.total_tokens == 0 and odd.cost_usd_estimate == 0


def test_request_records_tokens_even_when_the_answer_is_unusable():
    events = [{"type": "system", "subtype": "init", "apiKeySource": "none"},
              {"type": "result", "subtype": "success", "is_error": False, "result": "not json",
               "usage": {"input_tokens": 100, "output_tokens": 20}}]
    cli = FakeCLI(stdout="\n".join(json.dumps(e) for e in events))
    p = provider(cli)
    assert code_of(lambda: p.request("s", "u", Answer)) == "invalid_response"
    assert p.last_usage is not None and p.last_usage.total_tokens == 120
    cli = FakeCLI(status={"loggedIn": False})
    p = provider(cli)
    code_of(lambda: p.request("s", "u", Answer))
    assert p.last_usage is None  # nothing was sent


def test_plan_limits_from_the_usage_report():
    limits = plan_limits(json.loads(line) for line in usage_stream().splitlines())  # type: ignore[arg-type]
    assert [(lim.kind, lim.percent, lim.scope) for lim in limits] == [("session", 36, ""), ("weekly_scoped", 12.5, "Opus")]
    assert plan_limits([{"type": "assistant", "message": {}}]) is None
    bad = [{"kind": "session"}, {"kind": 5, "percent": 1}, {"kind": "x", "percent": True}, "row"]
    assert plan_limits([{"type": "assistant", "usage_report": {"rate_limits": {"limits": bad}}}]) == []


def test_plan_usage_runs_the_local_usage_command_without_tools():
    cli = FakeCLI(stdout=usage_stream())
    plan = provider(cli).plan_usage("2026-10-17T15:00:00+00:00")
    assert plan is not None and [lim.percent for lim in plan.limits] == [36, 12.5]
    call = cli.calls[-1]
    assert call["input"] == "/usage" and "/usage" not in call["args"]
    assert call["args"][call["args"].index("--tools") + 1] == ""
    assert "--disable-slash-commands" not in call["args"] and "--strict-mcp-config" in call["args"]
    assert not set(REMOVED_VARIABLES) & set(call["env"])


@pytest.mark.parametrize("cli", [
    FakeCLI(stdout=usage_stream(api_key_source="ANTHROPIC_API_KEY")),
    FakeCLI(stdout="", returncode=1),
    FakeCLI(stdout='{"type": "result", "result": "/usage isn\'t available in this environment."}'),
    FakeCLI(error=subprocess.TimeoutExpired(cmd="claude", timeout=1)),
])
def test_plan_usage_is_none_when_unavailable(cli):
    assert provider(cli).plan_usage() is None
    assert provider(FakeCLI(), enabled=False).plan_usage() is None


def test_generation_usage_changes():
    before = PlanUsage(limits=[PlanLimit(kind="session", percent=36), PlanLimit(kind="weekly_all", percent=27)])
    after = PlanUsage(limits=[PlanLimit(kind="session", percent=38), PlanLimit(kind="weekly_all", percent=27),
                              PlanLimit(kind="weekly_scoped", scope="Opus", percent=3)])
    changes = GenerationUsage(before=before, after=after).changes()
    assert [(c.limit.kind, c.before, c.delta) for c in changes] == [
        ("session", 36, 2), ("weekly_all", 27, 0), ("weekly_scoped", None, None)]
    # A window that reset during the request does not show a negative change.
    reset = GenerationUsage(before=before, after=PlanUsage(limits=[PlanLimit(kind="session", percent=1)]))
    assert reset.changes()[0].delta == 0
    assert GenerationUsage(before=before).changes() == []


USAGE_TEXT = """You are currently using your subscription to power your Claude Code usage

Current session: 36% used · resets Oct 17 at 8:40pm (Europe/Warsaw)
Current week (all models): 27% used · resets Oct 23 at 6am (Europe/Warsaw)
Current week (Sonnet only): 3.5% used
"""


def test_limits_from_the_usage_text_when_the_report_has_none():
    events = [{"type": "system", "subtype": "init", "apiKeySource": "none"},
              {"type": "assistant", "message": {"content": [{"type": "text", "text": USAGE_TEXT}]},
               "usage_report": {"rate_limits": {"limits": None}}},
              {"type": "result", "subtype": "success", "result": USAGE_TEXT}]
    cli = FakeCLI(stdout="\n".join(json.dumps(e) for e in events))
    plan = provider(cli).plan_usage()
    assert [(lim.kind, lim.percent, lim.scope) for lim in plan.limits] == [
        ("session", 36, ""), ("weekly_all", 27, ""), ("weekly_scoped", 3.5, "Sonnet only")]  # no duplicates
    from datetime import datetime
    assert datetime.fromisoformat(plan.limits[0].resets_at).utcoffset() is not None
    assert plan.limits[0].resets_at.endswith(("T20:40:00+02:00", "T20:40:00+01:00"))
    assert plan.limits[2].resets_at == ""


def test_reset_text_forms():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime(2026, 12, 30, 12, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    reset = claude_code._reset_from_text
    assert reset("Oct 23 at 6am", "Europe/Warsaw", datetime(2026, 10, 17, tzinfo=ZoneInfo("Europe/Warsaw"))) \
        == "2026-10-23T06:00:00+02:00"
    assert reset("Jan 2 at 9:15am", "Europe/Warsaw", today) == "2027-01-02T09:15:00+01:00"  # next year
    assert reset("8:40pm", "Europe/Warsaw", today) == "2026-12-30T20:40:00+01:00"  # today
    assert reset("soon", "Europe/Warsaw", today) == ""
    assert reset("Dec 31 at 6am", "Not/AZone", today).startswith("2026-12-31T06:00:00")  # this computer's zone


def test_text_without_limit_lines_gives_none():
    events = [{"type": "result", "subtype": "success", "result": "Total cost: $0.0000\nUsage: 0 input"}]
    assert provider(FakeCLI(stdout=json.dumps(events[0]))).plan_usage() is None
