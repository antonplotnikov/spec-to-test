"""Limits and safety checks of the QA Agent.

Which hosts may be tested comes from the same operator settings as the
Automation tab (AUTOMATION_ALLOWED_HOSTS, AUTOMATION_ALLOW_PRIVATE_NETWORK,
AUTOMATION_SECRET_<NAME>; see spec_to_test.automation.config), read from the
process environment only. Each URL is validated and its host pinned by
`build_egress_policy` (SSRF protection). On top of that the QA Agent reads:

QA_MAX_CASES          cases per run (default 25, 1-200)
QA_MAX_STEPS          steps per case (default 40, 1-200)
QA_STEP_TIMEOUT_MS    one action or check (default 10000, 1000-60000)
QA_NAV_TIMEOUT_MS     one page load (default 20000, 2000-120000)
QA_RUN_TIMEOUT        seconds for a whole run (default 600, 30-3600)
QA_MAX_RUNS_KEPT      saved runs per project before the oldest are removed (default 50)

Autonomous QA discovery (read-only crawling of the target site):

QA_DISCOVERY_MAX_PAGES     pages opened per discovery (default 15, 1-100)
QA_DISCOVERY_MAX_DEPTH     link depth from the start page (default 2, 0-5)
QA_DISCOVERY_TIMEOUT       seconds for a whole discovery (default 180, 20-1800)
QA_DISCOVERY_MAX_ELEMENTS  links, fields or headings read per page (default 150, 10-1000)

`preflight` decides, without a browser, whether a case may run at all.
"""

import os
import threading
from dataclasses import dataclass, field

from pydantic import BaseModel

from spec_to_test.automation.config import AutomationConfig, load_automation_config
from spec_to_test.automation.security import EgressPolicy, Redactor, UrlRejected, check_navigation, destructive_term
from spec_to_test.qa_agent.models import PlanCase, RunStatus, StepAction
from spec_to_test.qa_agent.steps import StepError, describe_locator, secret_name, validate_step


class QALimits(BaseModel):
    max_cases: int = 25
    max_steps: int = 40
    step_timeout_ms: int = 10_000
    nav_timeout_ms: int = 20_000
    run_timeout_s: int = 600
    max_runs_kept: int = 50
    discovery_max_pages: int = 15
    discovery_max_depth: int = 2
    discovery_timeout_s: int = 180
    discovery_max_elements: int = 150


def _int(env: dict[str, str], key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(env.get(key, "").strip() or default)
    except ValueError:
        return default
    return max(low, min(high, value))


def load_limits(environ: dict[str, str] | None = None) -> QALimits:
    env = dict(os.environ if environ is None else environ)
    return QALimits(
        max_cases=_int(env, "QA_MAX_CASES", 25, 1, 200),
        max_steps=_int(env, "QA_MAX_STEPS", 40, 1, 200),
        step_timeout_ms=_int(env, "QA_STEP_TIMEOUT_MS", 10_000, 1000, 60_000),
        nav_timeout_ms=_int(env, "QA_NAV_TIMEOUT_MS", 20_000, 2000, 120_000),
        run_timeout_s=_int(env, "QA_RUN_TIMEOUT", 600, 30, 3600),
        max_runs_kept=_int(env, "QA_MAX_RUNS_KEPT", 50, 1, 1000),
        discovery_max_pages=_int(env, "QA_DISCOVERY_MAX_PAGES", 15, 1, 100),
        discovery_max_depth=_int(env, "QA_DISCOVERY_MAX_DEPTH", 2, 0, 5),
        discovery_timeout_s=_int(env, "QA_DISCOVERY_TIMEOUT", 180, 20, 1800),
        discovery_max_elements=_int(env, "QA_DISCOVERY_MAX_ELEMENTS", 150, 10, 1000),
    )


@dataclass
class QASettings:
    automation: AutomationConfig
    limits: QALimits

    @property
    def enabled(self) -> bool:
        return self.automation.enabled

    def redactor(self) -> Redactor:
        return Redactor(self.automation.secret_values())


def load_qa_settings(environ: dict[str, str] | None = None) -> QASettings:
    return QASettings(load_automation_config(environ), load_limits(environ))


@dataclass
class Verdict:
    """Why a case may not run: a status and a qaagent.reason.<code> key suffix."""

    status: RunStatus
    reason: str
    params: dict[str, str] = field(default_factory=dict)


def destructive_in(case: PlanCase) -> str | None:
    """A destructive word in what the case would click, select, press or open."""
    for step in case.steps:
        if step.action in (StepAction.CLICK, StepAction.SELECT, StepAction.CHECK, StepAction.PRESS):
            texts = [describe_locator(step.target), step.value if step.action == StepAction.SELECT else ""]
        elif step.action == StepAction.GOTO:
            texts = [step.value.replace("/", " ").replace("-", " ").replace("_", " ")]
        else:
            continue
        for text in texts:
            if text and (term := destructive_term(text)):
                return term
    return None


def preflight(
    case: PlanCase, policy: EgressPolicy, secrets: dict[str, str], limits: QALimits, allow_destructive: bool,
    allow_forms: bool = False,
) -> Verdict | None:
    """None when the case may run; otherwise NOT RUN or BLOCKED with the reason."""
    if not case.steps:
        return Verdict(RunStatus.NOT_RUN, "no_steps")
    if not case.is_approved:
        return Verdict(RunStatus.NOT_RUN, "changed_after_approval" if case.approved else "not_approved")
    if not case.has_assertion:
        return Verdict(RunStatus.NOT_RUN, "no_assertion")
    if len(case.steps) > limits.max_steps:
        return Verdict(RunStatus.NOT_RUN, "too_many_steps", {"max": str(limits.max_steps)})
    for number, step in enumerate(case.steps, start=1):
        try:
            validate_step(step)
        except StepError as error:
            return Verdict(RunStatus.NOT_RUN, "invalid_step", {"step": str(number), "code": error.code})
        if step.action == StepAction.GOTO:
            try:
                check_navigation(step.value, policy)
            except UrlRejected as rejected:
                return Verdict(RunStatus.BLOCKED, "url", {"code": rejected.code, **rejected.params})
        if (name := secret_name(step.value)) and name not in secrets:
            return Verdict(RunStatus.BLOCKED, "secret_missing", {"name": name})
    if not allow_destructive and (term := destructive_in(case)):
        return Verdict(RunStatus.BLOCKED, "destructive", {"term": term})
    if case.risk and not allow_forms:
        return Verdict(RunStatus.BLOCKED, "risk", {"risk": case.risk})
    return None


# One browser run at a time per server process: runs are heavy and share the machine.
RUN_SLOT = threading.BoundedSemaphore(1)
