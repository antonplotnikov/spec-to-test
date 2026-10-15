"""QA tasks in plain text, answered with the app's existing rule-based tools.

The agent reads the task, picks the tools that answer it and runs each one once
on the open document:

- critic:       Test Case Critic (spec_to_test.test_critic)
- coverage:     Scenario Coverage (spec_to_test.scenario_coverage)
- impact:       Change Impact (spec_to_test.change_impact)
- traceability: traceability gaps of the RTM (spec_to_test.rtm)
- suites:       Test Suite Planner (spec_to_test.suites)

The tools do the analysis; this module only routes the task to them and turns
their output into one result: conclusions, problems, unknowns and
recommendations. Tool selection is keyword-based (EN / UK / RU), no AI.

The agent never changes the workspace. A request to change test case statuses
("approve TC-003") becomes a proposed action that the page applies with
`apply_action` only after the user confirms it. Running, generating, editing or
deleting is not supported and is reported instead of attempted.
"""

import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from spec_to_test.models import ChangeImpact, Requirement, ReviewStatus, TestCase, Workspace
from spec_to_test.rtm import Coverage, build_rtm, traceability_gaps
from spec_to_test.rule_engine import _compile
from spec_to_test.scenario_coverage import scenario_coverage
from spec_to_test.suites import SuiteKind, plan_suites
from spec_to_test.test_critic import critique

Tool = Literal["critic", "coverage", "impact", "traceability", "suites"]
TOOLS: tuple[Tool, ...] = ("critic", "coverage", "impact", "traceability", "suites")

# At most this many tool calls per task.
MAX_STEPS = 5
MAX_TASK_LENGTH = 2000
# A proposed status change names at most this many test cases.
MAX_ACTION_TEST_CASES = 20

_TOOL_TERMS: dict[Tool, list[str]] = {
    "critic": [
        "critic*", "critique", "quality", "duplicat*", "vague", "review*",
        "критик*", "качеств*", "дубл*", "размыт*", "ревью", "якіст*", "розмит*", "рев'ю",
    ],
    "coverage": [
        "coverage", "cover", "covered", "covers", "uncovered", "scenario*",
        "покрыт*", "покрит*", "сценари*", "сценарі*",
    ],
    "impact": [
        "impact", "change", "changes", "changed", "diff", "version*",
        "изменени*", "изменил*", "влияни*", "верси*", "змін*", "вплив*", "версі*",
    ],
    "traceability": [
        "traceab*", "trace", "rtm", "matrix", "link*", "unlinked", "orphan*", "gap", "gaps", "untested",
        "трассир*", "трасув*", "матриц*", "связ*", "зв'яз*", "пробел*", "прогалин*", "непротестир*",
    ],
    "suites": [
        "suite*", "smoke", "regression",
        "набор*", "набір*", "смоук", "регресс*", "регрес*",
    ],
}
_PATTERNS = {tool: _compile(terms) for tool, terms in _TOOL_TERMS.items()}
_EVERYTHING = _compile([
    "full", "everything", "overall", "audit", "readiness", "release", "all checks",
    "полн*", "всё", "все проверки", "аудит*", "готовност*", "релиз*",
    "повн*", "усі перевірки", "всі перевірки", "готовн*", "реліз*",
])
_APPROVE = _compile([
    "approve", "set approved", "mark approved", "mark as approved",
    "утверди", "утвердить", "одобри", "одобрить", "затверди", "затвердити", "схвали", "схвалити",
])
_TO_DRAFT = _compile([
    "back to draft", "to draft", "as draft",
    "в черновик", "в черновики", "до чернетки", "в чернетку", "у чернетку",
])
# What the agent does not do: it only analyzes and proposes status changes.
_UNSUPPORTED = _compile([
    "run", "execute", "generate", "create", "write", "delete", "remove", "automate", "fix", "edit", "rewrite",
    "запусти*", "выполни", "сгенерир*", "создай", "напиши", "удали*", "автоматиз*", "исправ*", "перепиши",
    "виконай", "згенеруй", "створи", "видали*", "виправ*",
])
# Requirement and test case IDs (REQ-1, TC-003, FR-AUTH-01, REQ-1.2).
_ID = re.compile(r"(?<![\w-])[^\W\d_]+(?:[-_.][^\W\d_]+)*[-_.]?\d+(?:[-.]\d+)*(?![\w-])")


class Item(BaseModel):
    """One translatable line: `key` with `params`; `terms` are translation keys joined into {names}."""

    key: str
    params: dict[str, str] = Field(default_factory=dict)
    terms: list[str] = Field(default_factory=list)
    ref: str = ""  # the requirement or test case it is about
    topic: str = ""  # translation key of a short label shown before the line


class StepResult(BaseModel):
    tool: Tool
    status: Literal["ok", "error"] = "ok"
    summary: Item | None = None
    problems: list[Item] = Field(default_factory=list)
    unknowns: list[Item] = Field(default_factory=list)
    recommendations: list[Item] = Field(default_factory=list)
    error: str = ""  # exception type only; details stay in the logs


class ProposedAction(BaseModel):
    """A test case status change the user has to confirm before it is applied."""

    kind: Literal["set_review_status"] = "set_review_status"
    test_case_ids: list[str]
    status: ReviewStatus


class AgentPlan(BaseModel):
    tools: list[Tool]
    test_case_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    # Things in the task that look like IDs but are not in the document.
    unknown_ids: list[str] = Field(default_factory=list)
    # Words of the task the agent does not act on ("run", "delete", ...).
    unsupported_terms: list[str] = Field(default_factory=list)
    action: ProposedAction | None = None
    # The status change asked for without naming test cases.
    action_needs_ids: bool = False
    action_too_large: bool = False
    # Tools left out because of MAX_STEPS.
    skipped_tools: list[Tool] = Field(default_factory=list)


class AgentResult(BaseModel):
    task: str
    document_hash: str = ""
    # done: every tool ran; partial: some failed; unsupported: nothing to do; error: nothing ran.
    status: Literal["done", "partial", "unsupported", "error"]
    error: str = ""  # translation key for status "error" before any tool ran
    plan: AgentPlan | None = None
    steps: list[StepResult] = Field(default_factory=list)
    action: ProposedAction | None = None

    @property
    def problems(self) -> list[Item]:
        return [i for s in self.steps for i in s.problems]

    @property
    def unknowns(self) -> list[Item]:
        return [i for s in self.steps for i in s.unknowns]

    @property
    def recommendations(self) -> list[Item]:
        return [i for s in self.steps for i in s.recommendations]


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _ids_in(task: str, workspace: Workspace) -> tuple[list[str], list[str], list[str]]:
    """(test case IDs, requirement IDs, unknown IDs) named in the task, in task order."""
    test_cases = {tc.id.lower(): tc.id for tc in workspace.test_cases}
    requirements = {r.id.lower(): r.id for r in workspace.requirements}
    tc_ids: list[str] = []
    req_ids: list[str] = []
    unknown: list[str] = []
    for token in dict.fromkeys(_ID.findall(task)):
        if (tc_id := test_cases.get(token.lower())) is not None:
            tc_ids.append(tc_id)
        elif (req_id := requirements.get(token.lower())) is not None:
            req_ids.append(req_id)
        elif token.split("-")[0].isupper():  # "TC-999", "REQ-7"; not "v2" or "mp3"
            unknown.append(token)
    return tc_ids, req_ids, unknown


def plan_task(task: str, workspace: Workspace, max_steps: int = MAX_STEPS) -> AgentPlan:
    """Which tools answer the task, on which IDs, and which status change it asks for."""
    tc_ids, req_ids, unknown_ids = _ids_in(task, workspace)
    unsupported = list(dict.fromkeys(m.group(0).lower() for m in _UNSUPPORTED.finditer(task)))
    tools = [tool for tool in TOOLS if _PATTERNS[tool].search(task)]
    # "Full check" means every tool, but "delete everything" asks for something the agent does not do.
    if not unsupported and _EVERYTHING.search(task):
        tools = list(TOOLS)

    target = ReviewStatus.APPROVED if _APPROVE.search(task) else ReviewStatus.DRAFT if _TO_DRAFT.search(task) else None
    action = None
    needs_ids = too_large = False
    if target is not None:
        if not tc_ids:
            needs_ids = True
        elif len(tc_ids) > MAX_ACTION_TEST_CASES:
            too_large = True
        else:
            action = ProposedAction(test_case_ids=tc_ids, status=target)
            if "critic" not in tools:
                tools.insert(0, "critic")  # check the test cases before the change is confirmed
    # IDs alone: test cases are judged by the critic, requirements by their scenario coverage.
    if not tools and not unsupported and tc_ids:
        tools.append("critic")
    if not tools and not unsupported and req_ids:
        tools.append("coverage")
    return AgentPlan(
        tools=tools[:max_steps], test_case_ids=tc_ids, requirement_ids=req_ids, unknown_ids=unknown_ids,
        unsupported_terms=unsupported, action=action, action_needs_ids=needs_ids, action_too_large=too_large,
        skipped_tools=tools[max_steps:],
    )


# ---------------------------------------------------------------------------
# Tools: thin adapters over the existing functions
# ---------------------------------------------------------------------------

def _scoped_test_cases(plan: AgentPlan, ws: Workspace) -> list[TestCase]:
    if plan.test_case_ids:
        return [tc for tc in ws.test_cases if tc.id in plan.test_case_ids]
    if plan.requirement_ids:
        return [tc for tc in ws.test_cases if tc.requirement_id in plan.requirement_ids]
    return list(ws.test_cases)


def _scoped_requirements(plan: AgentPlan, ws: Workspace) -> list[Requirement]:
    ids = set(plan.requirement_ids) | {tc.requirement_id for tc in ws.test_cases if tc.id in plan.test_case_ids}
    return [r for r in ws.requirements if r.id in ids] if ids else list(ws.requirements)


def _critic(plan: AgentPlan, ws: Workspace, _impact: ChangeImpact | None) -> StepResult:
    step = StepResult(tool="critic")
    cases = _scoped_test_cases(plan, ws)
    with_problems = []
    for tc in cases:
        issues = critique(tc, ws)
        for issue in issues:
            item = Item(key=f"critic.{issue.code}", params=issue.params, ref=tc.id,
                        topic=f"critic.criterion.{issue.criterion}")
            (step.unknowns if issue.unknown else step.problems).append(item)
        if any(not i.unknown for i in issues):
            with_problems.append(tc.id)
    step.summary = Item(key="qatask.summary.critic", params={
        "checked": str(len(cases)), "problems": str(len(with_problems)),
    })
    if with_problems:
        step.recommendations.append(Item(key="qatask.rec.critic_fix", params={"ids": ", ".join(with_problems)}))
    if step.unknowns:
        step.recommendations.append(Item(key="qatask.rec.critic_unknown"))
    return step


def _coverage(plan: AgentPlan, ws: Workspace, _impact: ChangeImpact | None) -> StepResult:
    step = StepResult(tool="coverage")
    requirements = _scoped_requirements(plan, ws)
    full = 0
    incomplete = []
    for req in requirements:
        coverage = scenario_coverage(req, ws.tests_for(req.id))
        if coverage.missing:
            incomplete.append(req.id)
            step.problems.append(Item(key="qatask.coverage.missing", ref=req.id,
                                      terms=[f"scenario.{c.value}" for c in coverage.missing]))
        elif coverage.percent is not None:
            full += 1
        if coverage.percent is None:
            step.unknowns.append(Item(key="qatask.coverage.unknown", ref=req.id))
        elif coverage.unknown:
            step.unknowns.append(Item(key="qatask.coverage.unknown_categories", ref=req.id,
                                      terms=[f"scenario.{c.value}" for c in coverage.unknown]))
    step.summary = Item(key="qatask.summary.coverage", params={
        "checked": str(len(requirements)), "full": str(full), "incomplete": str(len(incomplete)),
    })
    if incomplete:
        step.recommendations.append(Item(key="qatask.rec.coverage", params={"ids": ", ".join(incomplete)}))
    return step


def _impact(_plan: AgentPlan, _ws: Workspace, impact: ChangeImpact | None) -> StepResult:
    step = StepResult(tool="impact")
    if impact is None:
        step.summary = Item(key="qatask.summary.impact_none")
        return step
    if impact.status == "unknown":
        step.summary = Item(key="qatask.summary.impact_unknown", params={"title": impact.previous_title})
        step.unknowns.append(Item(key="qatask.impact.previous_unknown", params={"title": impact.previous_title}))
        step.recommendations.append(Item(key="qatask.rec.impact_compare_manually"))
        return step
    counts = {kind: str(sum(c.kind == kind for c in impact.changes))
              for kind in ("added", "modified", "removed", "unknown")}
    step.summary = Item(key="qatask.summary.impact", params={"title": impact.previous_title, **counts})
    for tc in impact.test_cases:
        step.problems.append(Item(key="qatask.impact.test_case", ref=tc.test_case_id,
                                  params={"req": tc.requirement_id},
                                  terms=[f"review.{tc.review_status.value}", f"impact.reason.{tc.reason}"]))
    for change in impact.changes:
        if change.kind == "unknown":
            step.unknowns.append(Item(key="qatask.impact.change_unknown", ref=change.new_id or change.old_id))
    if impact.test_cases:
        step.recommendations.append(Item(key="qatask.rec.impact_review", params={
            "ids": ", ".join(tc.test_case_id for tc in impact.test_cases),
        }))
    if added := [c.new_id for c in impact.changes if c.kind == "added"]:
        step.recommendations.append(Item(key="qatask.rec.impact_added", params={"ids": ", ".join(added)}))
    return step


def _traceability(plan: AgentPlan, ws: Workspace, _impact: ChangeImpact | None) -> StepResult:
    step = StepResult(tool="traceability")
    rows = build_rtm(ws)
    gaps = traceability_gaps(rows, ws)
    if plan.test_case_ids or plan.requirement_ids:
        scope = {r.id for r in _scoped_requirements(plan, ws)}
        rows = [row for row in rows if row.requirement_id in scope]
        gaps = gaps.model_copy(update={
            "untested": [i for i in gaps.untested if i in scope],
            "unknown": [i for i in gaps.unknown if i in scope],
            "unlinked": [i for i in gaps.unlinked if i in plan.test_case_ids],
        })
    partial = [row.requirement_id for row in rows if row.coverage == Coverage.PARTIAL]
    step.problems += [Item(key="qatask.trace.untested", ref=req_id) for req_id in gaps.untested]
    step.problems += [Item(key="qatask.trace.unlinked", ref=tc_id) for tc_id in gaps.unlinked]
    step.problems += [Item(key="qatask.trace.not_approved", ref=req_id) for req_id in partial]
    step.unknowns += [Item(key="qatask.trace.unknown", ref=req_id) for req_id in gaps.unknown]
    step.summary = Item(key="qatask.summary.traceability", params={
        "requirements": str(len(rows)),
        "covered": str(sum(row.coverage == Coverage.COVERED for row in rows)),
        "gaps": str(gaps.gaps),
    })
    if gaps.untested:
        step.recommendations.append(Item(key="qatask.rec.trace_untested", params={"ids": ", ".join(gaps.untested)}))
    if gaps.unlinked:
        step.recommendations.append(Item(key="qatask.rec.trace_unlinked", params={"ids": ", ".join(gaps.unlinked)}))
    if partial:
        step.recommendations.append(Item(key="qatask.rec.trace_approve", params={"ids": ", ".join(partial)}))
    if gaps.unknown:
        step.recommendations.append(Item(key="qatask.rec.trace_clarify", params={"ids": ", ".join(gaps.unknown)}))
    return step


def _suites(_plan: AgentPlan, ws: Workspace, _impact: ChangeImpact | None) -> StepResult:
    step = StepResult(tool="suites")
    plan = plan_suites(ws)
    step.summary = Item(key="qatask.summary.suites", params={
        kind.value: str(len(plan.suites[kind])) for kind in SuiteKind
    })
    if not plan.suites[SuiteKind.REGRESSION]:
        step.problems.append(Item(key="qatask.suites.no_approved"))
        step.recommendations.append(Item(key="qatask.rec.suites_approve"))
    elif plan.smoke_missing:
        step.problems.append(Item(key="qatask.suites.smoke_missing", params={"ids": ", ".join(plan.smoke_missing)}))
        step.recommendations.append(Item(key="qatask.rec.suites_smoke"))
    return step


_RUNNERS: dict[Tool, Callable[[AgentPlan, Workspace, ChangeImpact | None], StepResult]] = {
    "critic": _critic,
    "coverage": _coverage,
    "impact": _impact,
    "traceability": _traceability,
    "suites": _suites,
}


# ---------------------------------------------------------------------------
# Running and applying
# ---------------------------------------------------------------------------

def run_task(
    task: str,
    workspace: Workspace,
    previous_impact: Callable[[Workspace], ChangeImpact | None] | None = None,
    max_steps: int = MAX_STEPS,
) -> AgentResult:
    """Plan the task and run its tools. Never changes `workspace`.

    `previous_impact` computes the Change Impact when the document has none stored
    (it is stored when a new version is analyzed).
    """
    task = task.strip()
    if not task:
        return AgentResult(task=task, document_hash=workspace.document_hash, status="error",
                           error="qatask.error.empty")
    if len(task) > MAX_TASK_LENGTH:
        return AgentResult(task=task[:MAX_TASK_LENGTH], document_hash=workspace.document_hash, status="error",
                           error="qatask.error.too_long")
    plan = plan_task(task, workspace, max_steps)
    if plan.unknown_ids and not plan.test_case_ids and not plan.requirement_ids:
        # Checking the whole document instead of the IDs asked about would answer another question.
        return AgentResult(task=task, document_hash=workspace.document_hash, status="error", plan=plan,
                           error="qatask.error.unknown_ids")
    result = AgentResult(task=task, document_hash=workspace.document_hash, status="done", plan=plan,
                         action=plan.action)
    if not plan.tools:
        result.status = "unsupported"
        return result

    impact = workspace.change_impact
    for tool in plan.tools:
        try:
            if tool == "impact" and impact is None and previous_impact is not None:
                impact = previous_impact(workspace)
            step = _RUNNERS[tool](plan, workspace.model_copy(deep=True), impact)
        except Exception as error:  # noqa: BLE001 - one failing tool must not lose the others' results
            step = StepResult(tool=tool, status="error", error=type(error).__name__)
        result.steps.append(step)
    failed = sum(step.status == "error" for step in result.steps)
    if failed == len(result.steps):
        result.status = "error"
        result.error = "qatask.error.all_failed"
    elif failed:
        result.status = "partial"
    return result


def apply_action(workspace: Workspace, action: ProposedAction) -> list[str]:
    """Apply a confirmed status change; returns the IDs that changed. Call only after the user confirms.

    Raises ValueError when a test case is no longer in the document (nothing is changed then).
    """
    known = {tc.id for tc in workspace.test_cases}
    if missing := [tc_id for tc_id in action.test_case_ids if tc_id not in known]:
        raise ValueError(", ".join(missing))
    targets = set(action.test_case_ids)
    changed = [tc.id for tc in workspace.test_cases if tc.id in targets and tc.review_status != action.status]
    workspace.test_cases = [
        tc.model_copy(update={"review_status": action.status}) if tc.id in changed else tc
        for tc in workspace.test_cases
    ]
    return changed
