"""Autonomous QA without a browser: discovery records, requirement drafting, test
generation, approval gates, workspace sync, triage, safety, persistence, AI checks
and the final report. Page snapshots stand in for what EXTRACT_JS returns."""

import json
import zipfile
from io import BytesIO
from types import SimpleNamespace

import pytest
from spec_to_test.qa_agent.report import reason_text

from spec_to_test.llm.config import load_config
from spec_to_test.models import ClarificationStatus, ReviewStatus, Severity
from spec_to_test.qa_agent import auto_ai, autonomous, autoplan, planner
from spec_to_test.qa_agent.auto_models import (
    AutoSession,
    Basis,
    Decision,
    DiscoveryState,
    EvidenceKind,
    FormKind,
    QueueItem,
)
from spec_to_test.qa_agent.auto_report import final_bundle, final_report
from spec_to_test.qa_agent.discovery import Recorder, normalize, role_locator
from spec_to_test.qa_agent.inference import draft_requirements
from spec_to_test.qa_agent.models import (
    RISK_SUBMITS_FORM,
    BugReport,
    CaseOrigin,
    CaseResult,
    PlanCase,
    PlanStep,
    QARun,
    RunState,
    RunStatus,
    StepAction,
)
from spec_to_test.qa_agent.safety import load_limits, load_qa_settings, preflight
from spec_to_test.qa_agent.service import QAError, check_target
from spec_to_test.qa_agent.steps import validate_step
from spec_to_test.qa_agent.store import RunStore
from spec_to_test.qa_agent.triage import Outcome, classify, refine_bugs

BASE = "http://shop.test/"
SECRET = "s3cr3t-Value-42"


def resolver(host, port, *args, **kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", port))]


def settings(**extra: str):
    return load_qa_settings({"AUTOMATION_ALLOWED_HOSTS": "shop.test", "AUTOMATION_SECRET_DEMO": SECRET, **extra})


def policy():
    from spec_to_test.automation.security import build_egress_policy

    return build_egress_policy(BASE, settings().automation, resolver)


def field(label: str, type_: str = "text", name: str = "", required: bool = False, maxlength=None, tag="input",
          id_: str = "") -> dict:
    return {"tag": tag, "type": type_, "name": name or label.lower(), "id": id_ or label.lower(), "label": label,
            "placeholder": "", "required": required, "maxlength": maxlength, "minlength": None, "options": []}


HOME = {
    "title": "Demo Shop",
    "headings": [{"level": 1, "text": "Demo Shop"}],
    "links": [
        {"text": "Home", "href": BASE, "nav": True},
        {"text": "Sign in", "href": BASE + "login", "nav": True},
        {"text": "Contact", "href": BASE + "contact#top", "nav": True},
        {"text": "Delete account", "href": BASE + "account/delete", "nav": False},
        {"text": "Log out", "href": BASE + "logout", "nav": False},
        {"text": "Partner", "href": "https://elsewhere.test/", "nav": False},
        {"text": "Mail us", "href": "mailto:a@b.test", "nav": False},
        {"text": "Broken", "href": BASE + "broken", "nav": False},
    ],
    "forms": [],
    "buttons": ["Remove all items"],
}
LOGIN = {
    "title": "Sign in · Demo Shop",
    "headings": [{"level": 1, "text": "Sign in"}],
    "links": [{"text": "Home", "href": BASE, "nav": True}],
    "forms": [{"name": "", "action": BASE + "login", "method": "post", "search": False,
               "fields": [field("Email", "email"), field("Password", "password")], "submits": ["Sign in"]}],
    "buttons": [],
}
CONTACT = {
    "title": "Contact · Demo Shop",
    "headings": [{"level": 1, "text": "Contact us"}],
    "links": [],
    "forms": [{"name": "", "action": BASE + "contact", "method": "post", "search": False,
               "fields": [field("Name", maxlength=40), field("Email"), field("Message", tag="textarea", type_="textarea"),
                          field("Phone", "tel", required=True)],
               "submits": ["Send"]}],
    "buttons": [],
}
ACCOUNT = {
    "title": "Account",
    "headings": [{"level": 1, "text": "Account"}],
    "links": [],
    "forms": [{"name": "", "action": BASE + "account/delete", "method": "post", "search": False,
               "fields": [field("Confirm", "checkbox", required=True)], "submits": ["Delete account"]}],
    "buttons": [],
}


def recorder(session: AutoSession, max_pages: int = 15, max_depth: int = 2) -> Recorder:
    redact = settings().redactor()
    return Recorder(session, policy(), redact, max_pages, max_depth)


def demo_session(lang: str = "en") -> AutoSession:
    """A session as discovery would leave it for a small shop."""
    session = AutoSession(id="0123456789abcdef", target_url=BASE, authorized=True)
    rec = recorder(session)
    rec.enqueue(BASE, 0)
    pages = {BASE: (200, BASE, HOME, ""), BASE + "login": (200, BASE + "login", LOGIN, ""),
             BASE + "contact": (200, BASE + "contact", CONTACT, ""),
             BASE + "broken": (500, BASE + "broken", {"title": "Error", "headings": [], "links": []}, "")}
    while session.queue:
        item = session.queue.pop(0)
        status, final, snapshot, redirected = pages[item.url]
        rec.ingest(item, status, final, snapshot, redirected)
    # A protected page that redirected to the sign-in page.
    rec.ingest(QueueItem(url=BASE + "dashboard", depth=1), 200, BASE + "login", LOGIN, "/dashboard")
    rec.ingest(QueueItem(url=BASE + "account", depth=1), 200, BASE + "account", ACCOUNT)
    draft_requirements(session, lang)
    autoplan.generate_cases(session, lang)
    return session


def req_by_template(session: AutoSession, template: str):
    return next(r for r in session.requirements if r.template == template)


# ---------------------------------------------------------------------------
# Discovery records
# ---------------------------------------------------------------------------

def test_links_are_queued_only_when_safe_and_inside_the_allowed_hosts():
    session = AutoSession(id="0123456789abcdef", target_url=BASE)
    rec = recorder(session)
    page = rec.ingest(QueueItem(url=BASE), 200, BASE, HOME)
    skipped = {link.text: link.skipped for link in page.links}
    assert skipped["Sign in"] == "" and skipped["Contact"] == ""
    assert skipped["Delete account"] == "destructive"
    assert skipped["Log out"] == "destructive"  # sign-out links end the session: never opened
    assert skipped["Partner"] == "external"
    assert "Mail us" not in skipped  # not an http(s) link: dropped
    assert [q.url for q in session.queue] == [BASE + "login", BASE + "contact", BASE + "broken"]  # fragment removed
    assert all(item.depth == 1 for item in session.queue)
    kinds = [e.kind for e in session.evidence]
    assert EvidenceKind.NAVIGATION in kinds and EvidenceKind.LINK in kinds and EvidenceKind.BUTTON in kinds


def test_depth_and_page_limits_stop_queueing():
    session = AutoSession(id="0123456789abcdef", target_url=BASE)
    rec = recorder(session, max_pages=2, max_depth=0)
    page = rec.ingest(QueueItem(url=BASE), 200, BASE, HOME)
    assert {link.skipped for link in page.links if link.text in ("Sign in", "Contact")} == {"depth"}
    session2 = AutoSession(id="0123456789abcdef", target_url=BASE)
    rec2 = recorder(session2, max_pages=2, max_depth=3)
    page2 = rec2.ingest(QueueItem(url=BASE), 200, BASE, HOME)
    assert len(session2.queue) == 1
    assert [link.skipped for link in page2.links if link.text == "Contact"] == ["limit"]


def test_forms_get_kinds_unique_locators_and_are_not_duplicated():
    session = demo_session()
    login, contact, account = session.forms
    assert login.kind == FormKind.LOGIN and login.name == "Sign in"  # named after the page heading
    assert contact.kind == FormKind.GENERIC and contact.name == "Contact us"
    assert [f.locator for f in contact.fields] == ["label=Name", "label=Email", "label=Message", "label=Phone"]
    assert contact.submit_locator == "role=button[name=Send]"
    assert account.destructive_term.startswith("delet")
    # The sign-in form reached again through /dashboard is the same form, not a new one.
    assert len(session.forms) == 3
    dashboard = session.page(BASE + "dashboard")
    assert dashboard.form_ids == [login.id] and dashboard.has_password and dashboard.redirected_from == "/dashboard"


def test_ambiguous_labels_fall_back_or_get_no_locator():
    session = AutoSession(id="0123456789abcdef", target_url=BASE)
    twice = {"title": "T", "headings": [], "links": [], "buttons": [], "forms": [
        {"name": "A", "action": BASE, "method": "post", "fields": [field("Email", id_="")], "submits": ["Go"]},
        {"name": "B", "action": BASE + "b", "method": "post", "fields": [field("Email", id_="")], "submits": ["Go"]},
    ]}
    for f in twice["forms"]:
        f["fields"][0]["id"] = ""
    recorder(session).ingest(QueueItem(url=BASE), 200, BASE, twice)
    assert [f.fields[0].locator for f in session.forms] == ["", ""]  # same label and name twice: not unique
    assert [f.submit_locator for f in session.forms] == ["", ""]  # two "Go" buttons


def test_page_text_is_redacted_and_clipped():
    session = AutoSession(id="0123456789abcdef", target_url=BASE)
    leaky = {"title": f"Token {SECRET}", "headings": [{"level": 1, "text": "x" * 500}], "links": [], "forms": []}
    page = recorder(session).ingest(QueueItem(url=BASE), 200, BASE, leaky)
    dumped = session.model_dump_json()
    assert SECRET not in dumped
    assert len(page.h1) <= 200


def test_role_locator_refuses_unsafe_names():
    assert role_locator("button", "Send") == "role=button[name=Send]"
    assert role_locator("button", "a]b") == "" and role_locator("link", 'say "hi"') == "" and role_locator("link", "") == ""
    assert normalize("javascript:alert(1)") == "" and normalize("HTTP://Shop.Test/a#b") == "http://shop.test/a"


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

def test_requirements_are_evidence_based_and_labelled():
    session = demo_session()
    by_template = {r.template: r for r in session.requirements if r.template}
    assert by_template["page"].basis == Basis.OBSERVED
    assert by_template["nav"].basis == Basis.OBSERVED and "\"Sign in\"" in by_template["nav"].description
    assert by_template["auth_redirect"].basis == Basis.OBSERVED and by_template["auth_redirect"].params["path"] == "/dashboard"
    assert by_template["maxlength"].params["max"] == "40"
    assert by_template["required"].params["field"] == "\"Phone\""  # `required` attribute: observed
    assert by_template["required_inferred"].basis == Basis.INFERRED  # an email field without `required`
    assert by_template["login_rejects"].basis == Basis.INFERRED
    assert by_template["server_error"].basis == Basis.INFERRED
    unknown = [r for r in session.requirements if r.basis == Basis.UNKNOWN]
    assert {r.key.split(":")[0] for r in unknown} >= {"signin", "submit", "destructive", "destructive_form"}
    for req in session.requirements:
        assert req.evidence_ids, req.id
        assert all(session.evidence_item(e) is not None for e in req.evidence_ids), req.id
        assert req.url
        if req.basis != Basis.OBSERVED:
            assert req.questions, req.id  # every non-observed requirement asks something
        limit = {Basis.OBSERVED: (80, 100), Basis.INFERRED: (30, 60), Basis.UNKNOWN: (0, 20)}[req.basis]
        assert limit[0] <= req.confidence <= limit[1], req.id
    assert [r.id for r in session.requirements] == [f"WEB-{i:03d}" for i in range(1, len(session.requirements) + 1)]


def test_drafting_again_keeps_ids_decisions_and_edits():
    session = demo_session()
    first = session.requirements[0]
    autoplan.decide(session, first.id, Decision.APPROVED, "en")
    autoplan.edit_requirement(session, first.id, "Edited by a person.", "", "en")
    before = [(r.id, r.key) for r in session.requirements]
    assert draft_requirements(session, "en") == 0
    assert [(r.id, r.key) for r in session.requirements] == before
    assert session.requirements[0].decision == Decision.APPROVED
    assert session.requirements[0].description == "Edited by a person." and session.requirements[0].edited


@pytest.mark.parametrize("lang", ["uk", "ru"])
def test_requirements_follow_the_language(lang):
    session = demo_session(lang)
    page = req_by_template(session, "page")
    assert "{" not in page.description and "Demo Shop" in page.description
    assert page.description != demo_session("en").requirements[0].description


# ---------------------------------------------------------------------------
# Test cases and approval gates
# ---------------------------------------------------------------------------

def test_generated_cases_are_valid_and_flag_form_submissions():
    session = demo_session()
    assert session.cases
    for case in session.cases:
        for step in case.steps:
            validate_step(step)
        assert any(step.is_assertion for step in case.steps)
        submits = any(s.action == StepAction.CLICK and s.target.startswith("role=button") for s in case.steps)
        assert (case.risk == RISK_SUBMITS_FORM) == submits, case.title
    # Destructive forms never get cases; unknown requirements without an answer neither.
    templates = {session.requirement(c.requirement_id).template for c in session.cases}
    assert "submit_outcome" not in templates
    assert not any(s.action == StepAction.CLICK and "Delete" in s.target for c in session.cases for s in c.steps)
    boundary = next(c for c in session.cases if c.requirement_id == req_by_template(session, "maxlength").id)
    assert boundary.steps[-1] == PlanStep(action=StepAction.EXPECT_VALUE, target="label=Name", value="b" * 40)


def test_answer_makes_unknown_testable_and_adds_the_expected_text():
    session = demo_session()
    submit = next(r for r in session.requirements if r.template == "submit_outcome")
    autoplan.edit_requirement(session, submit.id, submit.description, "Thanks! We will reply soon.", "en")
    case = next(c for c in session.cases if c.requirement_id == submit.id)
    assert case.steps[-1] == PlanStep(action=StepAction.EXPECT_TEXT, value="Thanks! We will reply soon.")
    assert case.risk == RISK_SUBMITS_FORM and session.requirement(submit.id).confirmed
    inferred = req_by_template(session, "required_inferred")
    assert not inferred.confirmed
    autoplan.edit_requirement(session, inferred.id, inferred.description, "Email is required", "en")
    case = next(c for c in session.cases if c.requirement_id == inferred.id)
    assert case.steps[-1].value == "Email is required" and session.requirement(inferred.id).confirmed


def test_cases_need_an_approved_requirement_and_changes_revoke_approval():
    session = demo_session()
    case = session.cases[0]
    assert not autoplan.approvable(session, case)
    assert autoplan.approve_cases(session, [case.id]) == 0
    autoplan.decide(session, case.requirement_id, Decision.APPROVED, "en")
    assert autoplan.approve_cases(session, [case.id]) == 1 and session.case(case.id).approved
    autoplan.decide(session, case.requirement_id, Decision.DEFERRED, "en")
    assert not session.case(case.id).approved  # un-approving the requirement revokes its cases
    autoplan.decide(session, case.requirement_id, Decision.REJECTED, "en")
    assert session.case(case.id) is None  # rejected requirements have no cases


def test_editing_an_answer_revokes_an_approved_case():
    session = demo_session()
    req = req_by_template(session, "login_rejects")
    autoplan.decide(session, req.id, Decision.APPROVED, "en")
    case = next(c for c in session.cases if c.requirement_id == req.id)
    autoplan.approve_cases(session, [case.id])
    autoplan.edit_requirement(session, req.id, req.description, "Invalid email or password", "en")
    assert not session.case(case.id).approved


# ---------------------------------------------------------------------------
# Workspace and QA plan
# ---------------------------------------------------------------------------

def approve_all_observed(session: AutoSession) -> None:
    for req in session.requirements:
        if req.basis == Basis.OBSERVED or req.template == "required_inferred":
            autoplan.decide(session, req.id, Decision.APPROVED, "en")
    autoplan.approve_cases(session, [c.id for c in session.cases])


def test_sync_creates_linked_records_once():
    session = demo_session()
    approve_all_observed(session)
    workspace, plan = autoplan.sync_workspace(session, None, None, "en", "Website: shop.test")
    approved = [r for r in session.requirements if r.decision == Decision.APPROVED]
    assert [r.id for r in workspace.requirements] == [r.id for r in approved]
    assert all(r.has_explicit_id for r in workspace.requirements)
    assert len(workspace.test_cases) == len(plan.cases) == sum(c.approved for c in session.cases)
    for case in (c for c in session.cases if c.approved):
        tc = next(x for x in workspace.test_cases if x.id == case.test_case_id)
        pc = plan.case(case.plan_case_id)
        assert tc.requirement_id == pc.requirement_id == case.requirement_id
        assert pc.test_case_id == tc.id and pc.origin == CaseOrigin.DISCOVERY and pc.is_approved
        assert tc.review_status == ReviewStatus.APPROVED and pc.risk == case.risk
        assert any("Website evidence" in a for a in tc.assumptions)
    inferred_tc = next(x for x in workspace.test_cases
                       if x.requirement_id == req_by_template(session, "required_inferred").id)
    assert inferred_tc.clarification_questions  # not confirmed: the question travels with the test case
    # Syncing again (with a resolved finding) adds no copies and keeps the finding's status.
    if workspace.findings:
        workspace.findings[0].status = ClarificationStatus.RESOLVED
    again_ws, again_plan = autoplan.sync_workspace(session, workspace, plan, "en", "ignored")
    assert len(again_ws.requirements) == len(workspace.requirements)
    assert len(again_ws.test_cases) == len(workspace.test_cases) and len(again_plan.cases) == len(plan.cases)
    if again_ws.findings:
        assert again_ws.findings[0].status == ClarificationStatus.RESOLVED
    assert again_ws.document_hash == session.document_hash == autoplan.session_document_hash(session)


def test_revoking_in_the_session_revokes_the_plan_case():
    session = demo_session()
    approve_all_observed(session)
    workspace, plan = autoplan.sync_workspace(session, None, None, "en", "W")
    case = session.cases[0]
    case.approved = False
    workspace, plan = autoplan.sync_workspace(session, workspace, plan, "en", "W")
    assert not plan.case(case.plan_case_id).is_approved
    assert next(x for x in workspace.test_cases if x.id == case.test_case_id).review_status == ReviewStatus.DRAFT


def test_rejecting_after_sending_revokes_and_reapproving_adds_no_copy():
    session = demo_session()
    approve_all_observed(session)
    workspace, plan = autoplan.sync_workspace(session, None, None, "en", "W")
    case = next(c for c in session.cases if c.approved)
    autoplan.decide(session, case.requirement_id, Decision.REJECTED, "en")
    kept = session.case(case.id)
    assert kept is not None and kept.retired and not kept.approved  # sent before: kept for its links
    assert not autoplan.approvable(session, kept)
    workspace, plan = autoplan.sync_workspace(session, workspace, plan, "en", "W")
    assert not plan.case(case.plan_case_id).is_approved  # cannot run from the manual mode either
    assert case.plan_case_id not in {c.id for c in autoplan.plan_cases(session, plan)}
    cases_before, tcs_before = len(plan.cases), len(workspace.test_cases)
    autoplan.decide(session, case.requirement_id, Decision.APPROVED, "en")
    autoplan.approve_cases(session, [case.id])
    workspace, plan = autoplan.sync_workspace(session, workspace, plan, "en", "W")
    assert (len(plan.cases), len(workspace.test_cases)) == (cases_before, tcs_before)
    assert plan.case(case.plan_case_id).is_approved


def test_navigation_link_texts_with_separators_stay_intact():
    session = AutoSession(id="0123456789abcdef", target_url=BASE)
    rec = recorder(session)
    home = dict(HOME, links=[{"text": "A; B=C", "href": BASE + "a", "nav": True},
                             {"text": "Home", "href": BASE, "nav": True}])
    rec.ingest(QueueItem(url=BASE), 200, BASE, home)
    rec.ingest(session.queue.pop(0), 200, BASE + "a", {"title": "A", "headings": [], "links": [], "forms": []})
    draft_requirements(session, "en")
    autoplan.generate_cases(session, "en")
    nav = next(r for r in session.requirements if r.template == "nav")
    case = next(c for c in session.cases if c.requirement_id == nav.id)
    assert PlanStep(action=StepAction.CLICK, target="role=link[name=A; B=C]") in case.steps
    assert PlanStep(action=StepAction.EXPECT_URL, value="/a") in case.steps


def test_hostile_snapshot_sizes_are_capped():
    from spec_to_test.qa_agent import discovery

    session = AutoSession(id="0123456789abcdef", target_url=BASE)
    flood = {"title": "x" * 10_000_000, "headings": "not a list",
             "links": [{"text": f"Delete {i}", "href": f"{BASE}d{i}"} for i in range(5000)],
             "forms": [{"fields": [field(f"F{i}") for i in range(500)], "submits": ["Go"] * 500}] * 50,
             "buttons": [f"Remove {i}" for i in range(5000)]}
    page = recorder(session).ingest(QueueItem(url=BASE), 200, BASE, flood)
    assert len(page.title) <= 200 and len(page.links) <= discovery.MAX_LINKS_KEPT
    assert len(session.forms) == 1 and len(session.forms[0].fields) <= discovery.MAX_FIELDS_PER_FORM
    assert len(page.buttons) <= discovery.MAX_BUTTONS_READ
    assert len(session.evidence) <= discovery.MAX_EVIDENCE


def test_page_limit_marks_the_links_left_in_the_queue():
    from spec_to_test.qa_agent.discovery import Discoverer

    session = AutoSession(id="0123456789abcdef", target_url=BASE)
    recorder(session).ingest(QueueItem(url=BASE), 200, BASE, HOME)
    assert session.queue
    Discoverer._left_over(session)
    assert not session.queue
    assert {link.text: link.skipped for link in session.pages[0].links}["Sign in"] == "limit"


def test_risk_does_not_change_existing_fingerprints():
    case = PlanCase(id="QA-001", requirement_id="REQ-1", title="t",
                    steps=[PlanStep(action=StepAction.GOTO, value="/"), PlanStep(action=StepAction.EXPECT_TITLE, value="x")])
    before = case.fingerprint()
    planner.approve(case)
    loaded = PlanCase.model_validate(json.loads(case.model_dump_json(exclude={"risk"})))
    assert loaded.is_approved and loaded.fingerprint() == before
    case.risk = RISK_SUBMITS_FORM
    assert not case.is_approved  # adding a risk to an approved case revokes it


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_form_submitting_cases_are_blocked_unless_allowed():
    case = PlanCase(id="QA-001", requirement_id="WEB-1", title="t", risk=RISK_SUBMITS_FORM, steps=[
        PlanStep(action=StepAction.GOTO, value="/contact"), PlanStep(action=StepAction.CLICK, target="role=button[name=Send]"),
        PlanStep(action=StepAction.EXPECT_URL, value="/contact")])
    planner.approve(case)
    limits = load_limits({})
    verdict = preflight(case, policy(), {}, limits, allow_destructive=False)
    assert verdict.status == RunStatus.BLOCKED and verdict.reason == "risk"
    assert preflight(case, policy(), {}, limits, allow_destructive=False, allow_forms=True) is None


@pytest.mark.parametrize("url, entry", [
    ("http://other.test/", "other.test"),
    ("https://other.test/x", "other.test"),
    ("http://other.test:3000/", "other.test:3000"),
])
def test_rejected_host_names_the_exact_allowlist_entry_and_changes_nothing(url, entry):
    cfg = settings()
    before = list(cfg.automation.allowed_hosts)
    with pytest.raises(QAError) as error:
        autonomous.new_session(url, cfg, "en", authorized=True, resolver=resolver)
    params = error.value.params
    assert error.value.code == "url" and params["code"] == "not_allowed"
    if entry:
        assert params["entry"] == entry
        text = reason_text("url", params, "en")
        assert f"`{entry}`" in text and "never added automatically" in text
    assert cfg.automation.allowed_hosts == before  # the allowlist is only ever reported, never widened
    with pytest.raises(QAError):  # still rejected on a second try
        autonomous.new_session(url, cfg, "en", authorized=True, resolver=resolver)


def test_ssrf_rejections_carry_no_allowlist_suggestion():
    meta = lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 80))]  # noqa: E731
    with pytest.raises(QAError) as error:
        autonomous.new_session(BASE, settings(), "en", authorized=True, resolver=meta)
    assert error.value.params["code"] == "metadata" and "entry" not in error.value.params


def test_sessions_need_authorization_and_an_allowed_host():
    with pytest.raises(QAError) as error:
        autonomous.new_session(BASE, settings(), "en", authorized=False, resolver=resolver)
    assert error.value.code == "not_authorized"
    with pytest.raises(QAError) as error:
        autonomous.new_session("http://other.test/", settings(), "en", authorized=True, resolver=resolver)
    assert error.value.code == "url"
    with pytest.raises(QAError) as error:
        autonomous.new_session(BASE, load_qa_settings({}), "en", authorized=True, resolver=resolver)
    assert error.value.code == "disabled"
    metadata = lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 80))]  # noqa: E731
    with pytest.raises(QAError):
        check_target(BASE, settings(AUTOMATION_ALLOW_PRIVATE_NETWORK="true"), metadata)
    session = autonomous.new_session(BASE, settings(), "en", authorized=True, resolver=resolver)
    assert session.authorized and session.target_url == BASE and session.limits["discovery_max_pages"] == 15


def test_discovery_needs_authorization_every_time(tmp_path):
    session = autonomous.new_session(BASE, settings(), "en", authorized=True, resolver=resolver)
    with pytest.raises(QAError) as error:
        autonomous.discover(session, settings(), RunStore(tmp_path), "en", authorized=False, resolver=resolver)
    assert error.value.code == "not_authorized"


def test_discovery_limits_are_clamped():
    limits = load_limits({"QA_DISCOVERY_MAX_PAGES": "100000", "QA_DISCOVERY_MAX_DEPTH": "-3",
                          "QA_DISCOVERY_TIMEOUT": "nope", "QA_DISCOVERY_MAX_ELEMENTS": "1"})
    assert (limits.discovery_max_pages, limits.discovery_max_depth, limits.discovery_timeout_s,
            limits.discovery_max_elements) == (100, 0, 180, 10)


# ---------------------------------------------------------------------------
# Triage and bug reports
# ---------------------------------------------------------------------------

def result(status: RunStatus, reason: str = "", error: str = "", requirement_id: str = "WEB-001") -> CaseResult:
    return CaseResult(case_id="QA-001", requirement_id=requirement_id, title="t", status=status, reason=reason,
                      error=error)


def test_classification_separates_defects_from_other_failures():
    session = demo_session()
    observed = session.requirements[0]
    inferred = req_by_template(session, "required_inferred")
    assert classify(result(RunStatus.PASSED), observed) == Outcome.PASSED
    assert classify(result(RunStatus.FAILED, "assertion"), observed) == Outcome.DEFECT
    assert classify(result(RunStatus.FAILED, "assertion"), inferred) == Outcome.UNCERTAIN
    assert classify(result(RunStatus.FAILED, "http_status"), inferred) == Outcome.DEFECT
    assert classify(result(RunStatus.FAILED, "action_error", "Timeout 3000ms exceeded"), observed) == Outcome.TIMEOUT
    assert classify(result(RunStatus.FAILED, "action_error", "net::ERR_CONNECTION_REFUSED"), observed) == Outcome.ENVIRONMENT
    for reason in ("url", "redirect", "destructive", "risk", "secret_missing"):
        assert classify(result(RunStatus.BLOCKED, reason), observed) == Outcome.SECURITY_BLOCK
    assert classify(result(RunStatus.BLOCKED, "browser"), observed) == Outcome.ENVIRONMENT
    assert classify(result(RunStatus.BLOCKED, "run_timeout"), observed) == Outcome.TIMEOUT
    assert classify(result(RunStatus.NOT_RUN, "not_approved"), observed) == Outcome.NOT_RUN
    autoplan.edit_requirement(session, inferred.id, inferred.description, "Email is required", "en")
    assert classify(result(RunStatus.FAILED, "assertion"), session.requirement(inferred.id)) == Outcome.DEFECT


def bug(case_id: str, requirement_id: str) -> BugReport:
    return BugReport(id=f"BUG-{case_id}", run_id="0" * 16, case_id=case_id, requirement_id=requirement_id, title="t")


def test_refined_bugs_keep_supported_failures_only():
    session = demo_session()
    observed = session.requirements[0]
    inferred = req_by_template(session, "required_inferred")
    run = QARun(id="0" * 16, target_url=BASE, results=[
        CaseResult(case_id="QA-1", requirement_id=observed.id, title="a", status=RunStatus.FAILED, reason="assertion"),
        CaseResult(case_id="QA-2", requirement_id=inferred.id, title="b", status=RunStatus.FAILED, reason="assertion"),
        CaseResult(case_id="QA-3", requirement_id=observed.id, title="c", status=RunStatus.FAILED,
                   reason="action_error", error="Timeout 3000ms exceeded"),
    ], bugs=[bug("QA-1", observed.id), bug("QA-2", inferred.id), bug("QA-3", observed.id)])
    refine_bugs(run, session)
    assert [(b.case_id, b.classification) for b in run.bugs] == [("QA-1", "defect"), ("QA-2", "uncertain_expectation")]
    uncertain = run.bugs[1]
    assert uncertain.severity == Severity.LOW and uncertain.title.startswith("[Needs confirmation]")
    assert any(line.startswith("website EV-") for line in run.bugs[0].evidence)
    assert run.bugs[0].environment["requirement_basis"] == "observed"


# ---------------------------------------------------------------------------
# Persistence and resuming
# ---------------------------------------------------------------------------

def test_sessions_are_saved_listed_and_deleted(tmp_path):
    store = RunStore(tmp_path)
    session = demo_session()
    store.save_session(session)
    assert store.load_session(session.id) == session
    assert [s.id for s in store.sessions()] == [session.id]
    assert store.load_session("../../etc/passwd") is None  # only hex session ids become file names
    (tmp_path / "autonomous" / "not-a-session.json").write_text("{}")
    assert [s.id for s in store.sessions()] == [session.id]
    store.delete_session(session.id)
    assert store.sessions() == []


def test_interrupted_discovery_and_runs_are_detected():
    session = demo_session()
    session.state = DiscoveryState.RUNNING
    assert autonomous.effective_state(session) == DiscoveryState.INTERRUPTED  # no worker in this process
    autonomous.ACTIVE_DISCOVERIES.add(session.id)
    try:
        assert autonomous.effective_state(session) == DiscoveryState.RUNNING
    finally:
        autonomous.ACTIVE_DISCOVERIES.discard(session.id)
    cases = [PlanCase(id=f"QA-00{i}", requirement_id="WEB-001", title="t") for i in (1, 2, 3)]
    run = QARun(id="1" * 16, target_url=BASE, state=RunState.RUNNING, cases=cases,
                results=[result(RunStatus.PASSED).model_copy(update={"case_id": "QA-001"})])
    assert autonomous.interrupted(run)
    assert [c.id for c in autonomous.unfinished_cases(run, cases)] == ["QA-002", "QA-003"]


def test_mark_interrupted_closes_stale_runs(tmp_path):
    store = RunStore(tmp_path)
    run = QARun(id="2" * 16, target_url=BASE, state=RunState.RUNNING)
    store.save(run)
    autonomous.mark_interrupted(run, store)
    assert store.load(run.id).state == RunState.ABORTED


# ---------------------------------------------------------------------------
# Optional AI
# ---------------------------------------------------------------------------

class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=self.response)


def ai_config():
    return load_config({"AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-ant-test-0000"}, env_file=None)


def test_ai_candidates_are_checked_against_evidence_and_never_observed():
    session = demo_session()
    known = session.evidence[0].id
    response = auto_ai.Interpretation.model_validate({
        "requirements": [
            {"description": "The shop lists products on the home page.", "evidence_ids": [known], "confidence": 95,
             "questions": ["Which products?"]},
            {"description": "Invented without evidence.", "evidence_ids": ["EV-999"], "confidence": 50},
            {"description": session.requirements[0].description, "evidence_ids": [known]},  # duplicate
        ],
        "questions": [{"requirement_id": session.requirements[0].id, "question": "Is the title final?"},
                      {"requirement_id": "WEB-999", "question": "ignored"}],
    })
    messages = FakeMessages(response)
    before = len(session.requirements)
    added, questions = auto_ai.interpret(ai_config(), session, "en",
                                         client_factory=lambda cfg: SimpleNamespace(messages=messages))
    assert (added, questions) == (1, 1)
    new = session.requirements[before]
    assert new.basis == Basis.INFERRED and new.confidence == 60 and new.origin.value == "ai" and not new.template
    assert new.evidence_ids == [known]
    prompt = messages.calls[0]["system"] + messages.calls[0]["messages"][0]["content"]
    assert "UNTRUSTED" in prompt and "<website-evidence>" in prompt
    assert SECRET not in prompt


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

def test_final_report_traces_evidence_to_bugs(tmp_path):
    session = demo_session()
    approve_all_observed(session)
    workspace, plan = autoplan.sync_workspace(session, None, None, "en", "W")
    case = session.cases[0]
    run = QARun(id="3" * 16, target_url=BASE, state=RunState.COMPLETED, results=[
        CaseResult(case_id=case.plan_case_id, requirement_id=case.requirement_id, title=case.title,
                   status=RunStatus.FAILED, reason="assertion")],
        bugs=[bug(case.plan_case_id, case.requirement_id)])
    refine_bugs(run, session)
    report = final_report(session, run, "en")
    req = session.requirement(case.requirement_id)
    row = next(line for line in report.splitlines() if line.startswith(f"| {', '.join(req.evidence_ids)} | {req.id}"))
    assert case.test_case_id in row and case.plan_case_id in row and "Defect" in row and run.bugs[0].id in row
    assert "## Limitations" in report and SECRET not in report
    archive = zipfile.ZipFile(BytesIO(final_bundle(session, run, tmp_path, workspace.requirements, "en")))
    assert set(archive.namelist()) == {"autonomous-report.md", "session.json", f"run-{run.id}.zip"}
    for lang in ("uk", "ru"):
        assert "qaauto." not in final_report(session, run, lang)
