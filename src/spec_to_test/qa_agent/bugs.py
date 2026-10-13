"""Bug reports for failed cases, built only from what the run recorded.

Every field comes from the run: the steps that were executed (up to the one
that failed), the expected result written in the plan, the observed page
state and error, and the screenshot. Nothing is inferred. Severity starts at
High for server errors and Medium otherwise; people adjust it on the page.
"""

from spec_to_test.models import Severity
from spec_to_test.qa_agent.executor import SCREENSHOT_WITHHELD, now, step_label
from spec_to_test.qa_agent.models import BugReport, CaseResult, QARun, RunStatus


def bug_id(run: QARun, number: int) -> str:
    return f"BUG-{run.id[:6].upper()}-{number:02d}"


def bug_from_result(run: QARun, result: CaseResult, number: int) -> BugReport:
    failed = result.failed_step
    reproduced = [step_label(s.step) for s in result.steps]
    expected = result.expected_result.strip()
    if failed is not None and failed.step.is_assertion:
        check = step_label(failed.step)
        expected = f"{expected}\n{check}".strip() if expected else check
    short = step_label(failed.step) if failed is not None else result.reason
    if result.screenshot == SCREENSHOT_WITHHELD:
        evidence = ["screenshot: withheld (the page showed a secret value)"]
    else:
        evidence = [f"screenshot: {result.screenshot}"] if result.screenshot else []
    evidence += [f"console: {line}" for line in result.console_errors]
    environment = {"url": run.target_url, "browser": run.browser or "Chromium (headless)",
                   "viewport": "1280x800", "run": run.id, "executed_at": result.started_at}
    return BugReport(
        id=bug_id(run, number),
        run_id=run.id,
        case_id=result.case_id,
        requirement_id=result.requirement_id,
        test_case_id=result.test_case_id,
        title=f"[{result.requirement_id}] {result.title} — failed: {short}"[:300],
        severity=Severity.HIGH if result.reason == "http_status" else Severity.MEDIUM,
        steps_to_reproduce=reproduced,
        expected=expected,
        actual=result.actual_result,
        error=result.error,
        evidence=evidence,
        environment=environment,
        created_at=now(),
    )


def generate_bugs(run: QARun) -> list[BugReport]:
    """One report per FAILED case. BLOCKED and NOT RUN are not product bugs."""
    failed = [r for r in run.results if r.status == RunStatus.FAILED]
    return [bug_from_result(run, result, number) for number, result in enumerate(failed, start=1)]


def bug_markdown(bug: BugReport) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(bug.steps_to_reproduce, start=1))
    environment = "\n".join(f"- {k}: {v}" for k, v in bug.environment.items())
    evidence = "\n".join(f"- {e}" for e in bug.evidence) or "- (none)"
    links = f"Requirement: {bug.requirement_id}" + (f" · Test case: {bug.test_case_id}" if bug.test_case_id else "")
    fenced = bug.error.replace("```", "'''")  # keep the code block closed
    error = f"\n\n**Error**\n\n```\n{fenced}\n```" if bug.error else ""
    return (
        f"### {bug.id}: {bug.title}\n\n"
        f"Severity: {bug.severity.value} · {links} · Plan case: {bug.case_id}\n\n"
        f"**Steps to reproduce**\n\n{steps}\n\n"
        f"**Expected**\n\n{bug.expected or '—'}\n\n"
        f"**Actual**\n\n{bug.actual or '—'}{error}\n\n"
        f"**Evidence**\n\n{evidence}\n\n"
        f"**Environment**\n\n{environment}\n"
    )
