"""Missing test cases for the gaps a QA task found, made by the existing generator.

A Full check (spec_to_test.qa_agent.tasks) reports requirements without any test
case (traceability) and scenario categories no test case exercises, not even a
Draft (coverage). For those requirements `generate_missing` runs
spec_to_test.test_generator on the requirement alone and keeps only what is
missing:

- a requirement without test cases gets every case the generator makes for it;
- otherwise a generated case is kept only when it exercises a category no test
  case of the requirement exercises yet (scenario_coverage.categories_of_test_case),
  one case per category.

A generated case is never added twice: one with the same title, or the same type,
steps and expected result, as a test case of the requirement is left out, so a
second run adds nothing. Existing test cases are not changed. New ones are Draft,
linked to their requirement, with IDs after the last one.

The generator quotes the requirement as the expected result. Where an open finding
says that wording cannot be checked as it stands (a contradiction, vague wording,
no stated result, a limit without a value), the expected result is replaced by a
"needs clarification" line instead; the generator's clarification questions stay.
Categories the generator has no case for (permissions, state transitions, recovery,
a negative case without numbers) are reported, not invented: they need a test case
written by hand.
"""

from pydantic import BaseModel, Field

from spec_to_test.i18n import t
from spec_to_test.models import FindingType, Requirement, TestCase, Workspace
from spec_to_test.qa_agent.tasks import AgentResult
from spec_to_test.scenario_coverage import (
    ScenarioCategory,
    categories_of_test_case,
    categories_without_test_case,
    scenario_coverage,
)
from spec_to_test.test_generator import generate_test_cases, next_test_case_id

# Problem lines of a QA task result that name requirements missing test cases.
GAP_KEYS = ("qatask.coverage.no_test_case", "qatask.trace.untested")

# Open findings that leave the requirement's own wording without a checkable result.
UNCLEAR_FINDINGS = (
    FindingType.CONTRADICTION, FindingType.AMBIGUOUS_WORDING, FindingType.MISSING_EXPECTED_RESULT,
    FindingType.MISSING_BOUNDARY,
)


class RequirementGeneration(BaseModel):
    """What the generation did for one requirement."""

    requirement_id: str
    created: list[str] = Field(default_factory=list)  # IDs of the new test cases
    tests_before: int = 0
    tests_after: int = 0
    # Applicable categories no test case (of any status) exercises, before and after.
    missing_before: list[ScenarioCategory] = Field(default_factory=list)
    missing_after: list[ScenarioCategory] = Field(default_factory=list)
    # Open findings that kept the expected results of the new test cases undefined.
    unclear: list[FindingType] = Field(default_factory=list)
    # Share of applicable categories Approved test cases cover; Drafts do not change it.
    approved_percent: float | None = None


class MissingGeneration(BaseModel):
    created: list[TestCase] = Field(default_factory=list)
    requirements: list[RequirementGeneration] = Field(default_factory=list)


def gap_requirements(result: AgentResult, workspace: Workspace) -> list[str]:
    """Requirements the result reports as missing test cases, in document order."""
    named = {i for step in result.steps if step.status == "ok"
             for item in step.problems if item.key in GAP_KEYS for i in item.ids}
    return [r.id for r in workspace.requirements if r.id in named]


def _same(text: str) -> str:
    return " ".join(text.split()).casefold()


def _is_duplicate(case: TestCase, others: list[TestCase]) -> bool:
    content = (case.test_type, [_same(s) for s in case.steps], _same(case.expected_result))
    return any(_same(case.title) == _same(other.title)
               or content == (other.test_type, [_same(s) for s in other.steps], _same(other.expected_result))
               for other in others)


def _candidates(req: Requirement, workspace: Workspace, lang: str) -> list[TestCase]:
    """What the generator makes for the requirement alone, with its open findings."""
    return generate_test_cases(Workspace(requirements=[req], findings=workspace.findings), lang)


def _needs_clarification(case: TestCase, req: Requirement, unclear: list[FindingType], lang: str) -> TestCase:
    reasons = ", ".join(t(f"finding.{kind.value}", lang) for kind in unclear)
    return case.model_copy(update={
        "expected_result": t("qamissing.expected_unclear", lang, req=req.id, reasons=reasons),
    })


def generate_missing(workspace: Workspace, requirement_ids: list[str], lang: str = "en") -> MissingGeneration:
    """New Draft test cases for the named requirements. Never changes `workspace`: the caller adds `created`."""
    generation = MissingGeneration()
    wanted = set(requirement_ids)
    for req in workspace.requirements:
        if req.id not in wanted:
            continue
        existing = workspace.tests_for(req.id)
        before = categories_without_test_case(req, existing)
        missing = set(before)
        unclear = list(dict.fromkeys(f.type for f in workspace.open_findings_for(req.id)
                                     if f.type in UNCLEAR_FINDINGS))
        kept: list[TestCase] = []
        for case in _candidates(req, workspace, lang):
            if _is_duplicate(case, existing + kept):
                continue
            if existing:
                fills = categories_of_test_case(case, req) & missing
                if not fills:
                    continue
                missing -= fills
            if unclear:
                case = _needs_clarification(case, req, unclear, lang)
            case = case.model_copy(update={
                "id": next_test_case_id(workspace.test_cases + generation.created + kept),
            })
            kept.append(case)
        generation.created += kept
        after = existing + kept
        generation.requirements.append(RequirementGeneration(
            requirement_id=req.id, created=[tc.id for tc in kept], tests_before=len(existing),
            tests_after=len(after), missing_before=before,
            missing_after=categories_without_test_case(req, after), unclear=unclear if kept else [],
            approved_percent=scenario_coverage(req, after).percent,
        ))
    return generation
