from spec_to_test.bug_reports import generate_defects
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import ReviewStatus, TestCase, TestType, Workspace
from spec_to_test.rtm import (
    Coverage,
    CoverageLevels,
    build_rtm,
    coverage_levels,
    filter_rows,
    orphan_test_case_ids,
    summarize,
)
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.test_generator import generate_test_cases


def make_workspace(example_text) -> Workspace:
    result = analyze_requirements(extract_requirements(example_text))
    ws = Workspace(requirements=result.requirements, findings=result.findings)
    ws.test_cases = generate_test_cases(ws)
    return ws


def row(rows, req_id):
    return next(r for r in rows if r.requirement_id == req_id)


def test_rtm_links_requirements_tests_findings_and_bugs(example_text):
    ws = make_workspace(example_text)
    ws.defects = generate_defects(ws)
    rows = build_rtm(ws)
    assert [r.requirement_id for r in rows] == [r.id for r in ws.requirements]
    req5 = row(rows, "REQ-5")
    assert "ambiguous_wording" in req5.open_issues
    assert req5.test_case_ids == [tc.id for tc in ws.tests_for("REQ-5")]
    assert req5.defect_ids
    assert req5.coverage == Coverage.PARTIAL  # drafts only


def test_coverage_status_transitions(example_text):
    ws = make_workspace(example_text)
    assert row(build_rtm(ws), "REQ-2").coverage == Coverage.PARTIAL
    ws.tests_for("REQ-2")[0].review_status = ReviewStatus.APPROVED
    assert row(build_rtm(ws), "REQ-2").coverage == Coverage.COVERED
    ws.test_cases = [tc for tc in ws.test_cases if tc.requirement_id != "REQ-2"]
    assert row(build_rtm(ws), "REQ-2").coverage == Coverage.NOT_COVERED


def test_dashboard_summary_counts(example_text):
    ws = make_workspace(example_text)
    ws.test_cases[0].review_status = ReviewStatus.APPROVED
    summary = summarize(build_rtm(ws), ws)
    assert summary.requirements == 9
    assert summary.open_issues == len(ws.findings)
    assert summary.test_cases == len(ws.test_cases)
    assert summary.coverage_percent == round(100 / 9, 1)
    assert summary.any_test_percent == 100.0
    assert sum(summary.severity_distribution.values()) == len(ws.findings)
    assert summary.review_distribution["approved"] == 1
    assert sum(summary.coverage_distribution.values()) == 9


def test_filters(example_text):
    ws = make_workspace(example_text)
    rows = build_rtm(ws)
    high = filter_rows(rows, severities={"high"})
    assert high and all("high" in {s.value for s in r.severities} for r in high)
    assert {r.requirement_id for r in filter_rows(rows, search="req-5")} == {"REQ-5"}
    assert filter_rows(rows, coverage={"covered"}) == []
    poor_or_fair = filter_rows(rows, grades={"poor", "fair"})
    assert all(r.quality_grade in {"poor", "fair"} for r in poor_or_fair)
    assert filter_rows(rows) == rows


def test_filtered_summary_uses_only_filtered_rows(example_text):
    ws = make_workspace(example_text)
    rows = filter_rows(build_rtm(ws), search="REQ-5")
    summary = summarize(rows, ws)
    assert summary.requirements == 1
    assert summary.test_cases == len(ws.tests_for("REQ-5"))


def test_empty_summary():
    summary = summarize([], Workspace())
    assert summary.coverage_percent == 0.0 and summary.average_quality is None


def test_design_and_review_levels_are_kept_apart(example_text):
    ws = make_workspace(example_text)
    ws.test_cases[0].review_status = ReviewStatus.APPROVED  # one approved test, the rest drafts
    levels = coverage_levels(build_rtm(ws))
    # Every requirement has a test case (design); only the one with an Approved test is reviewed.
    assert levels.design == 100.0
    assert levels.review == round(100 / 9, 1)
    # No test run is recorded, so execution is unknown: never zero, and not implied by Approved.
    assert levels.execution is None


def test_approved_test_case_is_not_counted_as_executed(example_text):
    ws = make_workspace(example_text)
    for tc in ws.test_cases:
        tc.review_status = ReviewStatus.APPROVED
    levels = coverage_levels(build_rtm(ws))
    assert levels.review == 100.0
    assert levels.execution is None


def test_coverage_levels_of_no_requirements():
    assert coverage_levels([]) == CoverageLevels(design=0.0, review=0.0)


def test_dashboard_summary_agrees_with_coverage_levels(example_text):
    ws = make_workspace(example_text)
    ws.test_cases[0].review_status = ReviewStatus.APPROVED
    rows = build_rtm(ws)
    summary = summarize(rows, ws)
    levels = coverage_levels(rows)
    assert (summary.any_test_percent, summary.coverage_percent) == (levels.design, levels.review)


def test_orphan_test_cases_are_detected():
    ws = Workspace(
        test_cases=[TestCase(id="TC-1", requirement_id="REQ-404", title="x", test_type=TestType.POSITIVE,
                             steps=["s"], expected_result="e")]
    )
    assert orphan_test_case_ids(ws) == ["TC-1"]
