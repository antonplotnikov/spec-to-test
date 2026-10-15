"""Test Suite Planner: Smoke, Regression and Full suites from the existing test cases.

Only the test cases' own metadata is used (test type, review status, priority); nothing
is generated and no AI is involved.

- full:       every test case
- regression: every Approved test case
- smoke:      Approved happy-path (Positive) test cases with High or Medium priority;
              Low stays out. Priority is set by the reviewer (Medium by default) and
              never inferred. Requirements without such a test case are listed,
              because Smoke says nothing about them.
"""

from enum import StrEnum

from pydantic import BaseModel

from spec_to_test.models import ReviewStatus, TestPriority, TestType, Workspace


class SuiteKind(StrEnum):
    SMOKE = "smoke"
    REGRESSION = "regression"
    FULL = "full"


class SuitePlan(BaseModel):
    # Suite -> test case IDs, in workspace order.
    suites: dict[SuiteKind, list[str]]
    # Requirements without a Smoke test case: not represented in Smoke.
    smoke_missing: list[str]


def plan_suites(workspace: Workspace) -> SuitePlan:
    approved = [tc for tc in workspace.test_cases if tc.review_status == ReviewStatus.APPROVED]
    smoke = [tc for tc in approved if tc.test_type == TestType.POSITIVE and tc.priority != TestPriority.LOW]
    represented = {tc.requirement_id for tc in smoke}
    return SuitePlan(
        suites={
            SuiteKind.SMOKE: [tc.id for tc in smoke],
            SuiteKind.REGRESSION: [tc.id for tc in approved],
            SuiteKind.FULL: [tc.id for tc in workspace.test_cases],
        },
        smoke_missing=[req.id for req in workspace.requirements if req.id not in represented],
    )


def suite_workspace(workspace: Workspace, kind: SuiteKind) -> Workspace:
    """A copy of the workspace holding only the suite's test cases, for the existing exports."""
    selected = set(plan_suites(workspace).suites[kind])
    return workspace.model_copy(update={"test_cases": [tc for tc in workspace.test_cases if tc.id in selected]})
