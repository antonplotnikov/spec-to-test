"""QA Agent against a real browser: Python Playwright + Chromium and the local Demo Shop.

Skipped when Playwright or its Chromium is not installed
(pip install -r requirements-qa.txt && python -m playwright install chromium).
Every status asserted here comes from an actual browser run.
"""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import PROJECT_ROOT
from spec_to_test.models import Severity
from spec_to_test.qa_agent import planner
from spec_to_test.qa_agent.executor import SCREENSHOT_WITHHELD
from spec_to_test.qa_agent.models import PlanCase, RunStatus
from spec_to_test.qa_agent.safety import load_qa_settings
from spec_to_test.qa_agent.service import run_cases
from spec_to_test.qa_agent.steps import parse_steps
from spec_to_test.qa_agent.store import RunStore

PASSWORD = "demo-pass-123"
DEMO = PROJECT_ROOT / "examples" / "qa_demo"


def _chromium_works() -> bool:
    if importlib.util.find_spec("playwright") is None:
        return False
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception:  # noqa: BLE001 - browser not installed
        return False
    return True


pytestmark = pytest.mark.skipif(not _chromium_works(), reason="Playwright Chromium is not installed")


class _Internal(BaseHTTPRequestHandler):
    """Stands in for an internal service the browser must never reach."""

    hits: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        self.hits.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"internal secret")

    def log_message(self, *args) -> None:
        return


def _serve(server: ThreadingHTTPServer):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture(scope="module")
def internal():
    _Internal.hits = []
    server = _serve(ThreadingHTTPServer(("127.0.0.1", 0), _Internal))
    server.hits = _Internal.hits  # every request the internal service received
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def demo(internal):
    import sys

    sys.path.insert(0, str(DEMO))
    from server import make_server  # examples/qa_demo/server.py

    server = _serve(make_server(port=0, password=PASSWORD, other_port=internal.server_address[1]))
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


def settings(url: str, **extra: str):
    port = url.rsplit(":", 1)[1].strip("/")
    return load_qa_settings({
        "AUTOMATION_ALLOWED_HOSTS": f"127.0.0.1:{port}",
        "AUTOMATION_ALLOW_PRIVATE_NETWORK": "true",
        "AUTOMATION_SECRET_DEMO_PASSWORD": PASSWORD,
        "QA_STEP_TIMEOUT_MS": "3000",
        **extra,
    })


def demo_cases() -> list[PlanCase]:
    plan = planner.import_plan((DEMO / "plan.json").read_bytes(), "")
    for case in plan.cases:
        planner.approve(case)
    return plan.cases


def case(case_id: str, steps: str, approve: bool = True) -> PlanCase:
    found = PlanCase(id=case_id, requirement_id="REQ-9", title=case_id, steps=parse_steps(steps))
    if approve:
        planner.approve(found)
    return found


def test_demo_plan_real_pass_fail_and_blocks(demo, internal, tmp_path):
    store = RunStore(tmp_path)
    progress: list[tuple[int, int, str]] = []
    run = run_cases(demo_cases(), demo, settings(demo), store, authorized=True,
                    on_progress=lambda done, total, r: progress.append((done, total, r.status.value)))
    statuses = {r.case_id: (r.status, r.reason) for r in run.results}
    assert statuses == {
        "QA-001": (RunStatus.PASSED, ""),
        "QA-002": (RunStatus.PASSED, ""),  # signs in with the secret from the environment
        "QA-003": (RunStatus.PASSED, ""),
        "QA-004": (RunStatus.FAILED, "assertion"),  # the deliberate bug: an empty email is accepted
        "QA-005": (RunStatus.BLOCKED, "destructive"),  # "Delete account" is never clicked
        "QA-006": (RunStatus.BLOCKED, "redirect"),  # redirect to another local port is stopped
    }
    assert [p[0] for p in progress] == [1, 2, 3, 4, 5, 6]
    assert internal.hits == []  # the redirect never reached the other service
    assert run.browser.startswith("Chromium")

    failed = run.result("QA-004")
    assert "Email is required" in failed.error
    assert "Thanks, Alex! We will reply soon." in failed.actual_result  # observed on the page, not invented
    for result in run.results:
        path = store.evidence(run, result.screenshot)
        assert path is not None and path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", result.case_id

    assert [b.case_id for b in run.bugs] == ["QA-004"]
    bug = run.bugs[0]
    assert bug.steps_to_reproduce[-1] == 'Verify the page shows "Email is required"'
    assert "Clear \"Email\"" in bug.steps_to_reproduce and bug.evidence[0] == f"screenshot: {failed.screenshot}"

    saved = (store.run_dir(run.id) / "run.json").read_text(encoding="utf-8")
    assert PASSWORD not in saved
    assert store.load(run.id) == run


def test_page_scripts_cannot_reach_other_hosts(demo, internal, tmp_path):
    run = run_cases([case("QA-1", "goto /leak\nexpect_text Leak test")], demo, settings(demo), RunStore(tmp_path),
                    authorized=True)
    result = run.results[0]
    assert result.status == RunStatus.PASSED
    assert internal.hits == []
    assert any("/steal" in url for url in result.blocked_requests)


def test_server_error_fails_with_a_high_severity_bug(demo, tmp_path):
    run = run_cases([case("QA-1", "goto /broken\nexpect_text Anything")], demo, settings(demo), RunStore(tmp_path),
                    authorized=True)
    assert (run.results[0].status, run.results[0].reason) == (RunStatus.FAILED, "http_status")
    assert run.bugs[0].severity == Severity.HIGH


def test_missing_element_is_a_failure_with_the_playwright_error(demo, tmp_path):
    run = run_cases([case("QA-1", "goto /login\nclick role=button[name=Register]\nexpect_text x")], demo,
                    settings(demo), RunStore(tmp_path), authorized=True)
    result = run.results[0]
    assert (result.status, result.reason) == (RunStatus.FAILED, "action_error")
    assert "Timeout" in result.error and result.steps[-1].status == RunStatus.FAILED


def test_destructive_actions_run_only_when_allowed(demo, tmp_path):
    cases = [c for c in demo_cases() if c.id == "QA-005"]
    run = run_cases(cases, demo, settings(demo), RunStore(tmp_path), authorized=True, allow_destructive=True)
    assert run.results[0].status == RunStatus.PASSED and run.allow_destructive


def test_secrets_typed_into_the_page_are_redacted_everywhere(demo, tmp_path):
    leaky = case("QA-1", "goto /contact\nfill label=Name | {{secret:DEMO_PASSWORD}}\nclick role=button[name=Send]\n"
                         "expect_text Something else")
    store = RunStore(tmp_path)
    run = run_cases([leaky], demo, settings(demo), store, authorized=True)
    result = run.results[0]
    assert result.status == RunStatus.FAILED
    assert "[redacted:DEMO_PASSWORD]" in result.actual_result
    assert result.screenshot == SCREENSHOT_WITHHELD  # the page displays the secret: no image of it
    assert not list(store.run_dir(run.id).glob("*.png"))
    assert run.bugs[0].evidence[0] == "screenshot: withheld (the page showed a secret value)"
    assert PASSWORD not in json.dumps(run.model_dump(mode="json"))
    assert PASSWORD not in (store.run_dir(run.id) / "run.json").read_text(encoding="utf-8")


def test_unapproved_changed_and_over_limit_cases_are_not_run(demo, tmp_path):
    changed = case("QA-2", "goto /\nexpect_text Demo Shop")
    changed.steps = parse_steps("goto /\nexpect_text Something new")
    cases = [
        case("QA-1", "goto /\nexpect_text Demo Shop"),
        changed,
        case("QA-3", "goto /\nexpect_text Demo Shop", approve=False),
        case("QA-4", "goto /\nexpect_text Demo Shop"),
    ]
    run = run_cases(cases, demo, settings(demo, QA_MAX_CASES="1"), RunStore(tmp_path), authorized=True)
    assert [(r.status, r.reason) for r in run.results] == [
        (RunStatus.PASSED, ""),
        (RunStatus.NOT_RUN, "changed_after_approval"),
        (RunStatus.NOT_RUN, "not_approved"),
        (RunStatus.NOT_RUN, "run_limit"),
    ]


def test_retest_runs_failed_cases_again_and_links_the_runs(demo, tmp_path):
    from spec_to_test.qa_agent.service import retest_cases

    store = RunStore(tmp_path)
    first = run_cases(demo_cases()[:4], demo, settings(demo), store, authorized=True)
    again = retest_cases(first, demo_cases())
    assert [c.id for c in again] == ["QA-004"]
    second = run_cases(again, demo, settings(demo), store, authorized=True, parent_run_id=first.id)
    assert second.parent_run_id == first.id
    assert [(r.case_id, r.status) for r in second.results] == [("QA-004", RunStatus.FAILED)]  # the bug is still there
    assert {r.id for r in store.runs()} == {first.id, second.id}


def test_cli_runs_the_demo(demo, tmp_path, monkeypatch, capsys):
    from spec_to_test.qa_agent.__main__ import main

    port = demo.rsplit(":", 1)[1].strip("/")
    monkeypatch.setenv("AUTOMATION_ALLOWED_HOSTS", f"127.0.0.1:{port}")
    monkeypatch.setenv("AUTOMATION_ALLOW_PRIVATE_NETWORK", "true")
    monkeypatch.setenv("AUTOMATION_SECRET_DEMO_PASSWORD", PASSWORD)
    assert main(["--plan", str(DEMO / "plan.json"), "--url", demo, "--authorized", "--approve", "QA-001,QA-004",
                 "--requirements", str(DEMO / "requirements.md"), "--out", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "QA-001 PASSED" in out and "QA-004 FAILED (assertion)" in out and "QA-002 NOT_RUN (not_approved)" in out
    reports = list(tmp_path.glob("runs/*/report.md"))
    assert len(reports) == 1 and "BUG-" in reports[0].read_text(encoding="utf-8")
    assert main(["--plan", str(DEMO / "plan.json"), "--approve-all", "--out", str(tmp_path)]) == 2  # no --authorized
