"""Claude Code CLI (`claude -p`) as a structured-output provider, on the user's own Claude login.

For a personal app on the subscriber's own machine. Anthropic's Help Center
("Use the Claude Agent SDK with your Claude plan", update of 2026-10-07) says
`claude -p` can be used with a Claude plan's usage limits; the legal page of
Claude Code allows that only through the unmodified `claude` binary, with
Anthropic's own sign-in, and forbids collecting or storing Claude credentials
and routing other people's requests through one plan. So:

- Off unless SPEC_TO_TEST_CLAUDE_CODE=1 is set (environment or Streamlit secrets).
- The official `claude` binary signs in and sends the request. This module never
  reads, copies or stores a token: it only reads `claude auth status --json`
  (login method and plan; e-mail and organization are ignored).
- Before every request the login must be a claude.ai login to Anthropic itself.
  API-key, bearer-token and cloud-provider variables are removed from the CLI's
  environment, so a key in the app's secrets can never turn the call into a
  paid API request; the init event must also report no API key.
- The model gets no tools: no built-in tools, no MCP servers, no skills or slash
  commands, no hooks, no CLAUDE.md or auto memory, one turn, `dontAsk` permission
  mode, and an empty temporary working directory. The session is not saved.
- The prompt goes through stdin, not the command line (which other local users
  can see in the process list).
- Usage: `last_usage` holds the tokens of the last request (from its result
  event; Claude Code's cost figure is an API-price estimate, not what the plan
  bills). `plan_usage()` reads the plan's limits (session and weekly percent,
  reset time) with the local `/usage` command, which sends nothing to the model
  and uses no tokens; it returns None when they are not available.
- Every failure becomes an AIError whose code maps to `claude_code.error.<code>`:
  disabled, missing, not_logged_in, not_subscription, limit, rate_limit,
  timeout, failed, invalid_response. CLI output is never put in a message.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, ValidationError

from spec_to_test.llm.config import valid_model
from spec_to_test.llm.providers import AIError

T = TypeVar("T", bound=BaseModel)
Runner = Callable[..., "subprocess.CompletedProcess[str]"]

ENABLE_VARIABLE = "SPEC_TO_TEST_CLAUDE_CODE"
MODEL_VARIABLE = "SPEC_TO_TEST_CLAUDE_CODE_MODEL"
TIMEOUT_VARIABLE = "SPEC_TO_TEST_CLAUDE_CODE_TIMEOUT"
SETTING_VARIABLES = (ENABLE_VARIABLE, MODEL_VARIABLE, TIMEOUT_VARIABLE, "SPEC_TO_TEST_CLAUDE_BIN")
DEFAULT_TIMEOUT_S = 180.0
TIMEOUT_RANGE_S = (10.0, 900.0)
STATUS_TIMEOUT_S = 20.0
MAX_OUTPUT_CHARS = 5_000_000
_TRUE = frozenset({"1", "true", "yes", "on"})

# Credentials that would make the CLI bill an API key or a cloud account instead of
# the Claude plan, and a model setting that belongs to the app's own API provider.
REMOVED_VARIABLES = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_PROFILE",
    "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_MODEL",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
)
# Nothing from the user's Claude Code setup reaches the request, and nothing is kept.
ADDED_VARIABLES = {
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_MAX_RETRIES": "2",
}
# No tools of any kind, one turn, nothing that could prompt or run a command.
ISOLATION_FLAGS = (
    "--tools", "",
    "--disallowedTools", "*",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--settings", '{"disableAllHooks": true}',
    "--permission-mode", "dontAsk",
    "--max-turns", "1",
    "--no-session-persistence",
)

_FENCED = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
# Messages Claude Code prints as the result of a failed run (code.claude.com/docs/en/errors).
_LIMIT = re.compile(
    r"hit your (?:\w+ )*limit|usage limit|limit reached|limit will reset|resets? (?:at|in)\b|"
    r"credit balance is too low|spend limit|out of (?:extra )?usage",
    re.I,
)
_RATE = re.compile(r"\b429\b|\b529\b|rate.?limit|temporarily limiting|overloaded", re.I)
_AUTH = re.compile(
    r"not logged in|/login|login expired|log ?in again|authenticat|oauth|invalid api key|"
    r"does not have access|401|403",
    re.I,
)


class TokenUsage(BaseModel):
    """Tokens of one request, as Claude Code reports them in its result event."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    models: list[str] = Field(default_factory=list)
    # Claude Code's estimate at API list prices. A Claude plan is not billed this amount.
    cost_usd_estimate: float = 0.0
    duration_ms: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_creation_tokens


class PlanLimit(BaseModel):
    """One usage meter of the plan, as the server reports it (`/usage`)."""

    kind: str  # "session", "weekly_all", "weekly_scoped", ...
    group: str = ""  # "session", "weekly"
    percent: float = 0.0  # share of the window used, 0-100
    resets_at: str = ""  # ISO 8601
    scope: str = ""  # model or surface of a scoped meter ("Opus", ...)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.scope}"


class PlanUsage(BaseModel):
    limits: list[PlanLimit] = Field(default_factory=list)
    checked_at: str = ""


class LimitChange(BaseModel):
    limit: PlanLimit  # after the request
    before: float | None = None

    @property
    def delta(self) -> float | None:
        return None if self.before is None else max(self.limit.percent - self.before, 0.0)


class GenerationUsage(BaseModel):
    """What one generation used: tokens, and the plan's limits before and after it.

    The percentages belong to the whole account: other Claude sessions running
    at the same time are counted too.
    """

    tokens: TokenUsage | None = None
    before: PlanUsage | None = None
    after: PlanUsage | None = None

    def changes(self) -> list[LimitChange]:
        if self.after is None:
            return []
        before = {limit.key: limit.percent for limit in (self.before.limits if self.before else [])}
        return [LimitChange(limit=limit, before=before.get(limit.key)) for limit in self.after.limits]


class ClaudeCodeSettings(BaseModel):
    enabled: bool = False
    # Absolute path of the `claude` binary, "" when it is not installed.
    binary: str = ""
    # "" = the plan's default model.
    model: str = ""
    timeout: float = DEFAULT_TIMEOUT_S

    @property
    def usable(self) -> bool:
        return self.enabled and bool(self.binary)


# Apps opened from Finder have a minimal PATH: the macOS build records where `claude`
# is (macos/build_app.sh), and the native installer puts it in ~/.local/bin.
BINARY_VARIABLE = "SPEC_TO_TEST_CLAUDE_BIN"
FALLBACK_BINARY = Path.home() / ".local" / "bin" / "claude"


def _executable(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def find_binary(environ: Mapping[str, str] | None = None) -> str:
    values = environ if environ is not None else os.environ
    recorded = values.get(BINARY_VARIABLE, "").strip()
    if _executable(recorded):
        return recorded
    found = shutil.which("claude", path=values.get("PATH"))
    if found:
        return found
    return str(FALLBACK_BINARY) if _executable(str(FALLBACK_BINARY)) else ""


def _timeout(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    if value != value:  # NaN
        return DEFAULT_TIMEOUT_S
    low, high = TIMEOUT_RANGE_S
    return min(max(value, low), high)


def load_claude_code_settings(environ: Mapping[str, str] | None = None) -> ClaudeCodeSettings:
    """Read the opt-in from the environment (Streamlit secrets arrive there too)."""
    values = environ if environ is not None else os.environ
    if values.get(ENABLE_VARIABLE, "").strip().lower() not in _TRUE:
        return ClaudeCodeSettings()
    model = values.get(MODEL_VARIABLE, "").strip()
    return ClaudeCodeSettings(
        enabled=True,
        binary=find_binary(values),
        model=model if valid_model(model) else "",
        timeout=_timeout(values.get(TIMEOUT_VARIABLE, "").strip()),
    )


def child_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The CLI's environment: the user's, without API credentials, with the isolation switches."""
    source = environ if environ is not None else os.environ
    env = {k: v for k, v in source.items() if k not in REMOVED_VARIABLES and k not in SETTING_VARIABLES}
    return env | ADDED_VARIABLES


def run_cli(args: list[str], *, input: str, timeout: float, env: dict[str, str], cwd: str) -> Any:
    return subprocess.run(  # noqa: S603 - fixed argument list, no shell
        args, input=input, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env, cwd=cwd, check=False,
    )


def _default_runner(args: list[str], **kwargs: Any) -> Any:
    return run_cli(args, **kwargs)  # looked up at call time, so tests can replace run_cli


def failure_code(text: str, subtype: str = "") -> str:
    """The error code for a failed run, from Claude Code's own message."""
    if subtype == "error_max_turns":
        return "invalid_response"
    if _LIMIT.search(text):
        return "limit"
    if _RATE.search(text):
        return "rate_limit"
    if _AUTH.search(text):
        return "not_logged_in"
    return "failed"


def _json_lines(stdout: str) -> list[dict[str, Any]]:
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def token_usage(result: dict[str, Any]) -> TokenUsage:
    """The tokens of a result event (missing or odd values count as 0)."""
    raw_usage, raw_models = result.get("usage"), result.get("modelUsage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    models: dict[str, Any] = raw_models if isinstance(raw_models, dict) else {}
    cost = result.get("total_cost_usd")
    return TokenUsage(
        input_tokens=_int(usage.get("input_tokens")),
        output_tokens=_int(usage.get("output_tokens")),
        cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
        cache_creation_tokens=_int(usage.get("cache_creation_input_tokens")),
        models=[str(name)[:100] for name in models][:5],
        cost_usd_estimate=float(cost) if isinstance(cost, int | float) and cost >= 0 else 0.0,
        duration_ms=_int(result.get("duration_ms")),
    )


def plan_limits(events: list[dict[str, Any]]) -> list[PlanLimit] | None:
    """The plan's meters from the `/usage` report, or None when the report has none."""
    report = next((e["usage_report"] for e in events
                   if e.get("type") == "assistant" and isinstance(e.get("usage_report"), dict)), None)
    rate_limits = report.get("rate_limits") if report else None
    rows = rate_limits.get("limits") if isinstance(rate_limits, dict) else None
    if not isinstance(rows, list):
        return None
    limits = []
    for row in rows[:10]:
        if not isinstance(row, dict) or not isinstance(row.get("kind"), str):
            continue
        percent = row.get("percent")
        if not isinstance(percent, int | float) or isinstance(percent, bool):
            continue
        raw_scope = row.get("scope")
        scope: dict[str, Any] = raw_scope if isinstance(raw_scope, dict) else {}
        label = next((part.get("display_name") for part in scope.values()
                      if isinstance(part, dict) and isinstance(part.get("display_name"), str)), "")
        limits.append(PlanLimit(
            kind=row["kind"][:40], group=str(row.get("group") or "")[:40],
            percent=min(max(float(percent), 0.0), 100.0),
            resets_at=str(row.get("resets_at") or "")[:40], scope=str(label)[:60],
        ))
    return limits


# The text of `/usage`, for when its structured report has no limits (the field is
# experimental and is sometimes null while the text still has them), e.g.
# "Current session: 36% used · resets Oct 17 at 8:40pm (Europe/Warsaw)".
_USAGE_LINE = re.compile(
    r"^\s*Current (?P<what>session|week)(?: \((?P<scope>[^)]{1,60})\))?:\s*(?P<percent>\d{1,3}(?:\.\d+)?)% used"
    r"(?:\s*·\s*resets (?P<reset>[^\n(]+?)\s*(?:\((?P<tz>[A-Za-z_/+-]{1,40})\))?)?\s*$",
    re.M,
)


def _reset_from_text(text: str, tz: str, today: datetime | None = None) -> str:
    """"Oct 17 at 8:40pm" / "Oct 23 at 6am" in `tz` as ISO 8601, or "" when it cannot be read."""
    zone: tzinfo | None
    try:
        zone = ZoneInfo(tz) if tz else None
    except (ZoneInfoNotFoundError, ValueError):
        zone = None
    zone = zone or datetime.now().astimezone().tzinfo  # unknown zone: this computer's
    text = " ".join(text.replace(" at ", " ").split())
    today = today or datetime.now(zone)
    for pattern in ("%b %d %I:%M%p", "%b %d %I%p", "%I:%M%p", "%I%p"):
        try:
            parsed = datetime.strptime(text, pattern)  # %b and %p ignore case
        except ValueError:
            continue
        if "%b" in pattern:
            moment = parsed.replace(year=today.year, tzinfo=zone)
            if moment < today - timedelta(days=2):  # "Jan 2" read in late December
                moment = moment.replace(year=today.year + 1)
        else:
            moment = datetime.combine(today.date(), parsed.time(), tzinfo=zone)
        return moment.isoformat()
    return ""


def limits_from_text(text: str) -> list[PlanLimit]:
    limits: dict[str, PlanLimit] = {}
    for match in _USAGE_LINE.finditer(text):
        scope = (match.group("scope") or "").strip()
        if match.group("what") == "session":
            kind, group = "session", "session"
        else:
            kind, group = ("weekly_all", "weekly") if scope.casefold() in ("", "all models") else ("weekly_scoped", "weekly")
        limit = PlanLimit(
            kind=kind, group=group, percent=min(float(match.group("percent")), 100.0),
            resets_at=_reset_from_text(match.group("reset") or "", match.group("tz") or ""),
            scope="" if kind != "weekly_scoped" else scope[:60],
        )
        limits.setdefault(limit.key, limit)  # the text is in the message and again in the result
    return list(limits.values())[:10]


def _usage_text(events: list[dict[str, Any]]) -> str:
    parts = []
    for event in events:
        if event.get("type") == "assistant" and isinstance(event.get("message"), dict):
            content = event["message"].get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                parts += [b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
        elif event.get("type") == "result" and isinstance(event.get("result"), str):
            parts.append(event["result"])
    return "\n".join(parts)


def parse_output(text: Any, output: type[T]) -> T:
    if not isinstance(text, str):
        raise AIError("invalid_response")
    if fenced := _FENCED.match(text):
        text = fenced.group(1)
    elif 0 <= (start := text.find("{")) < (end := text.rfind("}")):
        text = text[start:end + 1]  # a sentence before or after the JSON object
    try:
        return output.model_validate_json(text)
    except ValidationError:
        raise AIError("invalid_response") from None


class ClaudeCodeProvider:
    """One `claude -p` request per call, answered with JSON validated against `output`.

    Has the StructuredProvider interface of spec_to_test.llm.providers.
    """

    def __init__(self, settings: ClaudeCodeSettings, runner: Runner | None = None,
                 environ: Mapping[str, str] | None = None) -> None:
        self.settings = settings
        self._run = runner or _default_runner
        self._environ = environ
        # Tokens of the last request that got an answer (also when the answer was unusable).
        self.last_usage: TokenUsage | None = None

    @property
    def label(self) -> str:
        return f"Claude Code · {self.settings.model}" if self.settings.model else "Claude Code"

    def _call(self, args: list[str], stdin: str, timeout: float) -> Any:
        if not self.settings.enabled:
            raise AIError("disabled")
        if not self.settings.binary:
            raise AIError("missing")
        with tempfile.TemporaryDirectory(prefix="spec-to-test-claude-") as empty_dir:
            try:
                return self._run([self.settings.binary, *args], input=stdin, timeout=timeout,
                                 env=child_environment(self._environ), cwd=empty_dir)
            except subprocess.TimeoutExpired:
                raise AIError("timeout") from None  # subprocess.run has killed the CLI
            except OSError:
                raise AIError("missing") from None

    def check_login(self) -> str:
        """The plan type ("pro", "max", ...) of a claude.ai login. Raises AIError otherwise.

        Only the login method, provider and plan are read from the status.
        """
        completed = self._call(["auth", "status", "--json"], "", STATUS_TIMEOUT_S)
        try:
            status = json.loads(completed.stdout or "")
        except ValueError:
            status = None
        if not isinstance(status, dict):
            raise AIError("not_logged_in" if completed.returncode else "invalid_response")
        if status.get("loggedIn") is not True:
            raise AIError("not_logged_in")
        if status.get("authMethod") != "claude.ai" or status.get("apiProvider", "firstParty") != "firstParty":
            raise AIError("not_subscription")
        plan = status.get("subscriptionType")
        return plan if isinstance(plan, str) and re.fullmatch(r"[a-z_]{1,20}", plan) else ""

    def plan_usage(self, checked_at: str = "") -> PlanUsage | None:
        """The plan's limits via the local `/usage` command (no model request, no tokens).

        Slash commands must be allowed for this one call; tools stay off. Returns
        None when the limits cannot be read (no claude.ai login, older CLI, error).
        """
        args = ["-p", "--output-format", "stream-json", "--verbose",
                *(flag for flag in ISOLATION_FLAGS if flag != "--disable-slash-commands")]
        try:
            completed = self._call(args, "/usage", STATUS_TIMEOUT_S)
        except AIError:
            return None
        stdout = completed.stdout or ""
        if completed.returncode or len(stdout) > MAX_OUTPUT_CHARS:
            return None
        events = _json_lines(stdout)
        init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
        if init.get("apiKeySource", "none") != "none":
            return None
        limits = plan_limits(events) or limits_from_text(_usage_text(events))
        return PlanUsage(limits=limits, checked_at=checked_at) if limits else None

    def command(self, system: str) -> list[str]:
        args = ["-p", "--output-format", "stream-json", "--verbose", *ISOLATION_FLAGS, "--system-prompt", system]
        if self.settings.model:
            args += ["--model", self.settings.model]
        return args

    def request(self, system: str, user: str, output: type[T], max_tokens: int = 0) -> T:
        """`max_tokens` is accepted for the StructuredProvider interface; the CLI sets its own."""
        self.last_usage = None
        self.check_login()
        completed = self._call(self.command(system), user, self.settings.timeout)
        stdout = completed.stdout or ""
        if len(stdout) > MAX_OUTPUT_CHARS:
            raise AIError("invalid_response")
        events = _json_lines(stdout)
        init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
        if init.get("apiKeySource", "none") != "none":
            raise AIError("not_subscription")  # an API key was used despite the checks
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        if result is None:
            if completed.returncode:
                raise AIError(failure_code(f"{stdout}\n{completed.stderr or ''}"))
            raise AIError("invalid_response")
        self.last_usage = token_usage(result)
        subtype = str(result.get("subtype") or "")
        if result.get("is_error") or subtype != "success":
            raise AIError(failure_code(str(result.get("result") or ""), subtype))
        return parse_output(result.get("result"), output)
