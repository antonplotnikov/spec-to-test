"""CSV exports for Jira and TestRail imports, the RTM, and a Markdown QA report.

Column mappings are documented in docs/EXPORTS.md. Headers are always in
English so import wizards can auto-map them; cell values keep the text the
user wrote (any language).

Cells that start with =, +, -, @ (or tab/CR) are prefixed with an apostrophe
so spreadsheet apps do not run them as formulas (CSV injection).
"""

import csv
import io
import re
from collections.abc import Sequence

from spec_to_test.formatting import escape_markdown, markdown_cell
from spec_to_test.i18n import t
from spec_to_test.models import (
    DefectReport,
    ReviewStatus,
    Severity,
    TestCase,
    Workspace,
)
from spec_to_test.rtm import RTMRow, summarize

JIRA_TEST_HEADERS = ["Summary", "Issue Type", "Description", "Labels", "Labels", "Labels"]
JIRA_BUG_HEADERS = ["Summary", "Issue Type", "Priority", "Description", "Labels", "Labels"]
TESTRAIL_HEADERS = [
    "Title", "Section", "Template", "Type", "Priority",
    "Preconditions", "Steps", "Expected Result", "References",
]
RTM_HEADERS = [
    "Requirement ID", "Requirement", "Quality Score", "Coverage", "Open Issues",
    "Highest Severity", "Test Cases", "Approved Test Cases", "Bug Reports",
]

JIRA_PRIORITY = {Severity.HIGH: "High", Severity.MEDIUM: "Medium", Severity.LOW: "Low"}
DEFAULT_JIRA_TEST_ISSUE_TYPE = "Task"
LABEL = "spec-to-test"

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def _label(text: str) -> str:
    """Jira labels cannot contain spaces."""
    return re.sub(r"\s+", "_", text.strip())


def _to_csv(headers: list[str], rows: Sequence[Sequence[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([safe_cell(cell) for cell in row])
    return buffer.getvalue()


def exportable_test_cases(workspace: Workspace, only_approved: bool = False) -> list[TestCase]:
    known = {req.id for req in workspace.requirements}
    return [
        tc
        for tc in workspace.test_cases
        if tc.requirement_id in known
        and (not only_approved or tc.review_status == ReviewStatus.APPROVED)
    ]


def _numbered(items: list[str], marker: str | None = None) -> str:
    if marker:
        return "\n".join(f"{marker} {item}" for item in items)
    return "\n".join(f"{n}. {item}" for n, item in enumerate(items, start=1))


def jira_test_cases_csv(
    workspace: Workspace,
    only_approved: bool = False,
    issue_type: str = DEFAULT_JIRA_TEST_ISSUE_TYPE,
) -> str:
    rows = []
    for tc in exportable_test_cases(workspace, only_approved):
        req = workspace.requirement(tc.requirement_id)
        parts = [f"*Requirement:* {tc.requirement_id} — {req.text if req else ''}"]
        if tc.preconditions:
            parts.append("*Preconditions:*\n" + _numbered(tc.preconditions, "*"))
        parts.append("*Steps:*\n" + _numbered(tc.steps, "#"))
        parts.append("*Expected result:*\n" + tc.expected_result)
        if tc.assumptions:
            parts.append("*Assumptions (not confirmed):*\n" + _numbered(tc.assumptions, "*"))
        if tc.clarification_questions:
            parts.append("*Open questions:*\n" + _numbered(tc.clarification_questions, "*"))
        parts.append(f"*Test ID:* {tc.id} | *Type:* {tc.test_type.value} | *Review status:* {tc.review_status.value}")
        rows.append(
            [
                f"[{tc.id}] {tc.title}",
                issue_type,
                "\n\n".join(parts),
                LABEL,
                _label(tc.requirement_id),
                _label(f"test-{tc.test_type.value}"),
            ]
        )
    return _to_csv(JIRA_TEST_HEADERS, rows)


def jira_defects_csv(defects: list[DefectReport]) -> str:
    rows = []
    for d in defects:
        description = "\n\n".join(
            part
            for part in [
                d.description,
                f"*Expected behavior:*\n{d.expected_behavior}" if d.expected_behavior else "",
                f"*Context:*\n{d.reproduction_context}" if d.reproduction_context else "",
                f"*Bug ID:* {d.id} | *Requirement:* {d.requirement_id} | *Source:* {d.source.value}",
            ]
            if part
        )
        rows.append(
            [f"[{d.id}] {d.title}", "Bug", JIRA_PRIORITY[d.severity], description, LABEL, _label(d.requirement_id)]
        )
    return _to_csv(JIRA_BUG_HEADERS, rows)


def testrail_csv(workspace: Workspace, only_approved: bool = False) -> str:
    rows = []
    for tc in exportable_test_cases(workspace, only_approved):
        preconditions = list(tc.preconditions)
        if tc.assumptions:
            preconditions += [f"Assumption (not confirmed): {a}" for a in tc.assumptions]
        rows.append(
            [
                tc.title,
                tc.requirement_id,
                "Test Case (Text)",
                "Functional",
                "Medium",
                "\n".join(preconditions),
                _numbered(tc.steps),
                tc.expected_result,
                tc.requirement_id,
            ]
        )
    return _to_csv(TESTRAIL_HEADERS, rows)


def rtm_csv(rows: list[RTMRow]) -> str:
    return _to_csv(
        RTM_HEADERS,
        [
            [
                row.requirement_id,
                row.requirement_text,
                row.quality_score,
                row.coverage.value,
                "; ".join(row.open_issues),
                row.highest_severity.value if row.highest_severity else "",
                ", ".join(row.test_case_ids),
                ", ".join(row.approved_test_case_ids),
                ", ".join(row.defect_ids),
            ]
            for row in rows
        ],
    )


# ---------------------------------------------------------------------------
# Markdown report (human-readable, e.g. for a GitHub wiki or a pull request)
# ---------------------------------------------------------------------------

def _md_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    out = ["| " + " | ".join(markdown_cell(h) for h in headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(markdown_cell(cell) for cell in row) + " |" for row in rows]
    return out


def _md_list(items: list[str]) -> list[str]:
    return [f"- {escape_markdown(item)}" for item in items] or ["- —"]


def markdown_report(workspace: Workspace, rows: list[RTMRow], lang: str = "en") -> str:
    """Summary, traceability matrix, test cases and bug reports in one document."""
    summary = summarize(rows, workspace)
    out = [f"# {t('report.title', lang)}", "", f"_{t('report.note', lang)}_", ""]

    out += [f"## {t('report.summary', lang)}", ""]
    out += _md_table(
        [t("report.metric", lang), t("report.value", lang)],
        [
            [t("dash.requirements", lang), summary.requirements],
            [t("dash.open_issues", lang), summary.open_issues],
            [t("dash.test_cases", lang), summary.test_cases],
            [t("column.bugs", lang), len(workspace.defects)],
            [t("dash.coverage", lang), f"{summary.coverage_percent:g}%"],
            [t("dash.avg_quality", lang), "—" if summary.average_quality is None else f"{summary.average_quality:g}"],
        ],
    )

    out += ["", f"## {t('tab.rtm', lang)}", ""]
    out += _md_table(
        [
            t("column.id", lang), t("column.requirement", lang), t("column.quality", lang),
            t("column.open_issues", lang), t("column.test_cases", lang), t("column.approved", lang),
            t("column.bugs", lang), t("column.coverage", lang),
        ],
        [
            [
                row.requirement_id,
                row.requirement_text,
                row.quality_score,
                ", ".join(t(f"finding.{issue}", lang) for issue in row.open_issues) or "—",
                ", ".join(row.test_case_ids) or "—",
                ", ".join(row.approved_test_case_ids) or "—",
                ", ".join(row.defect_ids) or "—",
                t(f"coverage.{row.coverage.value}", lang),
            ]
            for row in rows
        ],
    )

    out += ["", f"## {t('tab.tests', lang)}", ""]
    cases = exportable_test_cases(workspace)
    if not cases:
        out.append(t("tests.none", lang))
    for tc in cases:
        out += [
            f"### {escape_markdown(tc.id)}: {escape_markdown(tc.title)}",
            "",
            f"- **{t('column.id', lang)}:** {escape_markdown(tc.requirement_id)}",
            f"- **{t('column.test_type', lang)}:** {t(f'test_type.{tc.test_type.value}', lang)}",
            f"- **{t('column.review', lang)}:** {t(f'review.{tc.review_status.value}', lang)}",
            "",
            f"**{t('tests.preconditions', lang)}**",
            "",
            *_md_list(tc.preconditions),
            "",
            f"**{t('tests.steps', lang)}**",
            "",
            *[f"{n}. {escape_markdown(step)}" for n, step in enumerate(tc.steps, start=1)],
            "",
            f"**{t('tests.expected', lang)}**",
            "",
            *_md_list(tc.expected_result.splitlines()),
            "",
        ]
        if tc.assumptions:
            out += [f"**{t('tests.assumptions', lang)}**", "", *_md_list(tc.assumptions), ""]
        if tc.clarification_questions:
            out += [f"**{t('tests.open_questions', lang)}**", "", *_md_list(tc.clarification_questions), ""]

    out += [f"## {t('tab.defects', lang)}", ""]
    if not workspace.defects:
        out.append(t("bugs.none", lang))
    for d in workspace.defects:
        out += [
            f"### {escape_markdown(d.id)}: {escape_markdown(d.title)}",
            "",
            f"- **{t('column.id', lang)}:** {escape_markdown(d.requirement_id)}",
            f"- **{t('column.severity', lang)}:** {t(f'severity.{d.severity.value}', lang)}",
            f"- **{t('column.source', lang)}:** {t(f'source.{d.source.value}', lang)}",
            "",
            f"**{t('bugs.description', lang)}**",
            "",
            *_md_list(d.description.splitlines()),
            "",
            f"**{t('bugs.expected', lang)}**",
            "",
            *_md_list(d.expected_behavior.splitlines()),
            "",
            f"**{t('bugs.context', lang)}**",
            "",
            *_md_list(d.reproduction_context.splitlines()),
            "",
        ]
    return "\n".join(out).rstrip() + "\n"
