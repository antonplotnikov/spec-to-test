"""Playwright MCP browser used by Claude to explore the staging UI.

The MCP server runs as a local child process (stdio) in the same sandbox as
test runs: pinned egress, private HOME, resource limits, headless Chromium,
an in-memory profile and secrets known only by name. Claude gets a reduced
tool set - no script evaluation, no file access, no network inspection - and
every call passes through `BrowserGate` before it reaches the server:
- navigation only to the vetted origin,
- clicks and key presses on elements that look destructive are refused
  unless the user allowed destructive actions for this job,
- output is masked (secrets, credentials) and capped in size.
"""

import json
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import anyio
from pydantic import BaseModel

from spec_to_test.automation.config import AutomationConfig
from spec_to_test.automation.sandbox import limited_command, node_command, sandbox_env
from spec_to_test.automation.security import (
    BLOCKING_PROXY,
    EgressPolicy,
    Redactor,
    UrlRejected,
    check_navigation,
    destructive_term,
)

# Tools Claude may use, and the arguments it may pass (others are dropped).
EXPLORATION_TOOLS: dict[str, set[str]] = {
    "browser_navigate": {"url"},
    "browser_navigate_back": set(),
    "browser_snapshot": {"target", "depth"},
    "browser_click": {"element", "target", "doubleClick", "button", "modifiers"},
    "browser_type": {"element", "target", "text", "submit", "slowly"},
    "browser_fill_form": {"fields"},
    "browser_select_option": {"element", "target", "values"},
    "browser_press_key": {"key"},
    "browser_hover": {"element", "target"},
    "browser_wait_for": {"time", "text", "textGone"},
    "browser_handle_dialog": {"accept", "promptText"},
    "browser_find": {"text", "regex"},
    "browser_console_messages": {"level", "all"},
}
# Interactions whose target is checked for destructive wording.
GATED_INTERACTIONS = {"browser_click", "browser_press_key", "browser_select_option", "browser_handle_dialog"}
MAX_RESULT_CHARS = 30_000
MAX_WAIT_SECONDS = 10
TOOL_TIMEOUT_SECONDS = 90
START_TIMEOUT_SECONDS = 60  # MCP handshake; a server that never answers must not hang the job
REF_LINE = re.compile(r"^\s*-\s*(?P<text>.*?)\s*\[ref=(?P<ref>e\d+)\]", re.M)


class ToolOutcome(BaseModel):
    text: str
    is_error: bool = False


class BrowserGate:
    """Checks and rewrites tool calls. Pure logic, so it is unit-tested without a browser."""

    def __init__(self, policy: EgressPolicy, redact: Redactor, allow_destructive: bool) -> None:
        self.policy = policy
        self.redact = redact
        self.allow_destructive = allow_destructive
        # Accessible names by snapshot ref, so a click is judged by what it really targets.
        self.refs: dict[str, str] = {}

    def tool_definitions(self, server_tools: list[Any]) -> list[dict[str, Any]]:
        """Anthropic tool definitions for the allowed subset of the server's tools."""
        definitions = []
        for tool in server_tools:
            allowed = EXPLORATION_TOOLS.get(tool.name)
            if allowed is None:
                continue
            schema = dict(tool.input_schema or {"type": "object"})
            schema.pop("$schema", None)
            props = {k: v for k, v in (schema.get("properties") or {}).items() if k in allowed}
            schema["properties"] = props
            if "required" in schema:
                schema["required"] = [r for r in schema["required"] if r in props]
            definitions.append(
                {"name": tool.name, "description": (tool.description or tool.name)[:1000], "input_schema": schema}
            )
        return sorted(definitions, key=lambda d: d["name"])  # stable order keeps the prompt cache valid

    def check(self, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        """Return (sanitized arguments, refusal message or None)."""
        if name not in EXPLORATION_TOOLS:
            return arguments, f"The tool {name} is not available."
        args = {k: v for k, v in (arguments or {}).items() if k in EXPLORATION_TOOLS[name]}
        if name == "browser_navigate":
            try:
                args["url"] = check_navigation(str(args.get("url", "")), self.policy)
            except UrlRejected:
                return args, (
                    "Navigation refused: only pages on the staging site under test may be opened "
                    f"({', '.join(self.policy.allowed_origins())})."
                )
        if name == "browser_wait_for" and "time" in args:
            try:
                args["time"] = min(float(args["time"]), MAX_WAIT_SECONDS)
            except (TypeError, ValueError):
                args.pop("time")
        if name in GATED_INTERACTIONS and not self.allow_destructive:
            described = " ".join(
                str(args.get(key, "")) for key in ("element", "key", "promptText") if args.get(key)
            )
            if name == "browser_select_option":
                described += " " + " ".join(map(str, args.get("values") or []))
            target_name = self.refs.get(str(args.get("target", "")), "")
            term = destructive_term(f"{described} {target_name}")
            if term:
                return args, (
                    f"Refused: '{term}' looks like a destructive or irreversible action, and the QA engineer "
                    "did not allow destructive actions for this run. If the test case cannot be automated "
                    "without it, call report_blocker with reason \"destructive_action\"."
                )
        return args, None

    def observe(self, text: str) -> str:
        """Remember element names from a snapshot, mask secrets and cap the size."""
        for match in REF_LINE.finditer(text):
            self.refs[match.group("ref")] = match.group("text")
        text = self.redact(text)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "\n[Output truncated. Use browser_snapshot with a `target` to see a part of the page.]"
        return text


def mcp_server_config(policy: EgressPolicy, config: AutomationConfig, secrets: dict[str, str], output_dir: Path) -> dict[str, Any]:
    return {
        "browser": {
            "browserName": "chromium",
            "isolated": True,
            "launchOptions": {
                "headless": True,
                "chromiumSandbox": config.chromium_sandbox,
                "args": policy.browser_args(),
            },
            "contextOptions": {
                "viewport": {"width": 1280, "height": 720},
                "serviceWorkers": "block",
                "acceptDownloads": False,
                "ignoreHTTPSErrors": config.ignore_https_errors,
            },
        },
        "capabilities": ["core"],
        "network": {"allowedOrigins": policy.allowed_origins()},
        "secrets": secrets,
        "outputDir": str(output_dir),
        "timeouts": {"action": 10_000, "navigation": 30_000},
    }


class PlaywrightMCPBrowser:
    """An MCP client session with the Playwright MCP server. Use `async with`."""

    def __init__(
        self, policy: EgressPolicy, config: AutomationConfig, secrets: dict[str, str], private_dir: Path
    ) -> None:
        self.policy = policy
        self.config = config
        self.secrets = secrets
        self.private_dir = private_dir
        self._stack = AsyncExitStack()
        self._session: Any = None
        self.tools: list[Any] = []

    async def __aenter__(self) -> "PlaywrightMCPBrowser":
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self.private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        config_path = self.private_dir / "mcp-config.json"
        # The config holds secret values: private folder, owner-only, removed after the job.
        config_path.touch(mode=0o600)
        config_path.write_text(
            json.dumps(mcp_server_config(self.policy, self.config, self.secrets, self.private_dir / "output")),
            encoding="utf-8",
        )
        command = limited_command(
            node_command(
                self.config, self.config.mcp_cli, "--config", str(config_path),
                # Given as flags: the server ignores `bypass` in launchOptions.proxy.
                "--proxy-server", BLOCKING_PROXY, "--proxy-bypass", self.policy.proxy_bypass(),
            ),
            cpu_seconds=self.config.job_timeout * 4,
        )
        params = StdioServerParameters(
            command=command[0], args=command[1:], env=sandbox_env(self.private_dir), cwd=str(self.private_dir)
        )
        try:
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            with anyio.fail_after(START_TIMEOUT_SECONDS):  # plain awaits only, no context entry inside
                await self._session.initialize()
                self.tools = list((await self._session.list_tools()).tools)
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        result = await self._session.call_tool(name, arguments, read_timeout_seconds=TOOL_TIMEOUT_SECONDS)
        parts = []
        for block in getattr(result, "content", None) or []:
            if getattr(block, "type", "") == "text":
                parts.append(block.text)
            else:
                parts.append(f"[{getattr(block, 'type', 'content')} omitted]")
        return ToolOutcome(text="\n".join(parts), is_error=bool(getattr(result, "is_error", False)))
