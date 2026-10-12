"""Test doubles for the automation pipeline (unit tests only; production uses the real ones)."""

import copy
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from spec_to_test.automation.browser import ToolOutcome
from spec_to_test.automation.config import load_automation_config
from spec_to_test.automation.models import Artifact, RunResult, TestOutcome
from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestType

PUBLIC_IP = "93.184.216.34"
SECRET_VALUE = "Hunter-2-pass"
SECRET_NAME = "STAGING_PASSWORD"
# Built at runtime so the repository secret scan (test_security.py) does not flag a fake key.
FAKE_API_KEY = "sk-ant-" + "api03-" + "0" * 24

TC = TestCase(
    id="TC-001", requirement_id="REQ-001", title="Expired link is rejected", test_type=TestType.NEGATIVE,
    preconditions=["A reset link was sent"],
    steps=["Open the expired reset link", "Submit a new password"],
    expected_result='The error "Link expired" is shown and the password is not changed.',
    assumptions=["Links expire after 15 minutes"],
    review_status=ReviewStatus.APPROVED,
)
REQ = Requirement(id="REQ-001", text="A reset link expires after 15 minutes; an expired link shows \"Link expired\".")


def resolver(table: dict[str, list[str]] | None = None) -> Callable[..., list[tuple]]:
    """getaddrinfo stand-in: host -> addresses (default: one public address)."""
    table = table or {}

    def resolve(host: str, port: int, *args: Any) -> list[tuple]:
        if host in table:
            addresses = table[host]
        elif host.endswith(".invalid"):
            raise socket.gaierror("not found")
        else:
            addresses = [PUBLIC_IP]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]

    return resolve


def config(tmp_path: Path, **overrides: str):
    env = {
        "AUTOMATION_ALLOWED_HOSTS": "staging.example.com",
        "AUTOMATION_DATA_DIR": str(tmp_path / "automation"),
        "AUTOMATION_SECRET_STAGING_PASSWORD": SECRET_VALUE,
    }
    env.update(overrides)
    return load_automation_config(env)


def step(action: str, strategy: str = "page", role: str = "", target: str = "", value: str = "",
         secret: str = "", tc_step: int = 0, evidence: str = "", exact: bool = False) -> dict[str, Any]:
    return dict(action=action, strategy=strategy, role=role, target=target, exact=exact, value=value,
                secret=secret, tc_step=tc_step, evidence=evidence)


def good_script(button: str = "Save password") -> dict[str, Any]:
    return {
        "title": "Expired link",
        "notes": "",
        "steps": [
            step("goto", value="/reset?token=expired", tc_step=1),
            step("fill", "label", target="New password", secret=SECRET_NAME, tc_step=2),
            step("click", "role", role="button", target=button, tc_step=2),
            step("expect_text", "role", role="alert", value="Link expired", tc_step=-1,
                 evidence='The error "Link expired" is shown'),
        ],
    }


def tool_use(call_id: str, name: str, **arguments: Any) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=arguments)


def text(value: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=value)


class FakeAgent:
    """Returns scripted turns; each turn is a list of blocks or a function of the messages."""

    def __init__(self, *turns: Any, model: str = "fake-model", error: Exception | None = None,
                 delay: threading.Event | None = None) -> None:
        self.turns = list(turns)
        self.model = model
        self.error = error
        self.delay = delay
        self.requests: list[dict[str, Any]] = []

    def create(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        self.requests.append({"system": system, "messages": copy.deepcopy(messages), "tools": tools})
        if self.delay is not None:
            self.delay.wait(10)
        if self.error is not None:
            raise self.error
        if not self.turns:
            raise AssertionError("the fake agent ran out of turns")
        turn = self.turns.pop(0)
        content = turn(messages) if callable(turn) else turn
        return SimpleNamespace(content=content, stop_reason="tool_use",
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0))

    def tool_results(self, request: int = -1) -> list[dict[str, Any]]:
        content = self.requests[request]["messages"][-1]["content"]
        return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]


SNAPSHOT = """### Page
- Page URL: https://staging.example.com/reset
### Snapshot
```yaml
- textbox "New password" [ref=e3]
- button "Save password" [ref=e4]
- button "Delete account" [ref=e5]
```"""

SERVER_TOOLS = [
    SimpleNamespace(name=name, description=f"{name} tool",
                    input_schema={"$schema": "x", "type": "object",
                                  "properties": {"url": {"type": "string"}, "element": {"type": "string"},
                                                 "target": {"type": "string"}, "text": {"type": "string"},
                                                 "filename": {"type": "string"}, "code": {"type": "string"}},
                                  "required": ["url"] if name == "browser_navigate" else []})
    for name in ("browser_navigate", "browser_snapshot", "browser_click", "browser_type",
                 "browser_run_code_unsafe", "browser_evaluate", "browser_file_upload", "browser_network_requests")
]


class FakeBrowser:
    instances: list["FakeBrowser"] = []

    def __init__(self, policy: Any, config: Any, secrets: dict[str, str], private_dir: Path,
                 fail: bool = False, outputs: dict[str, str] | None = None) -> None:
        self.policy = policy
        self.secrets = secrets
        self.private_dir = private_dir
        self.fail = fail
        self.outputs = outputs or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        self.tools = SERVER_TOOLS
        FakeBrowser.instances.append(self)

    async def __aenter__(self) -> "FakeBrowser":
        if self.fail:
            raise FileNotFoundError("node")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.calls.append((name, arguments))
        return ToolOutcome(text=self.outputs.get(name, SNAPSHOT))


def browser_factory(**options: Any) -> Callable[..., FakeBrowser]:
    return lambda policy, config, secrets, private_dir: FakeBrowser(policy, config, secrets, private_dir, **options)


def passed_run() -> RunResult:
    return RunResult(exit_code=0, passed=True, duration_ms=1200,
                     tests=[TestOutcome(title="TC-001: Expired link is rejected", status="passed", duration_ms=900)])


def failed_run(error: str = "locator.click: Timeout 15000ms exceeded waiting for getByRole('button', { name: 'Save' })") -> RunResult:
    return RunResult(exit_code=1, passed=False, duration_ms=16000,
                     tests=[TestOutcome(title="TC-001: Expired link is rejected", status="failed", error=error,
                                        error_location="tc-001.spec.ts:18")])


class FakeRunner:
    def __init__(self, *results: RunResult, block: threading.Event | None = None) -> None:
        self.results = list(results)
        self.block = block
        self.runs: list[dict[str, Any]] = []

    def run(self, job_dir: Path, secrets: dict[str, str], redact: Any, cancel: threading.Event):
        self.runs.append({"code": next((job_dir / "tests").glob("*.spec.ts")).read_text(), "secrets": dict(secrets),
                          "config": (job_dir / "playwright.config.ts").read_text()})
        if self.block is not None:
            while not cancel.is_set():
                self.block.wait(0.05)
            from spec_to_test.automation.runner import RunCancelled
            raise RunCancelled
        (job_dir / "report").mkdir(exist_ok=True)
        (job_dir / "report" / "results.json").write_text("{}")
        result = self.results.pop(0)
        return result, [Artifact(kind="report", path="report/results.json", size=2)]
