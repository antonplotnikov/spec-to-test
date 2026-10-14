"""What a result means, for Autonomous QA runs.

A FAILED or BLOCKED status alone does not say whether the product is wrong.
`classify` separates, from the recorded reason and the requirement's basis:

defect                 a check did not hold (or the server answered 5xx) and the
                       expectation is observed or was stated by the reviewer;
uncertain_expectation  a check did not hold, but the expectation was only
                       inferred and nobody confirmed it;
timeout                an element did not appear in time or the run ran out of time;
environment            the browser could not start or the page could not load;
security_block         a safety rule stopped the case (allowed hosts, redirect,
                       destructive action, form submissions not allowed, secret missing);
not_run / passed       as recorded.

`refine_bugs` keeps bug reports only for defects and uncertain expectations
(uncertain ones at Low severity, labelled), and adds the website evidence
behind the requirement. No root cause is stated: a report says what was
expected, what the page showed and where the expectation came from.
"""

from enum import StrEnum

from spec_to_test.models import Severity
from spec_to_test.qa_agent.auto_models import AutoSession, DraftRequirement
from spec_to_test.qa_agent.models import CaseResult, QARun, RunStatus

SECURITY_REASONS = frozenset({"url", "redirect", "destructive", "risk", "secret_missing"})
TIMEOUT_REASONS = frozenset({"run_timeout"})


class Outcome(StrEnum):
    PASSED = "passed"
    DEFECT = "defect"
    UNCERTAIN = "uncertain_expectation"
    TIMEOUT = "timeout"
    ENVIRONMENT = "environment"
    SECURITY_BLOCK = "security_block"
    NOT_RUN = "not_run"


def classify(result: CaseResult, requirement: DraftRequirement | None) -> Outcome:
    if result.status == RunStatus.PASSED:
        return Outcome.PASSED
    if result.status == RunStatus.NOT_RUN:
        return Outcome.NOT_RUN
    if result.status == RunStatus.BLOCKED:
        if result.reason in SECURITY_REASONS:
            return Outcome.SECURITY_BLOCK
        if result.reason in TIMEOUT_REASONS:
            return Outcome.TIMEOUT
        return Outcome.ENVIRONMENT
    # FAILED
    if result.reason == "http_status":
        return Outcome.DEFECT
    if result.reason == "action_error":
        error = result.error.casefold()
        if "timeout" in error:
            return Outcome.TIMEOUT
        return Outcome.ENVIRONMENT
    if requirement is not None and not requirement.confirmed:
        return Outcome.UNCERTAIN
    return Outcome.DEFECT


def outcomes(run: QARun, session: AutoSession) -> dict[str, Outcome]:
    """Outcome per plan case id of the run."""
    return {r.case_id: classify(r, session.requirement(r.requirement_id)) for r in run.results}


def refine_bugs(run: QARun, session: AutoSession) -> None:
    """Keep the bug reports that the evidence supports, and add where each expectation came from."""
    found = outcomes(run, session)
    kept = []
    for bug in run.bugs:
        outcome = found.get(bug.case_id)
        if outcome not in (Outcome.DEFECT, Outcome.UNCERTAIN):
            continue
        bug.classification = outcome.value
        req = session.requirement(bug.requirement_id)
        if req is not None:
            bug.environment["requirement_basis"] = req.basis.value
            bug.environment["requirement_confidence"] = f"{req.confidence}%"
            for evidence_id in req.evidence_ids[:6]:
                if (item := session.evidence_item(evidence_id)) is not None:
                    text = f": {item.text}" if item.text else ""
                    bug.evidence.append(f"website {item.id} ({item.kind.value}) {item.url}{text}"[:400])
            if req.answer:
                bug.evidence.append(f"expected behaviour stated by the reviewer: {req.answer}"[:400])
                bug.expected = f"{bug.expected}\nStated by the reviewer: {req.answer}".strip()
        if outcome == Outcome.UNCERTAIN:
            bug.severity = Severity.LOW
            bug.title = f"[Needs confirmation] {bug.title}"[:300]
        kept.append(bug)
    run.bugs = kept
