"""Autonomous QA against a real browser and the local Demo Shop.

Skipped when Playwright's Chromium is not installed. The demo server counts the
POST requests it receives, so "discovery is read-only" is checked at the server.
"""

import sys
import threading
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT
from spec_to_test.automation.security import build_egress_policy
from spec_to_test.qa_agent import autonomous, autoplan
from spec_to_test.qa_agent.auto_models import Basis, Decision, DiscoveryState
from spec_to_test.qa_agent.discovery import Discoverer
from spec_to_test.qa_agent.models import RunStatus
from spec_to_test.qa_agent.store import RunStore
from spec_to_test.qa_agent.triage import Outcome, outcomes
from test_qa_agent_e2e import _chromium_works, internal, settings  # noqa: F401 - `internal` is a fixture

pytestmark = pytest.mark.skipif(not _chromium_works(), reason="Playwright Chromium is not installed")
DEMO = PROJECT_ROOT / "examples" / "qa_demo"
PASSWORD = "demo-pass-123"


@pytest.fixture
def shop(internal):  # noqa: F811 - the imported fixture
    sys.path.insert(0, str(DEMO))
    from server import make_server  # examples/qa_demo/server.py

    server = make_server(port=0, password=PASSWORD, other_port=internal.server_address[1])
    posts: list[str] = []
    handler = server.RequestHandlerClass
    original = handler.do_POST

    def counting(self):
        posts.append(self.path)
        original(self)

    handler.do_POST = counting
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.posts = posts
    server.url = f"http://127.0.0.1:{server.server_address[1]}/"
    yield server
    server.shutdown()
    server.server_close()


def discovered(shop, tmp_path: Path, **extra: str):
    qa = settings(shop.url, **extra)
    store = RunStore(tmp_path)
    session = autonomous.new_session(shop.url, qa, "en", authorized=True)
    progress: list[str] = []
    autonomous.discover(session, qa, store, "en", authorized=True, on_page=lambda done, total, page: progress.append(page.path))
    return session, qa, store, progress


def test_discovery_is_read_only_and_stays_on_the_allowed_host(shop, internal, tmp_path):  # noqa: F811
    session, _, store, progress = discovered(shop, tmp_path)
    assert session.state == DiscoveryState.COMPLETED
    assert shop.posts == []  # nothing was submitted
    assert internal.hits == []  # the off-site redirect never reached the other service
    paths = {page.path for page in session.pages}
    assert {"/", "/login", "/contact", "/account", "/broken", "/go-elsewhere"} <= paths
    assert progress and len(progress) == len(session.pages)
    blocked = next(p for p in session.pages if p.path == "/go-elsewhere")
    assert blocked.error == "redirect_blocked"
    templates = {r.template for r in session.requirements}
    assert {"page", "nav", "auth_redirect", "server_error", "form_fields", "maxlength", "required_inferred",
            "login_rejects", "submit_outcome"} <= templates
    assert any(r.basis == Basis.UNKNOWN and "Delete account" in r.description for r in session.requirements)
    assert PASSWORD not in session.model_dump_json()
    assert store.load_session(session.id) == session  # saved


def approve(session):
    for req in session.requirements:
        if req.basis == Basis.OBSERVED or req.template in ("server_error", "required_inferred", "login_rejects"):
            autoplan.decide(session, req.id, Decision.APPROVED, "en")
    autoplan.approve_cases(session, [c.id for c in session.cases])


def test_full_flow_finds_the_demo_bugs_and_classifies_them(shop, tmp_path):
    session, qa, store, _ = discovered(shop, tmp_path)
    approve(session)
    workspace, plan = autoplan.sync_workspace(session, None, None, "en", "Website")
    store.save_plan(plan)
    cases = autoplan.plan_cases(session, plan)

    # Without permission, cases that submit forms are blocked and nothing is posted.
    run = autonomous.execute(session, cases, qa, store, authorized=True, allow_forms=False)
    assert shop.posts == []
    found = outcomes(run, session)
    risky = {c.id for c in cases if c.risk}
    assert risky and all(found[case_id] == Outcome.SECURITY_BLOCK for case_id in risky)

    run = autonomous.execute(session, cases, qa, store, authorized=True, allow_forms=True)
    found = outcomes(run, session)
    by_template = {session.requirement(r.requirement_id).template: r for r in run.results}
    assert by_template["server_error"].status == RunStatus.FAILED and by_template["server_error"].reason == "http_status"
    assert found[by_template["server_error"].case_id] == Outcome.DEFECT
    # The deliberate demo bug: the contact form accepts an empty email. The expectation was
    # only inferred and not confirmed, so it is reported as uncertain, not as a defect.
    assert by_template["required_inferred"].status == RunStatus.FAILED
    assert found[by_template["required_inferred"].case_id] == Outcome.UNCERTAIN
    for template in ("page", "nav", "auth_redirect", "form_fields", "maxlength", "login_rejects"):
        assert by_template[template].status == RunStatus.PASSED, template
    assert sorted(b.classification for b in run.bugs) == ["defect", "uncertain_expectation"]
    assert set(shop.posts) == {"/login", "/contact"}  # only the approved form cases submitted anything
    assert "/account/delete" not in shop.posts
    assert session.run_ids[-1] == run.id and store.load(run.id).bugs == run.bugs

    # Confirming the expectation (the reviewer's answer) turns it into a defect on retest.
    req = next(r for r in session.requirements if r.template == "required_inferred")
    autoplan.edit_requirement(session, req.id, req.description, "Email is required", "en")
    autoplan.approve_cases(session, [c.id for c in session.cases if c.requirement_id == req.id])
    workspace, plan = autoplan.sync_workspace(session, workspace, plan, "en", "Website")
    retest = autonomous.execute(session, [c for c in autoplan.plan_cases(session, plan) if c.requirement_id == req.id],
                                qa, store, authorized=True, allow_forms=True, parent_run_id=run.id)
    assert [b.classification for b in retest.bugs] == ["defect"]
    assert "Email is required" in retest.bugs[0].expected


def test_interrupted_discovery_resumes_without_duplicates(shop, tmp_path):
    qa = settings(shop.url)
    store = RunStore(tmp_path)
    session = autonomous.new_session(shop.url, qa, "en", authorized=True)
    policy = build_egress_policy(session.target_url, qa.automation)
    ticks = iter([0.0, 0.0, 0.0])  # the deadline, then two pages; after that time is up
    Discoverer(qa, policy, clock=lambda: next(ticks, 10_000.0)).run(session)
    assert session.state == DiscoveryState.INTERRUPTED and len(session.pages) == 2 and session.queue
    store.save_session(session)
    autonomous.discover(session, qa, store, "en", authorized=True)
    assert session.state == DiscoveryState.COMPLETED and not session.queue
    urls = [page.url for page in session.pages]
    assert len(urls) == len(set(urls))
    assert session.requirements
