"""Autonomous QA mode of the QA Agent page (Streamlit AppTest).

The last test explores the local Demo Shop through the page; it is skipped
when Playwright's Chromium is not installed.
"""

import threading

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto
from spec_to_test.qa_agent.auto_models import Decision
from spec_to_test.qa_agent.store import RunStore
from test_qa_agent_e2e import _chromium_works
from test_qa_auto_unit import demo_session

APP_PATH = str(PROJECT_ROOT / "app.py")
DEMO = PROJECT_ROOT / "examples" / "qa_demo"


def store(tmp_path) -> RunStore:
    return RunStore(tmp_path / "data" / "qa_agent" / "default")


def autonomous(at: AppTest) -> AppTest:
    at.run()
    goto(at, "qa_agent")
    at.segmented_control(key="qa_mode").set_value("auto").run()
    assert not at.exception
    return at


def button(at: AppTest, key: str):
    return next(b for b in at.button if b.key == key)


def test_manual_mode_stays_the_default_and_needs_a_document():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    goto(at, "qa_agent")
    assert at.segmented_control(key="qa_mode").value == "manual"
    assert any(b.key == "qa_agent_go_home" for b in at.button)


def test_autonomous_mode_works_without_a_document_and_needs_authorization(monkeypatch):
    monkeypatch.setenv("AUTOMATION_ALLOWED_HOSTS", "shop.test")
    at = autonomous(AppTest.from_file(APP_PATH, default_timeout=30))
    assert any("explores it read-only" in c.value for c in at.caption)
    at.text_input(key="qa_auto_url").input("http://other.test/").run()
    assert any("not on the allowlist" in w.value or "not allowed" in w.value.lower() for w in at.warning)
    assert button(at, "qa_auto_start_button").disabled


def test_review_approve_and_send_to_workspace(tmp_path):
    session = demo_session()
    store(tmp_path).save_session(session)
    at = autonomous(AppTest.from_file(APP_PATH, default_timeout=60))
    assert at.selectbox(key="qa_auto_pick").value == session.id  # the newest saved session opens
    assert [t.label for t in at.tabs][:5] == ["1 · Site map", "2 · Requirements", "3 · Test plan", "4 · Run & bugs",
                                              "5 · Final report"]

    button(at, "qa_auto_bulk_observed").click().run()
    saved = store(tmp_path).load_session(session.id)
    observed = [r for r in saved.requirements if r.basis.value == "observed"]
    assert observed and all(r.decision == Decision.APPROVED for r in observed)
    assert all(r.decision == Decision.PROPOSED for r in saved.requirements if r.basis.value != "observed")

    # Reject one requirement explicitly, then approve the read-only cases.
    rejected = observed[0].id
    button(at, f"qa_auto_rejected_{rejected}").click().run()
    button(at, "qa_auto_approve_safe").click().run()
    saved = store(tmp_path).load_session(session.id)
    assert saved.requirement(rejected).decision == Decision.REJECTED
    approved = [c for c in saved.cases if c.approved]
    assert approved and not any(c.risk for c in approved)  # form-submitting cases need their own approval

    # A case that submits a form needs the confirmation checkbox.
    req = next(r for r in saved.requirements if r.template == "required")
    assert req.decision == Decision.APPROVED  # observed: approved by the bulk action
    risky = next(c for c in store(tmp_path).load_session(session.id).cases if c.requirement_id == req.id)
    button(at, f"qa_auto_approve_{risky.id}").click().run()
    assert not store(tmp_path).load_session(session.id).case(risky.id).approved
    at.checkbox(key=f"qa_auto_risk_ok_{risky.id}").check().run()
    button(at, f"qa_auto_approve_{risky.id}").click().run()
    assert store(tmp_path).load_session(session.id).case(risky.id).approved

    button(at, "qa_auto_send").click().run()
    assert not at.exception
    saved = store(tmp_path).load_session(session.id)
    workspace = at.session_state["workspace"]
    assert workspace.document_hash == saved.document_hash
    assert rejected not in {r.id for r in workspace.requirements}
    assert len(workspace.test_cases) == sum(c.approved for c in saved.cases)
    plan = store(tmp_path).load_plan(saved.document_hash)
    assert plan is not None and all(pc.is_approved for pc in plan.cases)

    # The manual mode now shows the same plan for the session's document.
    at.segmented_control(key="qa_mode").set_value("manual").run()
    assert not at.exception
    assert next(m.value for m in at.metric if m.label == "Plan cases") == str(len(plan.cases))


@pytest.mark.skipif(not _chromium_works(), reason="Playwright Chromium is not installed")
def test_start_autonomous_qa_from_the_page(monkeypatch, tmp_path):
    import sys

    sys.path.insert(0, str(DEMO))
    from server import make_server

    server = make_server(port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    monkeypatch.setenv("AUTOMATION_ALLOWED_HOSTS", f"127.0.0.1:{server.server_address[1]}")
    monkeypatch.setenv("AUTOMATION_ALLOW_PRIVATE_NETWORK", "true")
    try:
        at = autonomous(AppTest.from_file(APP_PATH, default_timeout=120))
        at.text_input(key="qa_auto_url").input(url).run()
        assert button(at, "qa_auto_start_button").disabled  # not yet authorized
        next(c for c in at.checkbox if c.key and c.key.startswith("qa_auto_authorize_")).check().run()
        button(at, "qa_auto_start_button").click().run()
        assert not at.exception
        [session] = store(tmp_path).sessions()
        assert session.pages and session.requirements
        assert any("Discovery finished" in s.value for s in at.success)
        # The authorization is asked again for the next discovery.
        assert not any(c.value for c in at.checkbox if c.key and c.key.startswith("qa_auto_resume_authorize_"))
    finally:
        server.shutdown()
        server.server_close()
