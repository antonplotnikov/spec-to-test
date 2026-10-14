"""QA Agent plans (generation, editing, approval, import) and the checks before a run."""

import json
import socket

import pytest

from spec_to_test.automation.config import load_automation_config
from spec_to_test.automation.security import build_egress_policy
from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestType, Workspace
from spec_to_test.qa_agent import planner
from spec_to_test.qa_agent.models import CaseOrigin, PlanCase, PlanStep, RunStatus, StepAction, TestPlan
from spec_to_test.qa_agent.safety import RUN_SLOT, QASettings, load_limits, load_qa_settings, preflight
from spec_to_test.qa_agent.service import QAError, check_target, retest_cases, run_cases
from spec_to_test.qa_agent.steps import StepError
from spec_to_test.qa_agent.store import RunStore

ENV = {"AUTOMATION_ALLOWED_HOSTS": "staging.example.com", "AUTOMATION_SECRET_DEMO_PASSWORD": "s3cret-value"}


def public_resolver(host, port, *args):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def settings(env: dict[str, str] | None = None) -> QASettings:
    return load_qa_settings(ENV if env is None else env)


def policy():
    return build_egress_policy("https://staging.example.com/", settings().automation, public_resolver)


def workspace() -> Workspace:
    concrete = TestCase(
        id="TC-001", requirement_id="REQ-1", title="Sign in", test_type=TestType.POSITIVE,
        steps=["Open /login", 'Enter "demo@example.com" in the "Email" field', 'Click the "Sign in" button'],
        expected_result='The page shows "Welcome".', review_status=ReviewStatus.APPROVED,
    )
    vague = TestCase(
        id="TC-002", requirement_id="REQ-2", title="Vague", test_type=TestType.NEGATIVE,
        steps=["Perform the action described in the requirement."], expected_result="It works.",
    )
    return Workspace(
        document_hash="abc123",
        requirements=[Requirement(id="REQ-1", text="Sign in."), Requirement(id="REQ-2", text="Other.")],
        test_cases=[concrete, vague],
    )


def approved_case(*steps: PlanStep, case_id: str = "QA-001") -> PlanCase:
    case = PlanCase(id=case_id, requirement_id="REQ-1", title="Case",
                    steps=list(steps) or [PlanStep(action=StepAction.EXPECT_TEXT, value="Hi")])
    planner.approve(case)
    return case


# --- Plans -----------------------------------------------------------------------

def test_plan_from_test_cases_links_ids_and_never_guesses():
    ws = workspace()
    plan = planner.new_plan(ws)
    assert planner.add_test_cases(plan, ws, only_approved=True) == 1
    case = plan.cases[0]
    assert (case.id, case.requirement_id, case.test_case_id, case.origin) == ("QA-001", "REQ-1", "TC-001", CaseOrigin.TEST_CASE)
    assert case.steps and case.has_assertion and not case.approved
    assert planner.add_test_cases(plan, ws, only_approved=False) == 1  # TC-001 is not added twice
    vague = plan.cases[1]
    assert vague.steps == [] and vague.unparsed == ["Perform the action described in the requirement."]
    assert planner.approval_problem(vague) == "no_steps"


def test_editing_an_approved_case_revokes_its_approval():
    case = approved_case()
    assert case.is_approved
    planner.edit_case(case, title="Case", requirement_id="REQ-1", steps_text="expect_text Bye", expected_result="")
    assert case.approved and not case.is_approved  # fingerprint no longer matches


def test_invalid_edit_changes_nothing():
    case = approved_case()
    with pytest.raises(StepError):
        planner.edit_case(case, title="New", requirement_id="REQ-2", steps_text="explode now", expected_result="")
    assert case.title == "Case" and case.is_approved


def test_a_case_without_a_check_cannot_be_approved():
    case = PlanCase(id="QA-001", requirement_id="REQ-1", title="x", steps=[PlanStep(action=StepAction.GOTO, value="/")])
    with pytest.raises(planner.PlanError) as error:
        planner.approve(case)
    assert error.value.code == "no_assertion"


def test_import_drops_approvals_and_validates(tmp_path):
    plan = TestPlan(cases=[approved_case()])
    imported = planner.import_plan(plan.model_dump_json().encode(), "doc1")
    assert imported.document_hash == "doc1"
    assert not imported.cases[0].approved and imported.cases[0].origin == CaseOrigin.IMPORTED
    bad = json.loads(plan.model_dump_json())
    bad["cases"][0]["steps"] = [{"action": "click", "target": "", "value": ""}]
    with pytest.raises(planner.PlanError) as error:
        planner.import_plan(json.dumps(bad).encode(), "doc1")
    assert error.value.code == "invalid_step"
    for raw, code in ((b"not json", "invalid_file"), (b"x" * (planner.MAX_PLAN_BYTES + 1), "too_large")):
        with pytest.raises(planner.PlanError) as error:
            planner.import_plan(raw, "doc1")
        assert error.value.code == code
    dup = json.loads(plan.model_dump_json())
    dup["cases"] = dup["cases"] * 2
    with pytest.raises(planner.PlanError):
        planner.import_plan(json.dumps(dup).encode(), "doc1")


def test_the_demo_plan_imports_and_approves():
    from conftest import PROJECT_ROOT

    plan = planner.import_plan((PROJECT_ROOT / "examples" / "qa_demo" / "plan.json").read_bytes(), "")
    for case in plan.cases:
        planner.approve(case)
    assert len(plan.cases) == 6 and all(c.is_approved for c in plan.cases)


# --- Preflight ---------------------------------------------------------------------

def verdict(case: PlanCase, allow_destructive: bool = False, secrets: dict[str, str] | None = None):
    found = preflight(case, policy(), secrets if secrets is not None else {"DEMO_PASSWORD": "x"}, load_limits({}),
                      allow_destructive)
    return (found.status, found.reason, found.params) if found else None


def test_preflight_allows_an_approved_safe_case():
    assert verdict(approved_case(PlanStep(action=StepAction.GOTO, value="/login"),
                                 PlanStep(action=StepAction.EXPECT_TEXT, value="Hi"))) is None


def test_preflight_not_run_reasons():
    draft = PlanCase(id="QA-1", requirement_id="R", title="t", steps=[PlanStep(action=StepAction.EXPECT_TEXT, value="x")])
    assert verdict(draft)[:2] == (RunStatus.NOT_RUN, "not_approved")
    empty = PlanCase(id="QA-2", requirement_id="R", title="t")
    assert verdict(empty)[:2] == (RunStatus.NOT_RUN, "no_steps")
    changed = approved_case()
    changed.steps.append(PlanStep(action=StepAction.EXPECT_TEXT, value="more"))
    assert verdict(changed)[:2] == (RunStatus.NOT_RUN, "changed_after_approval")
    long_case = approved_case(*[PlanStep(action=StepAction.EXPECT_TEXT, value="x")] * 41)
    assert verdict(long_case)[:2] == (RunStatus.NOT_RUN, "too_many_steps")


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://169.254.169.254/latest/meta-data/", "not_allowed"),
        ("https://evil.example.org/", "not_allowed"),
        ("file:///etc/passwd", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("https://user:pw@staging.example.com/", "credentials"),
        ("//evil.example.org/x", "scheme"),
    ],
)
def test_preflight_blocks_navigation_off_the_allowlist(url, code):
    case = approved_case(PlanStep(action=StepAction.GOTO, value=url), PlanStep(action=StepAction.EXPECT_TEXT, value="x"))
    status, reason, params = verdict(case)
    assert (status, reason) == (RunStatus.BLOCKED, "url")
    assert params["code"] == code


def test_preflight_blocks_missing_secrets_and_destructive_steps():
    secret = approved_case(PlanStep(action=StepAction.FILL, target="label=Password", value="{{secret:NOPE}}"),
                           PlanStep(action=StepAction.EXPECT_TEXT, value="x"))
    assert verdict(secret)[:3] == (RunStatus.BLOCKED, "secret_missing", {"name": "NOPE"})
    delete = approved_case(PlanStep(action=StepAction.CLICK, target="role=button[name=Delete account]"),
                           PlanStep(action=StepAction.EXPECT_TEXT, value="x"))
    assert verdict(delete)[:2] == (RunStatus.BLOCKED, "destructive")
    assert verdict(delete, allow_destructive=True) is None
    pay = approved_case(PlanStep(action=StepAction.GOTO, value="/checkout/pay"), PlanStep(action=StepAction.EXPECT_TEXT, value="x"))
    assert verdict(pay)[:2] == (RunStatus.BLOCKED, "destructive")
    # Typing the word "delete" into a search box is not destructive.
    search = approved_case(PlanStep(action=StepAction.FILL, target="label=Search", value="delete"),
                           PlanStep(action=StepAction.EXPECT_TEXT, value="x"))
    assert verdict(search) is None


def test_limits_are_clamped():
    limits = load_limits({"QA_MAX_CASES": "100000", "QA_STEP_TIMEOUT_MS": "1", "QA_RUN_TIMEOUT": "abc"})
    assert (limits.max_cases, limits.step_timeout_ms, limits.run_timeout_s) == (200, 1000, 600)


# --- Service refusals (no browser needed) ----------------------------------------------

def test_check_target():
    check_target("https://staging.example.com/", settings(), public_resolver)
    with pytest.raises(QAError) as error:
        check_target("https://staging.example.com/", settings({}), public_resolver)
    assert error.value.code == "disabled"
    private = lambda *a: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]  # noqa: E731
    with pytest.raises(QAError) as error:
        check_target("https://staging.example.com/", settings(), private)
    assert (error.value.code, error.value.params["code"]) == ("url", "private")


def test_metadata_addresses_are_refused_even_when_allowlisted():
    env = {"AUTOMATION_ALLOWED_HOSTS": "169.254.169.254", "AUTOMATION_ALLOW_PRIVATE_NETWORK": "true"}
    with pytest.raises(QAError) as error:
        check_target("http://169.254.169.254/latest/meta-data/", settings(env))
    assert error.value.params["code"] == "metadata"


@pytest.mark.parametrize(
    ("kwargs", "env", "code"),
    [
        ({"authorized": False}, ENV, "not_authorized"),
        ({"authorized": True}, {}, "disabled"),
    ],
)
def test_run_is_refused_before_anything_starts(tmp_path, kwargs, env, code):
    with pytest.raises(QAError) as error:
        run_cases([approved_case()], "https://staging.example.com/", settings(env), RunStore(tmp_path),
                  resolver=public_resolver, **kwargs)
    assert error.value.code == code
    assert not (tmp_path / "runs").exists()


def test_run_needs_an_approved_case_and_a_free_slot(tmp_path):
    pytest.importorskip("playwright.sync_api")
    draft = PlanCase(id="QA-1", requirement_id="R", title="t", steps=[PlanStep(action=StepAction.EXPECT_TEXT, value="x")])
    with pytest.raises(QAError) as error:
        run_cases([draft], "https://staging.example.com/", settings(), RunStore(tmp_path), authorized=True,
                  resolver=public_resolver)
    assert error.value.code == "nothing_approved"
    assert RUN_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(QAError) as error:
            run_cases([approved_case()], "https://staging.example.com/", settings(), RunStore(tmp_path),
                      authorized=True, resolver=public_resolver)
        assert error.value.code == "busy"
    finally:
        RUN_SLOT.release()


def test_retest_uses_the_current_version_of_failed_cases():
    from spec_to_test.qa_agent.models import CaseResult, QARun

    old = approved_case(case_id="QA-001")
    passed = approved_case(case_id="QA-002")
    run = QARun(id="0" * 16, target_url="https://staging.example.com/", cases=[old, passed], results=[
        CaseResult(case_id="QA-001", requirement_id="REQ-1", title="Case", status=RunStatus.FAILED),
        CaseResult(case_id="QA-002", requirement_id="REQ-1", title="Case", status=RunStatus.PASSED),
    ])
    fixed = approved_case(PlanStep(action=StepAction.EXPECT_TEXT, value="fixed"), case_id="QA-001")
    assert retest_cases(run, [fixed, passed]) == [fixed]
    assert retest_cases(run, []) == [old]  # removed from the plan: retested as it was


def test_automation_secret_values_come_only_from_the_environment():
    config = load_automation_config(ENV)
    assert config.secret_values() == {"DEMO_PASSWORD": "s3cret-value"}
    assert "s3cret-value" not in repr(config)
