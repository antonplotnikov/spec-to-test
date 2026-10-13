"""Automation tab in the Streamlit app (AppTest; model, browser and runner are fakes)."""

import pytest
from streamlit.testing.v1 import AppTest

import automation_ui
from automation_fakes import (
    SECRET_VALUE,
    FakeAgent,
    FakeRunner,
    browser_factory,
    failed_run,
    good_script,
    passed_run,
    resolver,
    tool_use,
)
from conftest import PROJECT_ROOT, goto, home
from spec_to_test.ai_analysis import AIError
from spec_to_test.automation import service as service_module
from spec_to_test.automation.config import load_automation_config
from spec_to_test.automation.models import JobStatus
from spec_to_test.automation.service import AutomationService
from spec_to_test.i18n import LANGUAGES, t
from spec_to_test.models import ReviewStatus
from test_localization import raw_keys, visible_text

APP_PATH = str(PROJECT_ROOT / "app.py")
REQUIREMENTS = (
    "REQ-001: A reset link expires after 15 minutes; an expired link shows \"Link expired\".\n"
    "REQ-002: The password must be at least 8 characters."
)


def analyzed_app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    home(at).text_area(key="requirements_text").input(REQUIREMENTS).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    return goto(at, "tests")  # Automation is a tab of the Test Cases page


def approve_first_test_case(at: AppTest) -> str:
    workspace = at.session_state["workspace"]
    tc = workspace.test_cases[0]
    tc.review_status = ReviewStatus.APPROVED
    tc.expected_result = 'The error "Link expired" is shown and the password is not changed.'
    tc.steps = ["Open the expired reset link", "Submit a new password"]
    at.session_state["workspace"] = workspace
    at.run()
    return tc.id


def by_key(elements, key):
    return next(e for e in elements if e.key == key)


@pytest.fixture
def automation_on(monkeypatch, tmp_path):
    """AI and an allowlist configured; the process-wide service uses fakes."""
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    monkeypatch.setenv("AUTOMATION_ALLOWED_HOSTS", "staging.example.com")
    monkeypatch.setenv("AUTOMATION_DATA_DIR", str(tmp_path / "automation"))
    monkeypatch.setenv("AUTOMATION_SECRET_STAGING_PASSWORD", SECRET_VALUE)
    monkeypatch.setattr(automation_ui, "missing_prerequisites", lambda config: [])
    agents: list[FakeAgent] = []
    runners: list[FakeRunner] = []
    svc = AutomationService(
        load_automation_config(),
        agent_factory=lambda ai: agents.pop(0),
        browser_factory=browser_factory(),
        runner_factory=lambda cfg: runners.pop(0),
        resolver=resolver(),
        check_prerequisites=False,
    )
    service_module.set_service(svc)
    yield svc, agents, runners
    service_module.set_service(None)


def run_job(at: AppTest, svc: AutomationService) -> str:
    by_key(at.checkbox, "automation_consent_0").check().run()
    run_button = by_key(at.button, "automation_run")
    assert not run_button.disabled
    run_button.click().run()
    assert not at.exception
    job_id = at.session_state["automation_job"]
    svc.wait(job_id, timeout=10)
    at.run()
    return job_id


def test_without_configuration_the_tab_explains_what_is_missing():
    at = analyzed_app()
    assert "Automation" in [tab.label for tab in at.tabs]
    info = "\n".join(i.value for i in at.info)
    assert t("automation.not_ready") in info and t("automation.missing.ai") in info
    assert t("automation.missing.allowlist") in info
    assert not [b for b in at.button if b.key == "automation_run"]


def test_only_approved_test_cases_are_offered(automation_on):
    at = analyzed_app()
    assert t("automation.no_approved") in [i.value for i in at.info]
    tc_id = approve_first_test_case(at)
    assert by_key(at.selectbox, "automation_tc").options == [f"{tc_id} — {at.session_state['workspace'].test_cases[0].title}"]
    assert by_key(at.text_input, "automation_url").value == "https://staging.example.com/"


def test_run_needs_fresh_consent_every_time(automation_on):
    svc, agents, runners = automation_on
    at = analyzed_app()
    approve_first_test_case(at)
    assert by_key(at.button, "automation_run").disabled
    agents.append(FakeAgent([tool_use("a", "submit_test_script", **good_script())]))
    runners.append(FakeRunner(passed_run()))
    run_job(at, svc)
    assert not [c for c in at.checkbox if c.key == "automation_consent_0"]
    assert not by_key(at.checkbox, "automation_consent_1").value


def test_full_flow_shows_results_and_approves_into_the_workspace(automation_on):
    svc, agents, runners = automation_on
    at = analyzed_app()
    tc_id = approve_first_test_case(at)
    agents.append(FakeAgent([tool_use("a", "submit_test_script", **good_script())]))
    runners.append(FakeRunner(passed_run()))
    job_id = run_job(at, svc)
    assert svc.job(at.session_state["automation_owner"], job_id).status == JobStatus.PASSED
    assert any(t("automation.reason.passed") in s.value for s in at.success)
    assert any("getByRole" in c.value for c in at.code)
    assert any(t("automation.check.verified") in str(v) for table in at.table for v in table.value.to_numpy().ravel())

    by_key(at.button, f"automation_approve_{job_id}").click().run()
    assert not at.exception
    tests = at.session_state["workspace"].automated_tests
    assert [(a.id, a.test_case_id) for a in tests] == [("AT-001", tc_id)]
    assert any(t("automation.already_approved") in s.value for s in at.success)
    assert SECRET_VALUE not in "\n".join(visible_text(at) + [c.value for c in at.code])
    labels = [b.label for b in at.get("download_button")]
    assert t("automation.download.approved") in labels and t("automation.download.spec") in labels


def test_failed_job_shows_the_error_and_cannot_be_approved(automation_on):
    svc, agents, runners = automation_on
    at = analyzed_app()
    approve_first_test_case(at)
    agents.append(FakeAgent([tool_use("a", "submit_test_script", **good_script())],
                            [tool_use("b", "submit_test_script", **good_script())]))
    runners.append(FakeRunner(failed_run("expected Link expired"), failed_run("expected Link expired")))
    job_id = run_job(at, svc)
    assert any(t("automation.reason.test_failed") in e.value for e in at.error)
    assert any("expected Link expired" in c.value for c in at.code)
    assert not [b for b in at.button if b.key == f"automation_approve_{job_id}"]


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_automation_tab_is_translated(automation_on, lang):
    svc, agents, runners = automation_on
    at = analyzed_app()
    approve_first_test_case(at)
    agents.append(FakeAgent([tool_use("a", "submit_test_script", **good_script())]))
    runners.append(FakeRunner(passed_run()))
    run_job(at, svc)
    at.selectbox(key="language").select(lang).run()
    assert not at.exception
    texts = visible_text(at)
    assert not raw_keys(texts), raw_keys(texts)
    joined = "\n".join(texts)
    for key in ("tab.automation", "automation.approve", "automation.code_heading", "automation.status.passed"):
        assert t(key, lang) in joined, key


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_ai_error_is_translated_in_the_status_and_activity_log(automation_on, lang):
    svc, agents, runners = automation_on
    at = analyzed_app()
    approve_first_test_case(at)
    agents.append(FakeAgent(error=AIError("auth")))
    runners.append(FakeRunner())
    run_job(at, svc)
    at.selectbox(key="language").select(lang).run()
    activity = [str(el.value) for el in at.get("text")]
    assert sum(t("ai.error.auth", lang) in line for line in activity) == 1  # the final event of the log
    texts = visible_text(at) + activity
    assert not raw_keys(texts), raw_keys(texts)
