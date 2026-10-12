"""Data models for the Automation tab: jobs, AI test scripts and run results.

A job turns one Approved test case into a validated Playwright test:
queued -> planning -> exploring -> generating -> validating -> passed/failed,
or blocked/cancelled at any point. Everything shown to the user is stored on
the job, so a page reload (or another browser tab of the same session) sees
exactly what the background worker produced.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class JobStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    EXPLORING = "exploring"
    GENERATING = "generating"
    VALIDATING = "validating"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATUSES


TERMINAL_STATUSES = frozenset({JobStatus.PASSED, JobStatus.FAILED, JobStatus.BLOCKED, JobStatus.CANCELLED})
ACTIVE_STATUSES = frozenset(set(JobStatus) - TERMINAL_STATUSES)


# ---------------------------------------------------------------------------
# The test script Claude submits (rendered to TypeScript by generator.py)
# ---------------------------------------------------------------------------

ActionType = Literal[
    "goto", "click", "fill", "select", "check", "uncheck", "press", "hover",
    "expect_visible", "expect_hidden", "expect_text", "expect_value", "expect_url",
    "expect_title", "expect_enabled", "expect_disabled", "expect_checked",
]
LocatorStrategy = Literal["role", "label", "testid", "placeholder", "text", "page"]

ASSERTION_ACTIONS = frozenset(
    {
        "expect_visible", "expect_hidden", "expect_text", "expect_value", "expect_url",
        "expect_title", "expect_enabled", "expect_disabled", "expect_checked",
    }
)
# Actions that work on the page rather than on an element.
PAGE_ACTIONS = frozenset({"goto", "press", "expect_url", "expect_title"})
# Assertions whose expected value must be written in the approved text.
TEXT_ASSERTIONS = frozenset({"expect_text", "expect_value", "expect_title"})


class ScriptStep(BaseModel):
    """One action or assertion. Unused fields are empty strings (strict tool schema)."""

    action: ActionType
    strategy: LocatorStrategy = "page"
    # ARIA role for strategy "role" (e.g. "button"); empty otherwise.
    role: str = ""
    # Accessible name, label text, test id, placeholder or visible text.
    target: str = ""
    exact: bool = False
    # Text to fill, option to select, key to press, path to open, or expected text/URL part.
    value: str = ""
    # Name of a configured secret to fill instead of `value` (never the secret itself).
    secret: str = ""
    # 1-based number of the test case step this implements; 0 = setup, -1 = expected result.
    tc_step: int = 0
    # Assertions only: verbatim quote from the approved expected result or requirement.
    evidence: str = ""

    @property
    def is_assertion(self) -> bool:
        return self.action in ASSERTION_ACTIONS

    def assertion_key(self) -> tuple[str, str, str]:
        """What an assertion checks. A repair may not change it."""
        return (self.action, " ".join(self.value.split()), " ".join(self.evidence.split()))


class TestScript(BaseModel):
    __test__ = False  # not a pytest class

    title: str = Field(min_length=1)
    steps: list[ScriptStep] = Field(min_length=1)
    # Anything the QA reviewer should know (observed differences, unclear steps).
    notes: str = ""


class AssertionCheck(BaseModel):
    """How an assertion traces back to the approved text, shown to the reviewer."""

    step_index: int
    action: str
    value: str
    evidence: str
    # "verified": quote and expected value found in the approved text;
    # "interpreted": quote found, but the value (e.g. a URL) is the model's reading of it.
    status: Literal["verified", "interpreted"]
    source: Literal["expected_result", "requirement"]


# ---------------------------------------------------------------------------
# Run results
# ---------------------------------------------------------------------------

class Artifact(BaseModel):
    kind: Literal["spec", "config", "report", "trace", "screenshot", "log", "bundle"]
    # Path relative to the job directory.
    path: str
    size: int = 0


class TestOutcome(BaseModel):
    __test__ = False

    title: str
    status: str  # Playwright: passed / failed / timedOut / skipped / interrupted
    duration_ms: int = 0
    error: str = ""
    error_location: str = ""


class RunResult(BaseModel):
    """Parsed Playwright JSON report of one validation run."""

    exit_code: int | None = None
    passed: bool = False
    timed_out: bool = False
    tests: list[TestOutcome] = Field(default_factory=list)
    duration_ms: int = 0
    # Report-level errors (syntax errors, config errors, crashes).
    errors: list[str] = Field(default_factory=list)
    log_tail: str = ""

    def failure_summary(self) -> str:
        parts = [f"{t.title}: {t.status}\n{t.error}".strip() for t in self.tests if t.status != "passed"]
        parts += self.errors
        if self.timed_out:
            parts.append("The run exceeded its time limit and was stopped.")
        if not parts and not self.passed:
            parts.append(self.log_tail or "The run did not produce a report.")
        return "\n\n".join(parts)


class JobEvent(BaseModel):
    at: str = Field(default_factory=utc_now)
    status: JobStatus
    # Translation key (automation.event.<code>) plus parameters; never raw page content.
    code: str
    params: dict[str, str] = Field(default_factory=dict)


class AutomationJob(BaseModel):
    id: str
    owner: str
    test_case_id: str
    requirement_id: str
    target_url: str
    model: str = ""
    allow_destructive: bool = False
    status: JobStatus = JobStatus.QUEUED
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    finished_at: str = ""
    events: list[JobEvent] = Field(default_factory=list)
    # Why the job ended blocked/failed: an automation.reason.<code> key plus params.
    reason: str = ""
    reason_params: dict[str, str] = Field(default_factory=dict)
    script: TestScript | None = None
    assertion_checks: list[AssertionCheck] = Field(default_factory=list)
    code: str = ""
    spec_file: str = ""
    runs: list[RunResult] = Field(default_factory=list)
    repair_attempted: bool = False
    artifacts: list[Artifact] = Field(default_factory=list)
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    approved: bool = False

    @property
    def last_run(self) -> RunResult | None:
        return self.runs[-1] if self.runs else None
