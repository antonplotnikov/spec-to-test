"""Requirements Traceability Matrix and QA dashboard figures.

Everything here is computed from the workspace on demand, so the RTM, the
dashboard and the exports always reflect the latest edits.

Coverage status per requirement:
- not_covered: no test cases linked
- partial:     test cases exist, but none is Approved
- covered:     at least one linked test case is Approved
"""

from collections import Counter
from enum import StrEnum

from pydantic import BaseModel

from spec_to_test.models import ReviewStatus, Severity, Workspace
from spec_to_test.quality import QualityScore, score_all
from spec_to_test.scenario_coverage import ScenarioCoverage, scenario_coverage

SEVERITY_ORDER = [Severity.HIGH, Severity.MEDIUM, Severity.LOW]


class Coverage(StrEnum):
    NOT_COVERED = "not_covered"
    PARTIAL = "partial"
    COVERED = "covered"


class RTMRow(BaseModel):
    requirement_id: str
    requirement_text: str
    quality_score: int
    quality_grade: str
    open_issues: list[str]  # finding types
    severities: list[Severity]
    test_case_ids: list[str]
    approved_test_case_ids: list[str]
    defect_ids: list[str]
    coverage: Coverage
    # Applicable/covered scenario categories; independent of the Approved-based coverage.
    scenarios: ScenarioCoverage | None = None

    @property
    def highest_severity(self) -> Severity | None:
        return next((s for s in SEVERITY_ORDER if s in self.severities), None)


def coverage_of(workspace: Workspace, requirement_id: str) -> Coverage:
    tests = workspace.tests_for(requirement_id)
    if not tests:
        return Coverage.NOT_COVERED
    if any(tc.review_status == ReviewStatus.APPROVED for tc in tests):
        return Coverage.COVERED
    return Coverage.PARTIAL


def build_rtm(workspace: Workspace, scores: dict[str, QualityScore] | None = None) -> list[RTMRow]:
    scores = scores if scores is not None else score_all(workspace.requirements, workspace.findings)
    rows = []
    for req in workspace.requirements:
        findings = workspace.open_findings_for(req.id)
        tests = workspace.tests_for(req.id)
        rows.append(
            RTMRow(
                requirement_id=req.id,
                requirement_text=req.text,
                quality_score=scores[req.id].score,
                quality_grade=scores[req.id].grade,
                open_issues=[f.type.value for f in findings],
                severities=[f.severity for f in findings],
                test_case_ids=[tc.id for tc in tests],
                approved_test_case_ids=[
                    tc.id for tc in tests if tc.review_status == ReviewStatus.APPROVED
                ],
                defect_ids=[d.id for d in workspace.defects_for(req.id)],
                coverage=coverage_of(workspace, req.id),
                scenarios=scenario_coverage(req, tests),
            )
        )
    return rows


def orphan_test_case_ids(workspace: Workspace) -> list[str]:
    """Test cases linked to a requirement ID that is not in the document."""
    known = {req.id for req in workspace.requirements}
    return [tc.id for tc in workspace.test_cases if tc.requirement_id not in known]


class TraceabilityGaps(BaseModel):
    """Missing links between requirements and test cases.

    untested: requirements without a test case whose text says what to test (a gap).
    unknown:  requirements without a test case whose text is not enough to tell what
              needs testing (Scenario Coverage Unknown); uncertain, not counted as a gap.
    unlinked: test cases linked to a requirement ID that is not in the document.
    """

    untested: list[str]
    unknown: list[str]
    unlinked: list[str]

    @property
    def gaps(self) -> int:
        return len(self.untested) + len(self.unlinked)


def traceability_gaps(rows: list[RTMRow], workspace: Workspace) -> TraceabilityGaps:
    without_tests = [row for row in rows if row.coverage == Coverage.NOT_COVERED]

    def is_unknown(row: RTMRow) -> bool:
        return row.scenarios is None or row.scenarios.percent is None

    return TraceabilityGaps(
        untested=[row.requirement_id for row in without_tests if not is_unknown(row)],
        unknown=[row.requirement_id for row in without_tests if is_unknown(row)],
        unlinked=orphan_test_case_ids(workspace),
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardSummary(BaseModel):
    requirements: int
    open_issues: int
    test_cases: int
    defects: int
    coverage_percent: float  # requirements with an Approved test case
    any_test_percent: float  # requirements with at least one test case
    average_quality: float | None
    severity_distribution: dict[str, int]  # open findings by severity
    review_distribution: dict[str, int]  # test cases by review status
    coverage_distribution: dict[str, int]


def _percent(part: int, total: int) -> float:
    return round(100 * part / total, 1) if total else 0.0


def summarize(rows: list[RTMRow], workspace: Workspace) -> DashboardSummary:
    """Summarize the given RTM rows (pass filtered rows to get filtered figures)."""
    ids = {row.requirement_id for row in rows}
    tests = [tc for tc in workspace.test_cases if tc.requirement_id in ids]
    severities = Counter(s.value for row in rows for s in row.severities)
    coverage = Counter(row.coverage.value for row in rows)
    return DashboardSummary(
        requirements=len(rows),
        open_issues=sum(len(row.open_issues) for row in rows),
        test_cases=len(tests),
        defects=sum(len(row.defect_ids) for row in rows),
        coverage_percent=_percent(coverage[Coverage.COVERED.value], len(rows)),
        any_test_percent=_percent(len(rows) - coverage[Coverage.NOT_COVERED.value], len(rows)),
        average_quality=round(sum(r.quality_score for r in rows) / len(rows), 1) if rows else None,
        severity_distribution={s.value: severities[s.value] for s in SEVERITY_ORDER},
        review_distribution={s.value: sum(tc.review_status == s for tc in tests) for s in ReviewStatus},
        coverage_distribution={c.value: coverage[c.value] for c in Coverage},
    )


def filter_rows(
    rows: list[RTMRow],
    severities: set[str] | None = None,
    coverage: set[str] | None = None,
    grades: set[str] | None = None,
    search: str = "",
) -> list[RTMRow]:
    """Keep rows matching every non-empty filter.

    `severities` keeps rows with at least one open issue of a selected severity.
    """
    needle = search.strip().lower()
    result = []
    for row in rows:
        if severities and not severities & {s.value for s in row.severities}:
            continue
        if coverage and row.coverage.value not in coverage:
            continue
        if grades and row.quality_grade not in grades:
            continue
        if needle and needle not in row.requirement_id.lower() and needle not in row.requirement_text.lower():
            continue
        result.append(row)
    return result
