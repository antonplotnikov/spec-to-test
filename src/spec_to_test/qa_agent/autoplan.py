"""Test cases for drafted requirements, and handing approved work to the rest of the app.

`generate_cases` builds executable steps (the QA Agent step language) from a
requirement's template and the evidence discovery recorded: the locators it
found, the texts the page showed, the attributes fields carry. Expected texts
come only from the page or from the reviewer's answer, never from guessing.
Cases that submit a form carry RISK_SUBMITS_FORM and run only when the person
allows form submissions for that run; destructive forms get no cases at all.

`sync_workspace` hands the approved requirements and cases to the rest of the
app, creating or updating one workspace document per session:
- requirements keep their WEB-… IDs (explicit IDs, so analysis, Grill Mode and
  the RTM see the same IDs as the session);
- rule-based analysis runs on them; findings already in the document keep
  their status (matched by finding key);
- each approved case becomes one workspace test case (approved review status)
  and one QA plan case linked to it, so runs, history, retests and the RTM use
  the existing machinery. Running sync again updates the same records instead
  of adding copies; the session keeps the links (test_case_id, plan_case_id).
"""

import json

from spec_to_test.i18n import t
from spec_to_test.input_parser import detect_language
from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestType, Workspace
from spec_to_test.projects import now as project_now
from spec_to_test.qa_agent import planner
from spec_to_test.qa_agent.auto_models import (
    AutoCase,
    AutoSession,
    Basis,
    Decision,
    DraftRequirement,
    FieldInfo,
    FormInfo,
)
from spec_to_test.qa_agent.discovery import path_of, role_locator
from spec_to_test.qa_agent.executor import now, step_label
from spec_to_test.qa_agent.models import RISK_SUBMITS_FORM, CaseOrigin, PlanCase, PlanStep, StepAction, TestPlan
from spec_to_test.qa_agent.steps import StepError, validate_step
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.storage import document_hash
from spec_to_test.test_generator import next_test_case_id

INVALID_EMAIL = "not-an-email"
WRONG_USER = "qa-agent@example.invalid"
WRONG_PASSWORD = "Wrong-Password-123"  # a literal, deliberately wrong value: not a secret


def _step(action: StepAction, target: str = "", value: str = "") -> PlanStep:
    return PlanStep(action=action, target=target, value=value)


def sample_value(field: FieldInfo) -> str | None:
    """A plausible valid value for a field, within its length limits; None when it cannot be filled."""
    if field.type in ("password", "checkbox", "radio", "file", "hidden"):
        return None
    if field.tag == "select":
        return next((o for o in field.options if o.strip()), None)
    text = f"{field.name} {field.label} {field.placeholder}".casefold()
    if field.type == "email" or "email" in text or "e-mail" in text:
        value = "qa.agent@example.com"
    elif field.type in ("number", "range"):
        value = "1"
    elif field.type == "tel":
        value = "+15550100"
    elif field.type == "url":
        value = "https://example.com"
    elif field.type == "date":
        value = "2030-01-15"
    elif field.tag == "textarea":
        value = "Test message from the Spec-to-Test QA Agent."
    else:
        value = "QA Agent"
    if field.minlength and len(value) < field.minlength:
        value = value + "x" * (field.minlength - len(value))
    if field.maxlength:
        value = value[: field.maxlength]
    return value or None


def fill_valid(form: FormInfo, skip: FieldInfo | None = None) -> list[PlanStep]:
    """Fill every findable field except `skip` with a valid sample value."""
    steps = []
    for field in form.fields:
        if field is skip or not field.locator:
            continue
        if field.type == "checkbox" and field.required:
            steps.append(_step(StepAction.CHECK, field.locator))
            continue
        value = sample_value(field)
        if value is None:
            continue
        action = StepAction.SELECT if field.tag == "select" else StepAction.FILL
        steps.append(_step(action, field.locator, value))
    return steps


def _field(form: FormInfo, locator: str) -> FieldInfo | None:
    return next((f for f in form.fields if f.locator == locator), None)


class _Spec:
    def __init__(self, key: str, title: str, test_type: TestType, steps: list[PlanStep], expected: str,
                 risk: str = "") -> None:
        self.key, self.title, self.test_type, self.steps, self.expected, self.risk = (
            key, title, test_type, steps, expected, risk)


def _specs(session: AutoSession, req: DraftRequirement, lang: str) -> list[_Spec]:  # noqa: C901 - one branch per template
    p = req.params
    answer = req.answer.strip()
    form = session.form(p.get("form_id", ""))

    def tr(key: str, **params: str) -> str:
        return t(f"qaauto.case.{key}", lang, **params)

    if req.template == "page":
        steps = [_step(StepAction.GOTO, value=p["path"])]
        if p.get("title"):
            steps.append(_step(StepAction.EXPECT_TITLE, value=p["title"]))
        if p.get("heading"):
            steps.append(_step(StepAction.EXPECT_VISIBLE, role_locator("heading", p["heading"])))
        if len(steps) == 1:
            steps.append(_step(StepAction.EXPECT_URL, value=p["path"].split("?")[0]))
        return [_Spec("page", tr("page", path=p["path"]), TestType.POSITIVE, steps, req.description)]
    if req.template == "nav":
        steps = []
        try:
            targets = json.loads(p.get("targets") or "[]")
        except ValueError:
            targets = []
        for text, path in (t_ for t_ in targets if isinstance(t_, list) and len(t_) == 2):
            if text and path:
                steps += [_step(StepAction.GOTO, value=p["path"]), _step(StepAction.CLICK, role_locator("link", text)),
                          _step(StepAction.EXPECT_URL, value=path.split("?")[0])]
        return [_Spec("nav", tr("nav", path=p["path"]), TestType.POSITIVE, steps, req.description)] if steps else []
    if req.template == "auth_redirect":
        steps = [_step(StepAction.GOTO, value=p["path"]), _step(StepAction.EXPECT_URL, value=p["target"].split("?")[0])]
        return [_Spec("auth", tr("auth_redirect", path=p["path"]), TestType.NEGATIVE, steps, req.description)]
    if req.template == "server_error":
        steps = [_step(StepAction.GOTO, value=p["path"]), _step(StepAction.EXPECT_URL, value=p["path"].split("?")[0])]
        return [_Spec("server_error", tr("server_error", path=p["path"]), TestType.ERROR_HANDLING, steps,
                      req.description)]
    if form is None:
        return []
    page = path_of(form.page_url)
    field = _field(form, p.get("field_locator", ""))
    if req.template == "form_fields":
        steps = [_step(StepAction.GOTO, value=page)]
        steps += [_step(StepAction.EXPECT_VISIBLE, f.locator) for f in form.fields if f.locator][:15]
        steps.append(_step(StepAction.EXPECT_VISIBLE, form.submit_locator))
        return [_Spec("form", tr("form_fields", form=p["form"]), TestType.POSITIVE, steps, req.description)]
    if req.template == "maxlength" and field is not None and field.maxlength:
        limit = field.maxlength
        steps = [
            _step(StepAction.GOTO, value=page),
            _step(StepAction.FILL, field.locator, "a" * limit),
            _step(StepAction.EXPECT_VALUE, field.locator, "a" * limit),
            _step(StepAction.FILL, field.locator, "b" * (limit + 1)),
            _step(StepAction.EXPECT_VALUE, field.locator, "b" * limit),
        ]
        return [_Spec("maxlength", tr("maxlength", field=p["field"], max=str(limit)), TestType.BOUNDARY, steps,
                      req.description)]
    rejected = [_step(StepAction.CLICK, form.submit_locator), _step(StepAction.EXPECT_URL, value=page.split("?")[0])]
    if req.template in ("required", "required_inferred") and field is not None:
        steps = [_step(StepAction.GOTO, value=page), *fill_valid(form, skip=field), *rejected,
                 _step(StepAction.EXPECT_VISIBLE, field.locator)]
        if answer:
            steps.append(_step(StepAction.EXPECT_TEXT, value=answer))
        return [_Spec("required", tr("required", field=p["field"]), TestType.NEGATIVE, steps, req.description,
                      RISK_SUBMITS_FORM)]
    if req.template == "email_format" and field is not None:
        steps = [_step(StepAction.GOTO, value=page), *fill_valid(form, skip=field),
                 _step(StepAction.FILL, field.locator, INVALID_EMAIL), *rejected,
                 _step(StepAction.EXPECT_VISIBLE, field.locator)]
        return [_Spec("email", tr("email_format", field=p["field"]), TestType.NEGATIVE, steps, req.description,
                      RISK_SUBMITS_FORM)]
    if req.template == "login_rejects":
        password = next((f for f in form.fields if f.type == "password" and f.locator), None)
        user = next((f for f in form.fields if f.type != "password" and f.locator), None)
        if password is None or user is None:
            return []
        user_value = WRONG_USER if user.type == "email" or "mail" in user.display.casefold() else "qa-agent-unknown"
        steps = [_step(StepAction.GOTO, value=page), _step(StepAction.FILL, user.locator, user_value),
                 _step(StepAction.FILL, password.locator, WRONG_PASSWORD), _step(StepAction.CLICK, form.submit_locator),
                 _step(StepAction.EXPECT_VISIBLE, password.locator)]
        if answer:
            steps.append(_step(StepAction.EXPECT_TEXT, value=answer))
        return [_Spec("login", tr("login_rejects"), TestType.NEGATIVE, steps, req.description, RISK_SUBMITS_FORM)]
    if req.template == "submit_outcome" and answer:
        steps = [_step(StepAction.GOTO, value=page), *fill_valid(form), _step(StepAction.CLICK, form.submit_locator),
                 _step(StepAction.EXPECT_TEXT, value=answer)]
        return [_Spec("submit", tr("submit_outcome", form=p["form"]), TestType.POSITIVE, steps, req.description,
                      RISK_SUBMITS_FORM)]
    return []


def _valid(steps: list[PlanStep]) -> bool:
    try:
        for step in steps:
            validate_step(step)
    except StepError:
        return False
    return any(step.is_assertion for step in steps)


def generate_cases(session: AutoSession, lang: str) -> None:
    """(Re)build the cases of every requirement that is not rejected; IDs and approvals are kept
    while a case's content stays the same."""
    existing = {c.key: c for c in session.cases}
    numbers = [int(c.id.split("-")[1]) for c in session.cases]
    cases: list[AutoCase] = []
    regenerated: set[str] = set()
    for req in session.requirements:
        if req.decision == Decision.REJECTED or not req.template:
            continue
        for spec in _specs(session, req, lang):
            if not _valid(spec.steps):
                continue
            key = f"{req.id}:{spec.key}"
            case = existing.get(key)
            if case is None:
                numbers.append(max(numbers, default=0) + 1)
                case = AutoCase(id=f"AC-{numbers[-1]:03d}", key=key, requirement_id=req.id, title=spec.title)
            changed = (case.steps != spec.steps or case.expected_result != spec.expected or case.risk != spec.risk)
            case.title, case.test_type, case.steps = spec.title[:300], spec.test_type, spec.steps
            case.expected_result, case.risk = spec.expected[:2000], spec.risk
            if changed or case.retired:
                case.approved = False
            case.retired = False
            regenerated.add(key)
            cases.append(case)
    # A case that no longer applies (its requirement was rejected, an answer removed) but was
    # already sent keeps its links, retired: the next sync revokes it instead of losing track.
    for case in session.cases:
        if case.key not in regenerated and (case.test_case_id or case.plan_case_id):
            case.approved, case.retired = False, True
            cases.append(case)
    session.cases = cases


# --- Decisions -----------------------------------------------------------------------

def decide(session: AutoSession, requirement_id: str, decision: Decision, lang: str) -> None:
    req = session.requirement(requirement_id)
    if req is None:
        return
    req.decision = decision
    req.decided_at = now()
    if decision != Decision.APPROVED:
        for case in session.cases:
            if case.requirement_id == requirement_id:
                case.approved = False
    generate_cases(session, lang)


def edit_requirement(session: AutoSession, requirement_id: str, description: str, answer: str, lang: str) -> None:
    """Apply a reviewer's edit. The basis stays as discovered; `confirmed` reflects the edit."""
    req = session.requirement(requirement_id)
    if req is None:
        return
    description = " ".join(description.split())[:1000]
    if description:
        req.description = description
    req.answer = answer.strip()[:500]
    generate_cases(session, lang)


def approvable(session: AutoSession, case: AutoCase) -> bool:
    req = session.requirement(case.requirement_id)
    return not case.retired and req is not None and req.decision == Decision.APPROVED and _valid(case.steps)


def approve_cases(session: AutoSession, case_ids: list[str]) -> int:
    count = 0
    for case_id in case_ids:
        case = session.case(case_id)
        if case is not None and approvable(session, case):
            case.approved = True
            count += 1
    return count


# --- Workspace and plan ----------------------------------------------------------------

def session_document_hash(session: AutoSession) -> str:
    """Stable per session, so syncing again updates the same document."""
    return document_hash(f"autonomous-qa:{session.id}")


def _requirement(req: DraftRequirement) -> Requirement:
    return Requirement(id=req.id, text=req.description, language=detect_language(req.description),
                       has_explicit_id=True)


def _assumptions(session: AutoSession, req: DraftRequirement, lang: str) -> list[str]:
    evidence = [f"{e.id} ({e.kind.value}) {e.url}" + (f": {e.text}" if e.text else "")
                for e in (session.evidence_item(i) for i in req.evidence_ids) if e is not None]
    notes = [t("qaauto.tc.evidence", lang, evidence="; ".join(evidence)[:900])] if evidence else []
    if req.basis != Basis.OBSERVED and not req.confirmed:
        notes.append(t("qaauto.tc.inferred", lang, basis=t(f"qaauto.basis.{req.basis.value}", lang)))
    return notes


def sync_workspace(session: AutoSession, workspace: Workspace | None, plan: TestPlan | None, lang: str,
                   title: str) -> tuple[Workspace, TestPlan]:
    """Send approved requirements and approved cases to the session's workspace document and QA plan."""
    doc_hash = session.document_hash or session_document_hash(session)
    if workspace is None or workspace.document_hash != doc_hash:
        workspace = Workspace(document_hash=doc_hash, title=title[:200], created_at=project_now())
    if plan is None or plan.document_hash != doc_hash:
        plan = planner.new_plan(workspace, session.target_url)
    plan.target_url = session.target_url

    approved = [r for r in session.requirements if r.decision == Decision.APPROVED]
    by_id = {r.id: r for r in workspace.requirements}
    for req in approved:
        by_id[req.id] = _requirement(req)
    workspace.requirements = list(by_id.values())
    old_status = {f.key: f.status for f in workspace.findings}
    analysis = analyze_requirements(workspace.requirements)
    for finding in analysis.findings:
        if finding.key in old_status:
            finding.status = old_status[finding.key]
    workspace.findings = analysis.findings

    approved_ids = {r.id for r in approved}
    for case in session.cases:
        draft = session.requirement(case.requirement_id)
        active = draft is not None and draft.id in approved_ids and case.approved and not case.retired
        tc = next((x for x in workspace.test_cases if x.id == case.test_case_id), None) if case.test_case_id else None
        pc = plan.case(case.plan_case_id) if case.plan_case_id else None
        if not active:
            # Not (or no longer) approved: what was sent before stays, but cannot run.
            if tc is not None:
                tc.review_status = ReviewStatus.DRAFT
            if pc is not None:
                planner.revoke(pc)
            continue
        assert draft is not None  # for the type checker: `active` implies it
        if tc is None:
            tc = TestCase(id=next_test_case_id(workspace.test_cases), requirement_id=draft.id, title=case.title,
                          test_type=case.test_type, steps=["-"], expected_result="-")
            workspace.test_cases.append(tc)
            case.test_case_id = tc.id
        tc.requirement_id, tc.title, tc.test_type = draft.id, case.title, case.test_type
        tc.preconditions = [t("qaauto.tc.precondition", lang, url=session.target_url)]
        tc.steps = [step_label(s) for s in case.steps] or ["-"]
        tc.expected_result = case.expected_result or draft.description
        tc.assumptions = _assumptions(session, draft, lang)
        tc.clarification_questions = [] if draft.confirmed else draft.questions[:5]
        tc.review_status = ReviewStatus.APPROVED

        if pc is None:
            pc = PlanCase(id=planner.next_case_id(plan.cases), requirement_id=draft.id, title=case.title,
                          origin=CaseOrigin.DISCOVERY)
            plan.cases.append(pc)
            case.plan_case_id = pc.id
        pc.requirement_id, pc.test_case_id, pc.title = draft.id, tc.id, case.title
        pc.steps, pc.expected_result, pc.risk = list(case.steps), case.expected_result, case.risk
        pc.origin, pc.unparsed = CaseOrigin.DISCOVERY, []
        if not pc.is_approved:
            planner.approve(pc)
    plan.updated_at = now()
    session.document_hash = doc_hash
    return workspace, plan


def plan_cases(session: AutoSession, plan: TestPlan) -> list[PlanCase]:
    """The plan cases this session created and still uses, in session order."""
    ids = [c.plan_case_id for c in session.cases if c.plan_case_id and not c.retired]
    return [pc for pc in (plan.case(i) for i in ids) if pc is not None]
