"""Test plans: built from the document's test cases, edited and approved by a person.

- Each workspace test case becomes one plan case linked to its requirement and
  test case IDs. Concrete written steps are converted to executable steps
  (spec_to_test.qa_agent.steps); when any step cannot be read, the case keeps
  no steps and lists the text it could not convert. Nothing is guessed.
- Approval is per case and records a fingerprint of the content; any edit
  revokes it (see PlanCase.is_approved). A case needs at least one step and
  one check to be approved, so a PASS always means a check held.
- Imported plans never carry approvals: approving is done on this page.
"""

import json
import re

from pydantic import ValidationError

from spec_to_test.models import ReviewStatus, TestCase, Workspace
from spec_to_test.qa_agent.executor import now
from spec_to_test.qa_agent.models import CaseOrigin, PlanCase, PlanStep, TestPlan
from spec_to_test.qa_agent.steps import StepError, parse_steps, steps_from_test_case, validate_step

MAX_PLAN_BYTES = 1_000_000
MAX_CASES = 500
CASE_ID = re.compile(r"^QA-(\d+)$")


class PlanError(ValueError):
    """`code` maps to qaagent.plan_error.<code>."""

    def __init__(self, code: str, params: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.params = params or {}


def next_case_id(cases: list[PlanCase]) -> str:
    numbers = [int(m.group(1)) for c in cases if (m := CASE_ID.match(c.id))]
    return f"QA-{max(numbers, default=0) + 1:03d}"


def case_from_test_case(tc: TestCase, case_id: str) -> PlanCase:
    conversion = steps_from_test_case(tc.preconditions, tc.steps, tc.expected_result)
    return PlanCase(
        id=case_id,
        requirement_id=tc.requirement_id,
        test_case_id=tc.id,
        title=tc.title[:300],
        steps=conversion.steps,
        expected_result=tc.expected_result[:2000],
        origin=CaseOrigin.TEST_CASE,
        unparsed=conversion.unparsed[:20],
    )


def add_test_cases(plan: TestPlan, workspace: Workspace, only_approved: bool = True) -> int:
    """Add a case for every test case not yet in the plan; existing (edited) cases are kept."""
    present = {c.test_case_id for c in plan.cases if c.test_case_id}
    added = 0
    for tc in workspace.test_cases:
        if tc.id in present or (only_approved and tc.review_status != ReviewStatus.APPROVED):
            continue
        if len(plan.cases) >= MAX_CASES:
            break
        plan.cases.append(case_from_test_case(tc, next_case_id(plan.cases)))
        added += 1
    plan.updated_at = now()
    return added


def new_plan(workspace: Workspace, target_url: str = "") -> TestPlan:
    stamp = now()
    return TestPlan(document_hash=workspace.document_hash, target_url=target_url, created_at=stamp, updated_at=stamp)


def add_manual_case(plan: TestPlan, requirement_id: str, title: str) -> PlanCase:
    if len(plan.cases) >= MAX_CASES:
        raise PlanError("too_many_cases")
    case = PlanCase(id=next_case_id(plan.cases), requirement_id=requirement_id, title=title)
    plan.cases.append(case)
    plan.updated_at = now()
    return case


def edit_case(case: PlanCase, *, title: str, requirement_id: str, steps_text: str, expected_result: str) -> None:
    """Apply an edit; raises StepError (nothing changed) when a step line is invalid."""
    steps = parse_steps(steps_text)
    title = title.strip()
    if not title:
        raise PlanError("title")
    case.title = title[:300]
    case.requirement_id = requirement_id
    case.steps = steps
    case.expected_result = expected_result.strip()[:2000]
    if steps:
        case.unparsed = []


def set_steps(case: PlanCase, steps: list[PlanStep], origin: CaseOrigin) -> None:
    for step in steps:
        validate_step(step)
    case.steps = steps
    case.origin = origin
    case.unparsed = []


def approval_problem(case: PlanCase) -> str | None:
    """Why the case cannot be approved (qaagent.plan_error.<code>), or None."""
    if not case.steps:
        return "no_steps"
    if not case.has_assertion:
        return "no_assertion"
    for step in case.steps:
        try:
            validate_step(step)
        except StepError:
            return "invalid_step"
    return None


def approve(case: PlanCase) -> None:
    if problem := approval_problem(case):
        raise PlanError(problem)
    case.approved = True
    case.approved_fingerprint = case.fingerprint()
    case.approved_at = now()


def revoke(case: PlanCase) -> None:
    case.approved = False
    case.approved_fingerprint = ""
    case.approved_at = ""


def import_plan(raw: bytes, document_hash: str) -> TestPlan:
    """A plan from an exported JSON file, without approvals, bound to the open document."""
    if len(raw) > MAX_PLAN_BYTES:
        raise PlanError("too_large")
    try:
        data = json.loads(raw.decode("utf-8"))
        plan = TestPlan.model_validate(data)
    except (UnicodeDecodeError, ValueError, ValidationError):
        raise PlanError("invalid_file") from None
    if len(plan.cases) > MAX_CASES:
        raise PlanError("too_many_cases")
    if len({c.id for c in plan.cases}) != len(plan.cases):
        raise PlanError("duplicate_ids")
    for case in plan.cases:
        for step in case.steps:
            try:
                validate_step(step)
            except StepError as error:
                raise PlanError("invalid_step", {"case": case.id, "code": error.code}) from None
        revoke(case)
        if case.origin != CaseOrigin.TEST_CASE:
            case.origin = CaseOrigin.IMPORTED
    plan.document_hash = document_hash
    plan.updated_at = now()
    return plan


def unknown_requirements(plan: TestPlan, workspace: Workspace) -> list[str]:
    known = {r.id for r in workspace.requirements}
    return sorted({c.requirement_id for c in plan.cases if c.requirement_id not in known})
