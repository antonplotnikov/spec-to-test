"""End-to-end: real Playwright MCP browser, real sandboxed test run, scripted model.

Only Claude is replaced (by a scripted agent that issues the tool calls a model
would); the MCP server, the browser gate, the TypeScript generator, the runner
and the report parser are the production ones, against a local staging page.
Skipped when the Node toolchain (automation/runner) or the `mcp` package is missing.
"""

import importlib.util
import re
import shutil
import subprocess
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from spec_to_test.automation.browser import PlaywrightMCPBrowser
from spec_to_test.automation.config import DEFAULT_RUNNER_DIR, load_automation_config
from spec_to_test.automation.models import AutomationJob, JobStatus
from spec_to_test.automation.orchestrator import JobContext, Orchestrator
from spec_to_test.automation.runner import PlaywrightRunner
from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestType

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        shutil.which("node") is None
        or not (DEFAULT_RUNNER_DIR / "node_modules" / "@playwright" / "mcp").is_dir()
        or importlib.util.find_spec("mcp") is None,
        reason="Automation toolchain not installed (see README: Automation setup)",
    ),
]

PASSWORD = "pa55-Word!"
SECRET_NAME = "STAGING_PASSWORD"
SITE = f"""<!doctype html><html><head><title>Staging Login</title></head><body>
<h1>Sign in</h1>
<form id="f"><label>Email <input name="email" type="email"></label>
<label>Password <input name="password" type="password"></label>
<button type="submit">Sign in</button></form>
<button type="button">Delete account</button>
<a href="http://example.com/">External docs</a>
<div role="alert" id="msg"></div>
<script>
document.getElementById('f').addEventListener('submit', e => {{ e.preventDefault();
  const ok = e.target.password.value === '{PASSWORD}';
  document.getElementById('msg').textContent = ok ? 'Welcome back' : 'Invalid email or password';
}});
</script></body></html>"""

TC = TestCase(
    id="TC-001", requirement_id="REQ-001", title="Sign in with a valid password", test_type=TestType.POSITIVE,
    steps=["Open the sign-in page", "Enter the email and the valid password", "Click Sign in"],
    expected_result='The message "Welcome back" is shown.', review_status=ReviewStatus.APPROVED,
)
REQ = Requirement(id="REQ-001", text='After signing in with a valid password the user sees "Welcome back".')


@pytest.fixture
def staging(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text(SITE, encoding="utf-8")
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *args: None  # type: ignore[attr-defined]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def tool_use(index: int, name: str, **arguments) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=f"call_{index}", name=name, input=arguments)


def ref(text: str, pattern: str) -> str:
    match = re.search(pattern + r".*?\[ref=(e\d+)\]", text)
    assert match, f"{pattern!r} not in snapshot:\n{text[:2000]}"
    return match.group(1)


def step(action, strategy="page", role="", target="", value="", secret="", tc_step=0, evidence="", exact=False):
    return dict(action=action, strategy=strategy, role=role, target=target, exact=exact, value=value,
                secret=secret, tc_step=tc_step, evidence=evidence)


def script(button_name: str) -> dict:
    return {
        "title": "Valid sign-in",
        "notes": "",
        "steps": [
            step("goto", value="/", tc_step=1),
            step("fill", "label", target="Email", value="qa@example.com", tc_step=2),
            step("fill", "label", target="Password", secret=SECRET_NAME, tc_step=2),
            step("click", "role", role="button", target=button_name, tc_step=3),
            step("expect_text", "role", role="alert", value="Welcome back", tc_step=-1,
                 evidence='The message "Welcome back" is shown'),
        ],
    }


class ScriptedAgent:
    """Plays the model: explores with real tool calls, then submits a script."""

    model = "scripted-test-agent"

    def __init__(self, first_button: str) -> None:
        self.first_button = first_button
        self.turn = 0
        self.seen: list[str] = []
        self.systems: list[str] = []

    def last_results(self, messages) -> list[dict]:
        content = messages[-1]["content"]
        return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"] if isinstance(content, list) else []

    def create(self, system, messages, tools):
        self.systems.append(system)
        self.turn += 1
        results = self.last_results(messages)
        self.seen += [r["content"] for r in results]
        names = {t["name"] for t in tools}
        assert "browser_run_code_unsafe" not in names and "browser_evaluate" not in names
        assert {"browser_navigate", "browser_snapshot", "submit_test_script", "report_blocker"} <= names
        if self.turn == 1:
            calls = [tool_use(1, "browser_navigate", url="/"), tool_use(2, "browser_navigate", url="http://example.com/")]
        elif self.turn == 2:
            calls = [tool_use(3, "browser_snapshot")]
        elif self.turn == 3:
            snapshot = results[0]["content"]
            calls = [
                tool_use(4, "browser_type", element="Email", target=ref(snapshot, r'textbox "Email"'), text="qa@example.com"),
                tool_use(5, "browser_type", element="Password", target=ref(snapshot, r'textbox "Password"'), text=SECRET_NAME),
                tool_use(6, "browser_click", element="Sign in button", target=ref(snapshot, r'button "Sign in"')),
                tool_use(7, "browser_click", element="the button", target=ref(snapshot, r'button "Delete account"')),
                tool_use(8, "browser_snapshot"),
            ]
        elif self.turn == 4:
            calls = [tool_use(9, "submit_test_script", **script(self.first_button))]
        else:  # repair turn: fix the locator, keep the assertion
            calls = [tool_use(10, "browser_snapshot"), tool_use(11, "submit_test_script", **script("Sign in"))]
        return SimpleNamespace(content=calls, stop_reason="tool_use", usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def run_job(tmp_path, staging, agent) -> AutomationJob:
    config = load_automation_config(
        {
            "AUTOMATION_ALLOWED_HOSTS": staging,
            "AUTOMATION_ALLOW_PRIVATE_NETWORK": "true",
            "AUTOMATION_SECRET_STAGING_PASSWORD": PASSWORD,
            "AUTOMATION_DATA_DIR": str(tmp_path / "automation"),
            "AUTOMATION_RUN_TIMEOUT": "120",
        }
    )
    job = AutomationJob(id="0123456789abcdef", owner="o", test_case_id=TC.id, requirement_id=REQ.id,
                        target_url=f"http://{staging}/", model=agent.model)
    job_dir = config.artifacts_dir / "jobs" / job.id
    job_dir.mkdir(parents=True)
    saved: list[str] = []
    context = JobContext(job=job, test_case=TC, requirement=REQ, config=config, job_dir=job_dir,
                         save=lambda j: saved.append(j.status.value))
    orchestrator = Orchestrator(agent, PlaywrightMCPBrowser, PlaywrightRunner(config), check_prerequisites=False)
    private_dirs = set(Path("/tmp").glob("stt-*"))
    result = orchestrator.run(context)
    leftovers = set(Path("/tmp").glob("stt-*")) - private_dirs
    assert not leftovers, "sandbox folders (MCP config with secret values) must be removed"
    return result


def test_explore_generate_run_passes_with_real_browser(tmp_path, staging):
    agent = ScriptedAgent(first_button="Sign in")
    job = run_job(tmp_path, staging, agent)
    assert job.status == JobStatus.PASSED, (job.reason, job.reason_params, job.runs and job.runs[-1].failure_summary())
    assert job.reason == "passed" and not job.repair_attempted
    observed = "\n".join(agent.seen)
    # Navigation away from staging and destructive clicks never reach the browser.
    assert "Navigation refused" in observed
    assert "'delete' looks like a destructive" in observed
    # The secret was typed by name, worked, and its value never reached the model.
    assert "Welcome back" in observed
    assert PASSWORD not in observed and PASSWORD not in "".join(agent.systems)
    assert 'secret("STAGING_PASSWORD")' in job.code and PASSWORD not in job.code
    assert job.tool_calls == 6  # refused calls are not counted
    kinds = {a.kind for a in job.artifacts}
    assert {"spec", "config", "report", "trace", "screenshot", "log"} <= kinds
    assert job.assertion_checks[0].status == "verified"
    run = job.last_run
    assert run and run.passed and run.tests[0].status == "passed"


def test_failed_run_gets_one_repair_that_keeps_assertions(tmp_path, staging):
    agent = ScriptedAgent(first_button="Log in")  # wrong locator: the first run fails
    job = run_job(tmp_path, staging, agent)
    assert job.status == JobStatus.PASSED and job.reason == "passed_after_repair", job.reason
    assert job.repair_attempted and len(job.runs) == 2
    assert not job.runs[0].passed and "Log in" in job.runs[0].failure_summary()
    assert job.runs[1].passed


class LinkClickingAgent:
    """Clicks a link to another site (which the navigation gate cannot see)."""

    model = "scripted-test-agent"

    def __init__(self) -> None:
        self.turn = 0
        self.seen: list[str] = []

    def create(self, system, messages, tools):
        self.turn += 1
        content = messages[-1]["content"]
        if isinstance(content, list):
            self.seen += [b["content"] for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
        if self.turn == 1:
            calls = [tool_use(1, "browser_navigate", url="/"), tool_use(2, "browser_snapshot")]
        elif self.turn == 2:
            calls = [tool_use(3, "browser_click", element="External docs link", target=ref(self.seen[-1], r'link "External docs"'))]
        else:
            calls = [tool_use(4, "report_blocker", reason="other", details="checked egress")]
        return SimpleNamespace(content=calls, stop_reason="tool_use", usage=None)


def test_browser_cannot_leave_staging_by_following_a_link(tmp_path, staging):
    agent = LinkClickingAgent()
    job = run_job(tmp_path, staging, agent)
    assert job.status == JobStatus.BLOCKED and job.reason == "ai_blocker"
    assert "ERR_PROXY_CONNECTION_FAILED" in agent.seen[-1] or "chrome-error" in agent.seen[-1], agent.seen[-1]
    assert "Example Domain" not in agent.seen[-1]


def test_mcp_server_that_never_answers_blocks_the_job_quickly(tmp_path, staging, monkeypatch):
    """A hung MCP server must end the job with a clear reason, not hang it (and leave no process)."""
    from spec_to_test.automation import browser as browser_module

    silent = tmp_path / "runner" / "node_modules" / "@playwright" / "mcp" / "cli.js"
    silent.parent.mkdir(parents=True)
    silent.write_text("setInterval(() => {}, 1000);  // reads nothing, answers nothing\n")
    (tmp_path / "runner" / "node_modules" / "@playwright" / "test").mkdir(parents=True)
    monkeypatch.setattr(browser_module, "START_TIMEOUT_SECONDS", 2)
    config = load_automation_config({
        "AUTOMATION_ALLOWED_HOSTS": staging, "AUTOMATION_ALLOW_PRIVATE_NETWORK": "true",
        "AUTOMATION_DATA_DIR": str(tmp_path / "automation"), "AUTOMATION_RUNNER_DIR": str(tmp_path / "runner"),
    })
    job = AutomationJob(id="0123456789abcdee", owner="o", test_case_id=TC.id, requirement_id=REQ.id,
                        target_url=f"http://{staging}/")
    job_dir = config.artifacts_dir / "jobs" / job.id
    job_dir.mkdir(parents=True)
    context = JobContext(job=job, test_case=TC, requirement=REQ, config=config, job_dir=job_dir, save=lambda j: None)
    started = time.monotonic()
    result = Orchestrator(ScriptedAgent("Sign in"), PlaywrightMCPBrowser, PlaywrightRunner(config),
                          check_prerequisites=False).run(context)
    assert result.status == JobStatus.BLOCKED and result.reason == "browser_unavailable"
    assert time.monotonic() - started < 30
    leftover = subprocess.run(["pgrep", "-f", str(silent)], capture_output=True, text=True).stdout.strip()
    assert not leftover, "the MCP server process must be stopped"
