import csv
import io

from spec_to_test.bug_reports import generate_defects
from spec_to_test.exports import (
    JIRA_BUG_HEADERS,
    JIRA_TEST_HEADERS,
    RTM_HEADERS,
    TESTRAIL_HEADERS,
    jira_defects_csv,
    jira_test_cases_csv,
    rtm_csv,
    safe_cell,
)
from spec_to_test.exports import (
    testrail_csv as build_testrail_csv,
)
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import ReviewStatus, TestCase, TestType, Workspace
from spec_to_test.rtm import build_rtm
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.test_generator import generate_test_cases


def parse(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def make_workspace(text: str) -> Workspace:
    result = analyze_requirements(extract_requirements(text))
    ws = Workspace(requirements=result.requirements, findings=result.findings)
    ws.test_cases = generate_test_cases(ws)
    return ws


def test_jira_test_cases_columns_and_content(example_text):
    ws = make_workspace(example_text)
    rows = parse(jira_test_cases_csv(ws))
    assert rows[0] == JIRA_TEST_HEADERS == ["Summary", "Issue Type", "Description", "Labels", "Labels", "Labels"]
    assert len(rows) == len(ws.test_cases) + 1
    first = dict(zip(["summary", "type", "description", "l1", "l2", "l3"], rows[1], strict=True))
    tc = ws.test_cases[0]
    assert first["summary"] == f"[{tc.id}] {tc.title}"
    assert first["type"] == "Task"
    assert "*Steps:*" in first["description"] and "*Expected result:*" in first["description"]
    assert first["l1"] == "spec-to-test" and first["l2"] == tc.requirement_id
    assert " " not in first["l3"]


def test_jira_issue_type_is_configurable(example_text):
    rows = parse(jira_test_cases_csv(make_workspace(example_text), issue_type="Test"))
    assert {row[1] for row in rows[1:]} == {"Test"}


def test_testrail_columns(example_text):
    ws = make_workspace(example_text)
    rows = parse(build_testrail_csv(ws))
    assert rows[0] == TESTRAIL_HEADERS
    record = dict(zip(rows[0], rows[1], strict=True))
    tc = ws.test_cases[0]
    assert record["Title"] == tc.title
    assert record["Section"] == record["References"] == tc.requirement_id
    assert record["Template"] == "Test Case (Text)"
    assert record["Steps"].startswith("1. ")
    assert record["Expected Result"] == tc.expected_result


def test_only_approved_filter(example_text):
    ws = make_workspace(example_text)
    ws.test_cases[2].review_status = ReviewStatus.APPROVED
    assert len(parse(build_testrail_csv(ws, only_approved=True))) == 2
    assert len(parse(jira_test_cases_csv(ws, only_approved=True))) == 2


def test_edits_are_reflected_in_exports(example_text):
    ws = make_workspace(example_text)
    ws.test_cases[0].title = "Edited title"
    ws.test_cases.pop(1)
    rows = parse(build_testrail_csv(ws))
    assert rows[1][0] == "Edited title"
    assert len(rows) == len(ws.test_cases) + 1


def test_orphan_test_cases_are_not_exported():
    ws = make_workspace("REQ-1: The system must save drafts.")
    ws.test_cases.append(
        TestCase(id="TC-999", requirement_id="REQ-404", title="Orphan", test_type=TestType.POSITIVE,
                 steps=["s"], expected_result="e")
    )
    assert "Orphan" not in build_testrail_csv(ws)


def test_jira_bug_csv(example_text):
    ws = make_workspace(example_text)
    defects = generate_defects(ws)
    rows = parse(jira_defects_csv(defects))
    assert rows[0] == JIRA_BUG_HEADERS
    record = rows[1]
    assert record[1] == "Bug"
    assert record[2] in {"High", "Medium", "Low"}
    assert "*Expected behavior:*" in record[3]


def test_rtm_csv(example_text):
    ws = make_workspace(example_text)
    rows = parse(rtm_csv(build_rtm(ws)))
    assert rows[0] == RTM_HEADERS
    assert [r[0] for r in rows[1:]] == [r.id for r in ws.requirements]


def test_formula_injection_is_neutralized():
    assert safe_cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert safe_cell("+1") == "'+1" and safe_cell("@cmd") == "'@cmd" and safe_cell("-2") == "'-2"
    assert safe_cell("Normal text") == "Normal text"
    ws = make_workspace("REQ-1: =cmd|' /C calc'!A0 must be shown as text.")
    for row in parse(build_testrail_csv(ws))[1:]:
        assert not any(cell.startswith(("=", "+", "@")) for cell in row)


def test_unicode_and_multiline_survive_round_trip():
    ws = make_workspace("REQ-1: Система повинна зберігати чернетки.")
    ws.test_cases[0].steps = ["Крок один", "Крок два, з комою"]
    record = parse(build_testrail_csv(ws))[1]
    assert record[6] == "1. Крок один\n2. Крок два, з комою"


def test_mapping_document_covers_every_column():
    from conftest import PROJECT_ROOT

    doc = (PROJECT_ROOT / "docs" / "EXPORTS.md").read_text(encoding="utf-8")
    for header in {*JIRA_TEST_HEADERS, *JIRA_BUG_HEADERS, *TESTRAIL_HEADERS, *RTM_HEADERS}:
        assert f"| {header}" in doc, header


# --- Markdown report and link integrity ------------------------------------------------

def test_markdown_report_contains_every_link(example_text):
    from spec_to_test.exports import markdown_report

    ws = make_workspace(example_text)
    ws.defects = generate_defects(ws)
    ws.test_cases[0].review_status = ReviewStatus.APPROVED
    report = markdown_report(ws, build_rtm(ws))
    assert report.startswith("# Spec-to-Test QA report")
    for req in ws.requirements:
        assert f"| {req.id} |" in report
    for tc in ws.test_cases:
        assert f"### {tc.id}:" in report
    for d in ws.defects:
        assert f"### {d.id}:" in report
    assert "| Coverage | " in report and "11.1%" in report


def test_markdown_report_escapes_user_text_and_is_localized():
    from spec_to_test.exports import markdown_report

    ws = make_workspace("REQ-1: The system must show [help](http://x) | and *stars*.")
    report = markdown_report(ws, build_rtm(ws), "uk")
    assert r"\[help\](http://x) \| and \*stars\*" in report
    assert report.startswith("# QA-звіт Spec-to-Test")


def test_every_export_links_to_existing_requirements(example_text):
    ws = make_workspace(example_text)
    known = {r.id for r in ws.requirements}
    testrail = parse(build_testrail_csv(ws))[1:]
    assert {row[1] for row in testrail} <= known  # Section
    assert {row[8] for row in testrail} <= known  # References
    jira = parse(jira_test_cases_csv(ws))[1:]
    assert {row[4] for row in jira} <= known  # requirement label
    rtm = {row[0]: row[6] for row in parse(rtm_csv(build_rtm(ws)))[1:]}
    for req in ws.requirements:
        assert rtm[req.id] == ", ".join(tc.id for tc in ws.tests_for(req.id))
