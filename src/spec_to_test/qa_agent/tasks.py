"""QA tasks in plain text, answered with the app's existing rule-based tools.

The agent reads the task, picks the tools that answer it and runs each one once
on the open document:

- requirements: open findings of the rule engine (spec_to_test.rule_engine) stored
                with the document: contradictions, ambiguous wording, missing
                error handling, missing expected results
- critic:       Test Case Critic (spec_to_test.test_critic)
- coverage:     Scenario Coverage (spec_to_test.scenario_coverage)
- impact:       Change Impact (spec_to_test.change_impact)
- traceability: traceability gaps of the RTM (spec_to_test.rtm)
- suites:       Test Suite Planner (spec_to_test.suites)

The tools do the analysis; this module only routes the task to them and turns
their output into one result: conclusions, problems, unknowns and
recommendations. Tool selection is keyword-based (EN / UK / RU), no AI.

Each problem is reported once: the mirror line of a pair and lines of one tool
that differ only in their ID become one line naming every ID (see `_merge`).
Lines that only say test cases are not Approved yet (coverage, traceability and
suites count only Approved test cases) are kept apart from the problems and
summed up in one line, `AgentResult.approval`. Under each problem and unknown
the report quotes the requirements (with their line) and test cases it names
(`reference_lines`), so the user sees what to fix without looking it up; a
vague wording or a contradiction also gets the next step (`next_step_lines`).

The agent never changes the workspace. A request to change test case statuses
("approve TC-003") becomes a proposed action that the page applies with
`apply_action` only after the user confirms it. Test cases whose expected
results conflict with another test case (see test_critic.expectation_conflicts)
are left out of a proposed approval. Running, generating, editing or
deleting is not supported and is reported instead of attempted.
"""

import re
from collections import Counter
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import t
from spec_to_test.models import (
    ChangeImpact,
    ClarificationStatus,
    FindingType,
    Requirement,
    ReviewStatus,
    Source,
    TestCase,
    Workspace,
)
from spec_to_test.rtm import Coverage, build_rtm, traceability_gaps
from spec_to_test.rule_engine import _compile
from spec_to_test.scenario_coverage import scenario_coverage
from spec_to_test.suites import SuiteKind, plan_suites
from spec_to_test.test_critic import critique, expectation_conflicts

# "ai" is the optional AI review (spec_to_test.qa_agent.ai_review); it is not planned from the task.
Tool = Literal["requirements", "critic", "coverage", "impact", "traceability", "suites", "ai"]
TOOLS: tuple[Tool, ...] = ("requirements", "critic", "coverage", "impact", "traceability", "suites")

# At most this many tool calls per task.
MAX_STEPS = 6
MAX_TASK_LENGTH = 2000
# A proposed status change names at most this many test cases.
MAX_ACTION_TEST_CASES = 20

_TOOL_TERMS: dict[Tool, list[str]] = {
    "requirements": [
        "contradict*", "inconsisten*", "conflict*", "ambigu*", "error handling", "testable", "testability",
        "check requirements", "check the requirements",
        "противореч*", "неоднознач*", "двусмыслен*", "конфликт*", "обработка ошибок", "обработки ошибок",
        "проверь требования", "проверить требования", "проверка требований",
        "суперечн*", "суперечить", "протиріч*", "конфлікт*", "обробка помилок", "обробки помилок",
        "перевір вимоги", "перевірити вимоги", "перевірка вимог",
    ],
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
# "Is the document ready for testing?": both words in the task.
_READY = _compile(["ready", "готов*"])
_TESTING = _compile(["testing", "тестировани*", "тестуванн*"])
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
    refs: list[str] = Field(default_factory=list)  # further IDs of the same line (see _merge)
    topic: str = ""  # translation key of a short label shown before the line

    @property
    def ids(self) -> list[str]:
        return [i for i in (self.ref, *self.refs) if i]

    @property
    def mentions(self) -> set[str]:
        """Every ID the line names: its own and the other side of a pair ("ids", "related")."""
        named = {i.strip() for key in ("ids", "related") for i in self.params.get(key, "").split(",")}
        return (set(self.ids) | named) - {""}


class StepResult(BaseModel):
    tool: Tool
    status: Literal["ok", "error"] = "ok"
    summary: Item | None = None
    problems: list[Item] = Field(default_factory=list)
    unknowns: list[Item] = Field(default_factory=list)
    recommendations: list[Item] = Field(default_factory=list)
    # Lines that only say test cases are not Approved yet; summed up in AgentResult.approval.
    approval: list[Item] = Field(default_factory=list)
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
    # Test cases left out of a proposed approval: their expected results conflict with other test cases.
    action_conflicts: list[str] = Field(default_factory=list)
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
    # One line instead of the steps' `approval` lines: review status, not a problem of the texts.
    approval: Item | None = None
    # Title of every test case at the time of the run: generated test case IDs move when a requirement
    # gets more or fewer test cases, so compare_problems matches test cases by title.
    test_case_titles: dict[str, str] = Field(default_factory=dict)

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
    tools = [tool for tool in TOOLS if _PATTERNS[tool].search(task)
             or (tool == "requirements" and _READY.search(task) and _TESTING.search(task))]
    # "Full check" means every tool, but "delete everything" asks for something the agent does not do.
    if not unsupported and _EVERYTHING.search(task):
        tools = list(TOOLS)

    target = ReviewStatus.APPROVED if _APPROVE.search(task) else ReviewStatus.DRAFT if _TO_DRAFT.search(task) else None
    action = None
    needs_ids = too_large = False
    conflicting: list[str] = []
    if target is not None:
        if not tc_ids:
            needs_ids = True
        elif len(tc_ids) > MAX_ACTION_TEST_CASES:
            too_large = True
        else:
            if target == ReviewStatus.APPROVED:
                conflicting = [tc.id for tc in workspace.test_cases
                               if tc.id in tc_ids and expectation_conflicts(tc, workspace)]
            if approvable := [tc_id for tc_id in tc_ids if tc_id not in conflicting]:
                action = ProposedAction(test_case_ids=approvable, status=target)
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
        action_conflicts=conflicting, skipped_tools=tools[max_steps:],
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


# Rule engine findings the requirements step reports, in this order in its summary.
_FINDING_TYPES = (
    FindingType.CONTRADICTION, FindingType.AMBIGUOUS_WORDING, FindingType.MISSING_ERROR_HANDLING,
    FindingType.MISSING_EXPECTED_RESULT,
)


def _requirements(plan: AgentPlan, ws: Workspace, _impact: ChangeImpact | None) -> StepResult:
    """Open rule engine findings stored with the document; a contradiction is reported once per pair."""
    step = StepResult(tool="requirements")
    requirements = _scoped_requirements(plan, ws)
    scope = {r.id for r in requirements}
    seen: set[tuple[FindingType, frozenset[str]]] = set()
    counts = dict.fromkeys(_FINDING_TYPES, 0)
    with_findings: set[str] = set()
    for f in ws.findings:
        if (f.source != Source.RULE or f.status != ClarificationStatus.NEEDS_CLARIFICATION
                or f.type not in counts or not scope & {f.requirement_id, *f.related_requirement_ids}):
            continue
        identity = (f.type, frozenset([f.requirement_id, *f.related_requirement_ids]))
        if identity in seen:
            continue
        seen.add(identity)
        counts[f.type] += 1
        params = {"terms": ", ".join(f.matched_terms)}
        if f.type == FindingType.CONTRADICTION:
            params = {"related": ", ".join(f.related_requirement_ids),
                      "terms": " ↔ ".join(f"“{term}”" for term in f.matched_terms)}
        step.problems.append(Item(key=f"qatask.requirements.{f.type.value}", params=params, ref=f.requirement_id,
                                  topic=f"finding.{f.type.value}"))
        with_findings |= {f.requirement_id, *f.related_requirement_ids}
    step.summary = Item(key="qatask.summary.requirements", params={
        "checked": str(len(requirements)), **{kind.value: str(n) for kind, n in counts.items()},
    })
    if ids := [r.id for r in ws.requirements if r.id in with_findings]:
        step.recommendations.append(Item(key="qatask.rec.requirements_clarify", params={"ids": ", ".join(ids)}))
    return step


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
    gaps = []
    for req in requirements:
        tests = ws.tests_for(req.id)
        coverage = scenario_coverage(req, tests)
        # What is still missing when every test case counts has no test case at all, not even a Draft.
        drafts = scenario_coverage(req, [tc.model_copy(update={"review_status": ReviewStatus.APPROVED})
                                         for tc in tests])
        if coverage.missing:
            incomplete.append(req.id)
            if drafts.missing:
                gaps.append(req.id)
                step.problems.append(Item(key="qatask.coverage.no_test_case", ref=req.id,
                                          terms=[f"scenario.{c.value}" for c in drafts.missing]))
            if pending := [c for c in coverage.missing if c not in drafts.missing]:
                step.approval.append(Item(key="qatask.coverage.missing", ref=req.id,
                                          terms=[f"scenario.{c.value}" for c in pending]))
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
    if gaps:
        step.recommendations.append(Item(key="qatask.rec.coverage", params={"ids": ", ".join(gaps)}))
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
    step.approval += [Item(key="qatask.trace.not_approved", ref=req_id) for req_id in partial]
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
        step.approval.append(Item(key="qatask.suites.no_approved"))
    elif plan.smoke_missing:
        step.problems.append(Item(key="qatask.suites.smoke_missing", params={"ids": ", ".join(plan.smoke_missing)}))
        step.recommendations.append(Item(key="qatask.rec.suites_smoke"))
    return step


_RUNNERS: dict[Tool, Callable[[AgentPlan, Workspace, ChangeImpact | None], StepResult]] = {
    "requirements": _requirements,
    "critic": _critic,
    "coverage": _coverage,
    "impact": _impact,
    "traceability": _traceability,
    "suites": _suites,
}


# ---------------------------------------------------------------------------
# One line per problem
# ---------------------------------------------------------------------------

def _named(item: Item) -> frozenset[str]:
    return frozenset(i.strip() for i in item.params.get("ids", "").split(",") if i.strip())


def _merge(items: list[Item]) -> list[Item]:
    """Each problem of one tool once, in report order.

    The mirror line of a pair ("TC-007 conflicts with TC-012" and "TC-012 conflicts with
    TC-007") is dropped: the first one names both. Lines that differ only in their ID
    (the same template steps in TC-001 and TC-002) become the first one with the other
    IDs in `refs`. Key, params, terms and topic are kept as they are.
    """
    merged: list[Item] = []
    pairs: set[tuple[object, ...]] = set()
    by_text: dict[tuple[object, ...], Item] = {}
    for item in items:
        if named := _named(item):
            rest = tuple(sorted((k, v) for k, v in item.params.items() if k != "ids"))
            pair = (item.key, item.topic, tuple(item.terms), rest, named | {item.ref})
            if pair in pairs:
                continue
            pairs.add(pair)
        text = (item.key, item.topic, tuple(item.terms), tuple(sorted(item.params.items())))
        if item.ref and (first := by_text.get(text)) is not None:
            first.refs += [i for i in item.ids if i not in first.ids]
            continue
        item = item.model_copy(deep=True)
        merged.append(item)
        if item.ref:
            by_text[text] = item
    return merged


def _approval_summary(steps: list[StepResult], plan: AgentPlan, ws: Workspace) -> Item | None:
    """One line for the steps' "not Approved" lines: how many test cases, which tools, which requirements."""
    lines = [(step.tool, item) for step in steps for item in step.approval]
    if not lines:
        return None
    named = {i for _, item in lines for i in item.ids}
    ids = [r.id for r in ws.requirements if r.id in named]
    cases = _scoped_test_cases(plan, ws)
    return Item(key="qatask.approval.summary_ids" if ids else "qatask.approval.summary", params={
        "draft": str(sum(tc.review_status != ReviewStatus.APPROVED for tc in cases)), "total": str(len(cases)),
        "ids": ", ".join(ids),
    }, terms=[f"qatask.tool.{tool}" for tool in dict.fromkeys(tool for tool, _ in lines)])


# ---------------------------------------------------------------------------
# What a report line refers to
# ---------------------------------------------------------------------------

# A quoted requirement text or test case title is cut to this many characters.
REFERENCE_TEXT_LENGTH = 160
# At most this many are quoted under one line; the rest are counted (their IDs are in the line itself).
MAX_REFERENCES = 5
# Change Impact lines name IDs of the previous version, which may now mean another requirement or test case.
_NO_REFERENCES = ("qatask.impact.",)


class Reference(BaseModel):
    """A requirement or test case a report line names, as it is in the document now."""

    id: str
    kind: Literal["requirement", "test_case"]
    text: str  # the requirement text or the test case title, shortened
    line: int | None = None  # requirement: its line in the source document
    requirement_id: str = ""  # test case: the requirement it tests
    status: ReviewStatus | None = None  # test case: its review status


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= REFERENCE_TEXT_LENGTH else text[:REFERENCE_TEXT_LENGTH - 1].rstrip() + "…"


def references(item: Item, workspace: Workspace) -> list[Reference]:
    """The requirements and test cases `item` names, its own IDs first. IDs not in the document are left out."""
    if item.key.startswith(_NO_REFERENCES):
        return []
    named = [i.strip() for key in ("ids", "related") for i in item.params.get(key, "").split(",")]
    requirements = {r.id: r for r in workspace.requirements}
    test_cases = {tc.id: tc for tc in workspace.test_cases}
    found: list[Reference] = []
    for i in dict.fromkeys(i for i in (*item.ids, *named) if i):
        if (req := requirements.get(i)) is not None:
            found.append(Reference(id=i, kind="requirement", text=_short(req.text), line=req.source_line))
        elif (tc := test_cases.get(i)) is not None:
            found.append(Reference(id=i, kind="test_case", text=_short(tc.title), requirement_id=tc.requirement_id,
                                   status=tc.review_status))
    return found


def reference_lines(lang: str, item: Item, workspace: Workspace) -> list[str]:
    """Indented Markdown list lines under a report line: the text of each requirement and test case it names."""
    found = references(item, workspace)
    lines = []
    for ref in found[:MAX_REFERENCES]:
        if ref.kind == "test_case":
            assert ref.status is not None
            text = t("qatask.ref.test_case", lang, id=ref.id, req=ref.requirement_id,
                     status=t(f"review.{ref.status.value}", lang), text=ref.text)
        elif ref.line is not None:
            text = t("qatask.ref.requirement_line", lang, id=ref.id, line=ref.line, text=ref.text)
        else:
            text = t("qatask.ref.requirement", lang, id=ref.id, text=ref.text)
        lines.append(f"  - {escape_markdown(text)}")
    if len(found) > MAX_REFERENCES:
        lines.append(f"  - {escape_markdown(t('qatask.ref.more', lang, count=len(found) - MAX_REFERENCES))}")
    return lines


# Problems whose next step says more than the line itself. Vague wording: the clarification
# question of the finding (the one the Analysis page shows). A contradiction is not decided
# here: the requirements it names have to be agreed on one wording.
_NEXT_STEPS = {
    "qatask.requirements.ambiguous_wording": "question.ambiguous_wording",
    "qatask.requirements.contradiction": "qatask.next.contradiction",
}


def next_step_lines(lang: str, item: Item) -> list[str]:
    """An indented Markdown list line under a report line: what to ask or agree on to resolve it, or none."""
    key = _NEXT_STEPS.get(item.key)
    if key is None:
        return []
    if key.startswith("question."):
        text = t("qatask.next.ask", lang, question=t(key, lang, terms=item.params.get("terms", "")))
    else:
        related = (i.strip() for i in item.params.get("related", "").split(","))
        text = t(key, lang, ids=", ".join(dict.fromkeys(i for i in (*item.ids, *related) if i)))
    return [f"  - **{t('qatask.next.label', lang)}:** {escape_markdown(text)}"]


# ---------------------------------------------------------------------------
# Compared with the previous run
# ---------------------------------------------------------------------------

# Change Impact lines are about one pair of versions and the AI review gives other lines on every run:
# a line of theirs gone or added says nothing about the fixes.
_NOT_COMPARED: frozenset[Tool] = frozenset({"impact", "ai"})


class ProblemComparison(BaseModel):
    """What happened to the previous run's problems.

    Counted per problem: one kind of problem of one requirement or test case, so a line naming
    two test cases is two problems. resolved + still_open + unmatched_before are all problems of
    the previous run; still_open + new + unmatched_now all problems of this one. The lists group
    the problems back into the lines of `AgentResult.problems`, cut to the IDs they are about.
    """

    resolved_count: int = 0
    still_open: int = 0
    new_count: int = 0
    # Problems of test cases that cannot be told apart: a title shared by several test cases in either
    # run, or a run without test case titles (result.json written before they were kept). Whether
    # they were fixed is unknown, so they are neither resolved nor new.
    unmatched_before_count: int = 0
    unmatched_now_count: int = 0
    resolved: list[Item] = Field(default_factory=list)  # previous lines
    new: list[Item] = Field(default_factory=list)  # current lines
    unmatched_before: list[Item] = Field(default_factory=list)
    unmatched_now: list[Item] = Field(default_factory=list)
    not_compared: list[Tool] = Field(default_factory=list)  # tools whose problems are left out
    # Test cases of `resolved` and `unmatched_before` lines: their title in the previous run
    # (the ID may now be another test case).
    previous_titles: dict[str, str] = Field(default_factory=dict)
    current_titles: dict[str, str] = Field(default_factory=dict)  # of the `unmatched_now` lines


# The IDs test_generator gives: a test case ID in a result that kept no titles.
_TEST_CASE_ID = re.compile(r"TC-\d+")

_Unit = tuple[object, ...]


def _problem_units(item: Item, identity: Callable[[str], object | None]) -> list[tuple[str, _Unit | None]]:
    """Each problem of a line: (ID, identity), None when its test case cannot be told apart."""
    if ids := item.ids or sorted(_named(item)):
        return [(i, None if (who := identity(i)) is None else (item.key, item.topic, who)) for i in ids]
    return [("", (item.key, item.topic, tuple(item.terms), tuple(sorted(item.params.items()))))]


def _only(item: Item, ids: list[str], units: list[tuple[str, _Unit | None]]) -> Item:
    """The line cut to `ids`: its own IDs, or its "ids" parameter when it has none."""
    if len(ids) == len(units):
        return item
    if item.ids:
        return item.model_copy(update={"ref": ids[0], "refs": ids[1:]})
    return item.model_copy(update={"params": item.params | {"ids": ", ".join(ids)}})


def compare_problems(previous: AgentResult, current: AgentResult) -> ProblemComparison:
    """Resolved, still open and new problems of the tools that ran in both results.

    Problems are matched by kind and ID (requirement or test case), not by text: a vague
    wording of REQ-3 reworded but still vague stays open. Test cases are matched by title
    (see AgentResult.test_case_titles), and only by a title no other test case has in either
    run and not taken over by another test case under the same ID; the others are counted
    as unmatched instead of a guess.
    """
    ran = [{s.tool for s in r.steps if s.status == "ok"} for r in (previous, current)]
    compared = (ran[0] & ran[1]) - _NOT_COMPARED
    every = [s.tool for r in (previous, current) for s in r.steps]
    titled = bool(previous.test_case_titles and current.test_case_titles)
    known = previous.test_case_titles.keys() | current.test_case_titles.keys()
    shared = {title for r in (previous, current) for title, n in Counter(r.test_case_titles.values()).items()
              if n > 1}

    def identity(i: str, titles: dict[str, str], other: dict[str, str]) -> object | None:
        if not titled:
            return None if i in known or _TEST_CASE_ID.fullmatch(i) else i
        if (title := titles.get(i)) is None:
            return i
        if title in shared:
            return None
        # A title the other run lacks, while this ID there has a title this run lacks: the test
        # case was renamed (its requirement reworded) or replaced by another one.
        if title not in other.values() and (there := other.get(i)) is not None and there not in titles.values():
            return None
        return ("test case", title)

    def units(result: AgentResult, other: AgentResult) -> list[tuple[Item, list[tuple[str, _Unit | None]]]]:
        titles, other_titles = result.test_case_titles, other.test_case_titles
        return [(item, _problem_units(item, lambda i: identity(i, titles, other_titles)))
                for s in result.steps if s.tool in compared for item in s.problems]

    before, now = units(previous, current), units(current, previous)
    old_units = {u for _, found in before for _, u in found if u is not None}
    now_units = {u for _, found in now for _, u in found if u is not None}

    def lines(found_lines: list[tuple[Item, list[tuple[str, _Unit | None]]]], keep: Callable[[_Unit | None], bool]
              ) -> list[Item]:
        return [_only(item, ids, found) for item, found in found_lines if (ids := [i for i, u in found if keep(u)])]

    def unmatched(found_lines: list[tuple[Item, list[tuple[str, _Unit | None]]]]) -> int:
        return len({(item.key, item.topic, i) for item, found in found_lines for i, u in found if u is None})

    comparison = ProblemComparison(
        resolved_count=len(old_units - now_units), still_open=len(old_units & now_units),
        new_count=len(now_units - old_units),
        unmatched_before_count=unmatched(before), unmatched_now_count=unmatched(now),
        resolved=lines(before, lambda u: u is not None and u not in now_units),
        new=lines(now, lambda u: u is not None and u not in old_units),
        unmatched_before=lines(before, lambda u: u is None), unmatched_now=lines(now, lambda u: u is None),
        not_compared=[tool for tool in dict.fromkeys(every) if tool not in compared])
    comparison.previous_titles = {i: previous.test_case_titles[i]
                                  for item in comparison.resolved + comparison.unmatched_before
                                  for i in item.ids if i in previous.test_case_titles}
    comparison.current_titles = {i: current.test_case_titles[i] for item in comparison.unmatched_now
                                 for i in item.ids if i in current.test_case_titles}
    return comparison


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
                         action=plan.action, test_case_titles={tc.id: tc.title for tc in workspace.test_cases})
    if not plan.tools:
        result.status = "unsupported"
        return result

    impact = workspace.change_impact
    for tool in plan.tools:
        try:
            if tool == "impact" and impact is None and previous_impact is not None:
                impact = previous_impact(workspace)
            step = _RUNNERS[tool](plan, workspace.model_copy(deep=True), impact)
            step.problems, step.unknowns = _merge(step.problems), _merge(step.unknowns)
        except Exception as error:  # noqa: BLE001 - one failing tool must not lose the others' results
            step = StepResult(tool=tool, status="error", error=type(error).__name__)
        result.steps.append(step)
    result.approval = _approval_summary(result.steps, plan, workspace)
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
