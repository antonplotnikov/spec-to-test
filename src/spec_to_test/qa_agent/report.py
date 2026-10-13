"""QA report of one run: results, requirement coverage, bug reports, evidence.

Coverage per requirement is computed from the run's results only:
- failed       at least one linked case failed;
- blocked      none failed, at least one was blocked;
- passed       every linked case passed;
- partial      some passed, the others were not run;
- not_run      linked cases exist, none was executed;
- not_covered  the requirement has no case in this run.
"""

import io
import json
import zipfile
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from spec_to_test.exports import _to_csv
from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import t
from spec_to_test.models import Requirement
from spec_to_test.qa_agent.bugs import bug_markdown
from spec_to_test.qa_agent.executor import SCREENSHOT_WITHHELD
from spec_to_test.qa_agent.models import QARun, RunStatus

MAX_BUNDLE_FILE = 20_000_000


class CoverageStatus(StrEnum):
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"
    NOT_COVERED = "not_covered"


class RequirementCoverage(BaseModel):
    requirement_id: str
    requirement_text: str = ""
    case_ids: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    bug_ids: list[str] = Field(default_factory=list)
    status: CoverageStatus


def _status(counts: dict[str, int]) -> CoverageStatus:
    if not sum(counts.values()):
        return CoverageStatus.NOT_COVERED
    if counts["failed"]:
        return CoverageStatus.FAILED
    if counts["blocked"]:
        return CoverageStatus.BLOCKED
    if counts["passed"]:
        return CoverageStatus.PARTIAL if counts["not_run"] else CoverageStatus.PASSED
    return CoverageStatus.NOT_RUN


def coverage(run: QARun, requirements: list[Requirement] | None = None) -> list[RequirementCoverage]:
    """One row per requirement of the document (when given) plus any other requirement the run touched."""
    texts = {r.id: r.text for r in requirements or []}
    order = list(texts)
    order += [r.requirement_id for r in run.results if r.requirement_id not in texts and r.requirement_id not in order]
    rows = []
    for req_id in dict.fromkeys(order):
        linked = [r for r in run.results if r.requirement_id == req_id]
        counts = {s.value: sum(r.status == s for r in linked) for s in RunStatus}
        rows.append(RequirementCoverage(
            requirement_id=req_id,
            requirement_text=texts.get(req_id, ""),
            case_ids=[r.case_id for r in linked],
            counts=counts,
            bug_ids=[b.id for b in run.bugs if b.requirement_id == req_id],
            status=_status(counts),
        ))
    return rows


def summary(run: QARun, rows: list[RequirementCoverage]) -> dict[str, float | int]:
    counts = run.counts()
    executed = counts["passed"] + counts["failed"]
    with_cases = [r for r in rows if r.status != CoverageStatus.NOT_COVERED]
    return {
        "cases": len(run.results),
        **counts,
        "pass_rate": round(100 * counts["passed"] / executed, 1) if executed else 0.0,
        "requirements": len(rows),
        "requirements_with_cases": len(with_cases),
        "requirements_passed": sum(r.status == CoverageStatus.PASSED for r in rows),
        "requirements_failed": sum(r.status == CoverageStatus.FAILED for r in rows),
        "bugs": len(run.bugs),
    }


def _cell(text: object) -> str:
    return escape_markdown(str(text)).replace("|", "\\|").replace("\n", " ")


def markdown_report(run: QARun, requirements: list[Requirement] | None = None, lang: str = "en") -> str:
    rows = coverage(run, requirements)
    stats = summary(run, rows)
    lines = [
        f"# {t('qaagent.report.title', lang)}",
        "",
        f"- {t('qaagent.report.target', lang)}: {run.target_url}",
        f"- {t('qaagent.report.run', lang)}: {run.id}" + (f" ({t('qaagent.report.retest_of', lang)} {run.parent_run_id})"
                                                           if run.parent_run_id else ""),
        f"- {t('qaagent.report.document', lang)}: {_cell(run.document_title or '—')}",
        f"- {t('qaagent.report.started', lang)}: {run.created_at} · {t('qaagent.report.finished', lang)}: "
        f"{run.finished_at or '—'} · {t('qaagent.report.state', lang)}: {t(f'qaagent.state.{run.state.value}', lang)}",
        f"- {t('qaagent.report.browser', lang)}: {run.browser or '—'}",
        "",
        f"## {t('qaagent.report.summary', lang)}",
        "",
        f"| {t('qaagent.status.passed', lang)} | {t('qaagent.status.failed', lang)} | "
        f"{t('qaagent.status.blocked', lang)} | {t('qaagent.status.not_run', lang)} | "
        f"{t('qaagent.report.pass_rate', lang)} | {t('qaagent.report.bugs', lang)} |",
        "|---|---|---|---|---|---|",
        f"| {stats['passed']} | {stats['failed']} | {stats['blocked']} | {stats['not_run']} | "
        f"{stats['pass_rate']}% | {stats['bugs']} |",
        "",
        t("qaagent.report.pass_rate_note", lang),
        "",
        f"## {t('qaagent.report.coverage', lang)}",
        "",
        f"| {t('column.id', lang)} | {t('column.requirement', lang)} | {t('qaagent.report.cases', lang)} | "
        f"{t('qaagent.report.result', lang)} | {t('qaagent.report.bugs', lang)} |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {_cell(row.requirement_id)} | {_cell(row.requirement_text or '—')} | {_cell(', '.join(row.case_ids) or '—')} | "
            f"{t(f'qaagent.coverage.{row.status.value}', lang)} | {_cell(', '.join(row.bug_ids) or '—')} |"
        )
    lines += [
        "",
        f"## {t('qaagent.report.results', lang)}",
        "",
        f"| {t('qaagent.report.case', lang)} | {t('column.id', lang)} | {t('qaagent.report.case_title', lang)} | "
        f"{t('qaagent.report.result', lang)} | {t('qaagent.report.reason', lang)} | {t('qaagent.report.evidence', lang)} |",
        "|---|---|---|---|---|---|",
    ]
    for result in run.results:
        reason = reason_text(result.reason, result.reason_params, lang) if result.reason else ""
        if result.screenshot == SCREENSHOT_WITHHELD:
            evidence = t("qaagent.report.screenshot_withheld", lang)
        else:
            evidence = f"screenshots/{result.screenshot}" if result.screenshot else "—"
        lines.append(
            f"| {_cell(result.case_id)} | {_cell(result.requirement_id)} | {_cell(result.title)} | "
            f"{t(f'qaagent.status.{result.status.value}', lang)} | {_cell(reason or '—')} | {evidence} |"
        )
    lines += ["", f"## {t('qaagent.report.bug_reports', lang)}", ""]
    lines += [bug_markdown(bug) for bug in run.bugs] or [t("qaagent.report.no_bugs", lang), ""]
    return "\n".join(lines) + "\n"


def reason_text(code: str, params: dict[str, str], lang: str) -> str:
    if code == "url":
        return t(f"automation.reason.url_{params.get('code', 'invalid')}", lang, host=params.get("host", ""))
    try:
        return t(f"qaagent.reason.{code}", lang, **params)
    except (KeyError, IndexError, ValueError):
        return t(f"qaagent.reason.{code}", lang)


def results_csv(run: QARun) -> str:
    headers = ["Run", "Case", "Requirement", "Test case", "Title", "Status", "Reason", "Error", "Actual",
               "Final URL", "Screenshot", "Duration ms"]
    rows = [
        [run.id, r.case_id, r.requirement_id, r.test_case_id, r.title, r.status.value, r.reason, r.error,
         r.actual_result, r.final_url, r.screenshot, r.duration_ms]
        for r in run.results
    ]
    return _to_csv(headers, rows)


def bugs_csv(run: QARun) -> str:
    headers = ["ID", "Summary", "Severity", "Requirement", "Test case", "Steps to reproduce", "Expected", "Actual",
               "Error", "Evidence", "Environment"]
    rows = [
        [b.id, b.title, b.severity.value, b.requirement_id, b.test_case_id,
         "\n".join(f"{i}. {s}" for i, s in enumerate(b.steps_to_reproduce, start=1)), b.expected, b.actual,
         b.error, "\n".join(b.evidence), "\n".join(f"{k}: {v}" for k, v in b.environment.items())]
        for b in run.bugs
    ]
    return _to_csv(headers, rows)


def bundle(run: QARun, run_dir: Path, requirements: list[Requirement] | None = None, lang: str = "en") -> bytes:
    """ZIP: report.md, run.json, results.csv, bugs.csv, coverage.json and the screenshots."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.md", markdown_report(run, requirements, lang))
        archive.writestr("run.json", run.model_dump_json(indent=2))
        archive.writestr("results.csv", results_csv(run))
        archive.writestr("bugs.csv", bugs_csv(run))
        archive.writestr("coverage.json", json.dumps(
            [row.model_dump(mode="json") for row in coverage(run, requirements)], indent=2, ensure_ascii=False))
        base = run_dir.resolve()
        for result in run.results:
            if not result.screenshot:
                continue
            path = (base / result.screenshot).resolve()
            if path.parent == base and path.is_file() and path.stat().st_size <= MAX_BUNDLE_FILE:
                archive.write(path, f"screenshots/{result.screenshot}")
    return buffer.getvalue()
