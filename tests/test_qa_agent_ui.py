"""QA Agent page in the app (Streamlit AppTest).

The last test runs real cases through the page against the local Demo Shop;
it is skipped when Playwright's Chromium is not installed.
"""

import threading

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto, home
from spec_to_test.qa_agent.store import RunStore
from test_qa_agent_e2e import _chromium_works

APP_PATH = str(PROJECT_ROOT / "app.py")
DEMO = PROJECT_ROOT / "examples" / "qa_demo"


def analyzed_demo() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    home(at).text_area(key="requirements_text").input((DEMO / "requirements.md").read_text(encoding="utf-8")).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    return goto(at, "qa_agent")


def button(at: AppTest, key: str):
    return next(b for b in at.button if b.key == key)


def metric(at: AppTest, label: str) -> str:
    return next(m.value for m in at.metric if m.label == label)


def write_steps(at: AppTest, case_id: str, steps: str) -> AppTest:
    at.text_area(key=f"qa_steps_{case_id}").input(steps)
    next(b for b in at.button if b.label == "Save case" and b.key and case_id in b.key).click().run()
    return at


def test_page_needs_an_open_document():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    goto(at, "qa_agent")
    assert not at.exception
    assert any(b.key == "qa_agent_go_home" for b in at.button)


def test_plan_from_vague_test_cases_needs_steps_and_cannot_run(monkeypatch):
    monkeypatch.delenv("AUTOMATION_ALLOWED_HOSTS", raising=False)
    at = analyzed_demo()
    assert at.title[0].value == "QA Agent"
    assert any("operator has not allowed any host" in w.value for w in at.warning)
    at.checkbox(key="qa_only_approved").uncheck().run()
    button(at, "qa_generate").click().run()
    assert not at.exception
    cases = int(metric(at, "Plan cases"))
    assert cases > 0
    # Rule-generated test cases are generic, so no steps are invented for them.
    assert int(metric(at, "Need steps")) == cases
    assert all(b.disabled for b in at.button if b.key and b.key.startswith("qa_approve_"))
    assert button(at, "qa_run").disabled


def test_editing_and_approving_a_case(monkeypatch):
    at = analyzed_demo()
    button(at, "qa_add_case").click().run()
    write_steps(at, "QA-001", "goto /\nexpect_text Demo Shop")
    assert not at.error, [e.value for e in at.error]
    button(at, "qa_approve_QA-001").click().run()
    assert metric(at, "Approved to run") == "1"
    # Editing the approved case revokes the approval.
    write_steps(at, "QA-001", "goto /\nexpect_text Demo Shop!")
    assert metric(at, "Approved to run") == "0"
    write_steps(at, "QA-001", "explode the page")
    assert any("unknown action" in e.value for e in at.error)


def test_invalid_url_is_explained(monkeypatch):
    monkeypatch.setenv("AUTOMATION_ALLOWED_HOSTS", "staging.example.com")
    at = analyzed_demo()
    at.text_input(key="qa_url").input("http://169.254.169.254/").run()
    assert any("169.254.169.254" in w.value or "allow" in w.value.lower() for w in at.warning)


@pytest.mark.skipif(not _chromium_works(), reason="Playwright Chromium is not installed")
def test_real_run_from_the_page_records_history_bug_and_report(monkeypatch, tmp_path):
    import sys

    sys.path.insert(0, str(DEMO))
    from server import make_server

    server = make_server(port=0, password="demo-pass-123")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    monkeypatch.setenv("AUTOMATION_ALLOWED_HOSTS", f"127.0.0.1:{server.server_address[1]}")
    monkeypatch.setenv("AUTOMATION_ALLOW_PRIVATE_NETWORK", "true")
    try:
        at = analyzed_demo()
        at.text_input(key="qa_url").input(url).run()
        assert any("passes the allowlist" in c.value for c in at.caption)
        button(at, "qa_add_case").click().run()
        write_steps(at, "QA-001", "goto /\nexpect_visible role=heading[name=Demo Shop]")
        button(at, "qa_add_case").click().run()
        write_steps(at, "QA-002", "goto /contact\nfill label=Name | Alex\nclick role=button[name=Send]\n"
                                  "expect_text Email is required")
        button(at, "qa_add_case").click().run()  # QA-003 stays unapproved
        button(at, "qa_approve_QA-001").click().run()
        button(at, "qa_approve_QA-002").click().run()
        assert button(at, "qa_run").disabled  # not authorized yet
        at.checkbox(key="qa_authorize_0").check().run()
        button(at, "qa_run").click().run()
        assert not at.exception
        assert any("1 passed, 1 failed, 0 blocked, 1 not run; 1 bug report" in s.value for s in at.success)
        # History: real statuses, a screenshot per executed case and the bug report.
        labels = [e.label for e in at.expander]
        assert any("✅ QA-001" in label for label in labels) and any("❌ QA-002" in label for label in labels)
        assert any("🐞 BUG-" in label for label in labels)
        assert len(at.image) == 2
        assert any(b.key == "qa_dl_zip" for b in at.get("download_button"))
        # Retest needs a new authorization; it links the runs.
        at.checkbox(key="qa_retest_authorize_1").check().run()
        button(at, "qa_retest").click().run()
        store = RunStore(tmp_path / "data" / "qa_agent" / "default")
        runs = store.runs()
        assert len(runs) == 2 and runs[0].parent_run_id == runs[1].id
        assert [r.status.value for r in runs[0].results] == ["failed"]
        assert at.selectbox(key="qa_history_pick").value == runs[0].id  # History shows the new run
    finally:
        server.shutdown()
        server.server_close()
