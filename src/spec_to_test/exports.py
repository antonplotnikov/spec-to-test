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

from spec_to_test.change_impact import Recommendation
from spec_to_test.execution import TestRun
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
        parts.append(
            f"*Test ID:* {tc.id} | *Type:* {tc.test_type.value} | *Review status:* {tc.review_status.value}"
            f" | *Priority:* {tc.priority.value}"
        )
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
        # The Text template has no description field, so the requirement wording and open
        # questions go into Preconditions: a tester in TestRail sees what the case verifies.
        req = workspace.requirement(tc.requirement_id)
        preconditions = [f"Requirement {tc.requirement_id}: {req.text if req else ''}"]
        preconditions += tc.preconditions
        if tc.assumptions:
            preconditions += [f"Assumption (not confirmed): {a}" for a in tc.assumptions]
        if tc.clarification_questions:
            preconditions += [f"Open question: {q}" for q in tc.clarification_questions]
        rows.append(
            [
                tc.title,
                tc.requirement_id,
                "Test Case (Text)",
                "Functional",
                tc.priority.value.capitalize(),
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


def impact_headers(lang: str) -> list[str]:
    return [
        t("column.id", lang), t("impact.rec.action", lang), t("impact.column.change", lang),
        t("column.test_cases", lang), t("impact.rec.regression", lang),
    ]


def impact_rows(recommendations: list[Recommendation], lang: str) -> list[list[object]]:
    return [
        [
            r.requirement_id, t(f"impact.action.{r.action}", lang), t(f"impact.kind.{r.change}", lang),
            ", ".join(r.test_case_ids) or "—", "✔" if r.regression else "—",
        ]
        for r in recommendations
    ]


def _impact_table(recommendations: list[Recommendation], lang: str,
                  decisions: dict[str, str] | None) -> tuple[list[str], list[list[object]]]:
    """Headers and rows; with `decisions` (requirement ID -> state label) a Decision column is added."""
    headers, rows = impact_headers(lang), impact_rows(recommendations, lang)
    if decisions is None:
        return headers, rows
    headers = [*headers, t("impact.decision.column", lang)]
    rows = [[*row, decisions.get(r.requirement_id, t("impact.decision.undecided", lang))]
            for row, r in zip(rows, recommendations, strict=True)]
    return headers, rows


def impact_csv(recommendations: list[Recommendation], lang: str = "en",
               decisions: dict[str, str] | None = None) -> str:
    """The recommendations of the change impact, one row per requirement. Suggestions only."""
    return _to_csv(*_impact_table(recommendations, lang, decisions))


def impact_markdown(workspace: Workspace, recommendations: list[Recommendation], lang: str = "en",
                    decisions: dict[str, str] | None = None) -> str:
    """The Impact Report: which version was compared, and what to do about each requirement."""
    impact = workspace.change_impact
    lines = [f"# {t('impact.report.title', lang)}", "", f"_{t('impact.report.note', lang)}_", ""]
    if impact is not None and impact.status == "compared":
        previous = t("impact.previous", lang, title=escape_markdown(impact.previous_title),
                     date=impact.previous_created_at[:16].replace("T", " "))
        lines += [previous, ""]
    lines += [f"## {t('impact.rec.heading', lang)}", ""]
    lines += _md_table(*_impact_table(recommendations, lang, decisions))
    return "\n".join(lines) + "\n"


def run_csv(run: TestRun, titles: dict[str, str], lang: str = "en") -> str:
    """The results of one test run, one row per test case. Titles come from the document (may be missing)."""
    headers = [t("column.test_id", lang), t("column.title", lang), t("column.status", lang),
               t("runs.comment", lang), t("runs.bug_id", lang), t("runs.updated", lang)]
    rows = [
        [r.test_case_id, titles.get(r.test_case_id, t("runs.removed", lang)), t(f"runs.status.{r.status.value}", lang),
         r.comment, r.bug_id, r.updated_at]
        for r in run.results
    ]
    return _to_csv(headers, rows)


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
