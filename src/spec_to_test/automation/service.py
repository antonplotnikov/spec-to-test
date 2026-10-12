"""Background jobs for the Automation tab.

Jobs run in a small thread pool, so the Streamlit page never waits for a
browser or for Claude: it submits a job and re-reads its state. Each job
belongs to one owner (a random id per browser session, or "local" for a
single-user machine) and is invisible to everyone else. State is written to
<artifacts>/jobs/<id>/job.json after every change, so it survives reruns and
page reloads; after a server restart, jobs that were still running are marked
as interrupted instead of hanging forever.
"""

import re
import secrets
import socket
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from spec_to_test.ai_analysis import AIConfig
from spec_to_test.automation.browser import PlaywrightMCPBrowser
from spec_to_test.automation.claude import ClaudeAgent
from spec_to_test.automation.config import AutomationConfig
from spec_to_test.automation.models import ACTIVE_STATUSES, AutomationJob, JobEvent, JobStatus, utc_now
from spec_to_test.automation.orchestrator import Agent, BrowserFactory, JobContext, Orchestrator, Runner
from spec_to_test.automation.runner import PlaywrightRunner
from spec_to_test.automation.sandbox import prune_private_dirs
from spec_to_test.automation.store import (  # noqa: F401 - re-exported
    JOB_ID,
    LOCAL_OWNER,
    AutomationError,
    JobStore,
    new_owner_id,
)
from spec_to_test.models import AutomatedTest, Requirement, ReviewStatus, TestCase, Workspace
from spec_to_test.storage import persistence_enabled

SESSION_JOB_MAX_AGE = 24 * 3600  # temporary job folders ("session" mode) are pruned after a day


AgentFactory = Callable[[AIConfig], Agent]


def claude_agent(config: AIConfig) -> Agent:
    return ClaudeAgent(config)


class AutomationService:
    def __init__(
        self,
        config: AutomationConfig,
        agent_factory: AgentFactory = claude_agent,
        browser_factory: BrowserFactory = PlaywrightMCPBrowser,
        runner_factory: Callable[[AutomationConfig], Runner] = PlaywrightRunner,
        resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
        check_prerequisites: bool = True,
    ) -> None:
        self.agent_factory = agent_factory
        self.browser_factory = browser_factory
        self.runner_factory = runner_factory
        self.resolver = resolver
        self.check_prerequisites = check_prerequisites
        self._lock = threading.RLock()
        self._running: dict[str, tuple[Future[Any], threading.Event]] = {}
        self._cache: dict[str, AutomationJob] = {}
        self.config = config
        self.store = JobStore(config.artifacts_dir)
        self._executor = ThreadPoolExecutor(max_workers=config.max_jobs, thread_name_prefix="automation")
        # Leftovers of jobs killed with an earlier server (no job lives longer than this).
        prune_private_dirs(2 * config.job_timeout + 600)

    def configure(self, config: AutomationConfig) -> None:
        """Apply current settings. New jobs use them; running jobs keep their own."""
        with self._lock:
            if self.config.max_jobs != config.max_jobs:
                old = self._executor
                self._executor = ThreadPoolExecutor(max_workers=config.max_jobs, thread_name_prefix="automation")
                old.shutdown(wait=False)
            self.config = config
            self.store = JobStore(config.artifacts_dir)

    # --- queries ----------------------------------------------------------

    def jobs(self, owner: str) -> list[AutomationJob]:
        with self._lock:
            found = {job.id: job for job in self.store.all() if job.owner == owner}
            found.update({job_id: job for job_id, job in self._cache.items() if job.owner == owner})
            for job_id, job in list(found.items()):
                if job.status in ACTIVE_STATUSES and job_id not in self._running:
                    found[job_id] = self._interrupted(job)
        return sorted(found.values(), key=lambda j: j.created_at, reverse=True)

    def job(self, owner: str, job_id: str) -> AutomationJob | None:
        with self._lock:
            job = self._cache.get(job_id) or (self.store.load(job_id) if JOB_ID.match(job_id) else None)
            if job is None or job.owner != owner:
                return None
            if job.status in ACTIVE_STATUSES and job_id not in self._running:
                job = self._interrupted(job)
            return job.model_copy(deep=True)

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._running

    def _interrupted(self, job: AutomationJob) -> AutomationJob:
        job = job.model_copy(deep=True)
        job.status = JobStatus.BLOCKED
        job.reason = "interrupted"
        job.finished_at = job.finished_at or utc_now()
        job.events.append(JobEvent(status=job.status, code="interrupted"))
        self._save(job)
        return job

    def _save(self, job: AutomationJob) -> None:
        with self._lock:
            self._cache[job.id] = job.model_copy(deep=True)
        try:
            self.store.save(job)
        except (OSError, ValueError):
            pass  # the in-memory copy still drives the page

    # --- commands ---------------------------------------------------------

    def submit(
        self,
        owner: str,
        test_case: TestCase,
        requirement: Requirement | None,
        target_url: str,
        ai_config: AIConfig | None,
        consent: bool,
        allow_destructive: bool = False,
    ) -> AutomationJob:
        if not consent:
            raise AutomationError("consent_required")
        if ai_config is None:
            raise AutomationError("ai_not_configured")
        if not self.config.enabled:
            raise AutomationError("not_configured")
        if test_case.review_status != ReviewStatus.APPROVED:
            raise AutomationError("not_approved")
        with self._lock:
            if any(self._cache[job_id].owner == owner for job_id in self._running if job_id in self._cache):
                raise AutomationError("busy")
            if not persistence_enabled():
                self.store.prune(SESSION_JOB_MAX_AGE, keep=set(self._running))
            job = AutomationJob(
                id=secrets.token_hex(8),
                owner=owner,
                test_case_id=test_case.id,
                requirement_id=test_case.requirement_id,
                target_url=target_url.strip(),
                model=ai_config.model,
                allow_destructive=allow_destructive,
            )
            job.events.append(JobEvent(status=JobStatus.QUEUED, code="queued"))
            job_dir = self.store.job_dir(job.id)
            job_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._save(job)
            cancel = threading.Event()
            context = JobContext(
                job=job.model_copy(deep=True),
                test_case=test_case.model_copy(deep=True),
                requirement=requirement.model_copy(deep=True) if requirement else None,
                config=self.config.model_copy(deep=True),
                job_dir=job_dir,
                save=self._save,
                cancel=cancel,
                api_key=ai_config.api_key.get_secret_value(),
            )
            future = self._executor.submit(self._work, context, ai_config)
            self._running[job.id] = (future, cancel)
        return job.model_copy(deep=True)

    def _work(self, context: JobContext, ai_config: AIConfig) -> None:
        try:
            if context.cancel.is_set():  # cancelled while still queued
                context.job.status = JobStatus.CANCELLED
                context.job.reason = "cancelled"
                context.job.finished_at = utc_now()
                context.job.events.append(JobEvent(status=JobStatus.CANCELLED, code="cancelled"))
                self._save(context.job)
                return
            orchestrator = Orchestrator(
                agent=self.agent_factory(ai_config),
                browser_factory=self.browser_factory,
                runner=self.runner_factory(context.config),
                resolver=self.resolver,
                check_prerequisites=self.check_prerequisites,
            )
            orchestrator.run(context)
        finally:
            with self._lock:
                self._running.pop(context.job.id, None)

    def cancel(self, owner: str, job_id: str) -> bool:
        with self._lock:
            job = self._cache.get(job_id)
            entry = self._running.get(job_id)
            if job is None or entry is None or job.owner != owner:
                return False
            entry[1].set()
            return True

    def wait(self, job_id: str, timeout: float | None = None) -> None:
        """Block until a job finishes (tests and scripts; the page never waits)."""
        with self._lock:
            entry = self._running.get(job_id)
        if entry is not None:
            entry[0].result(timeout=timeout)

    def approve(self, owner: str, job_id: str, workspace: Workspace) -> AutomatedTest:
        """Record a passed job as an approved automated test in the workspace."""
        job = self.job(owner, job_id)
        if job is None:
            raise AutomationError("job_missing")
        if job.status != JobStatus.PASSED or not job.code or job.last_run is None or not job.last_run.passed:
            raise AutomationError("not_passed")
        test_case = next((tc for tc in workspace.test_cases if tc.id == job.test_case_id), None)
        if test_case is None or test_case.review_status != ReviewStatus.APPROVED:
            raise AutomationError("not_approved")
        existing = next((a for a in workspace.automated_tests if a.test_case_id == job.test_case_id), None)
        record = AutomatedTest(
            id=existing.id if existing else next_automated_test_id(workspace.automated_tests),
            test_case_id=job.test_case_id,
            requirement_id=test_case.requirement_id,
            job_id=job.id,
            file_name=Path(job.spec_file).name,
            code=job.code,
            target_url=job.target_url,
            model=job.model,
            validated_at=job.finished_at,
            approved_at=utc_now(),
            duration_ms=job.last_run.duration_ms,
        )
        workspace.automated_tests = [a for a in workspace.automated_tests if a.test_case_id != job.test_case_id]
        workspace.automated_tests.append(record)
        job.approved = True
        self._save(job)
        return record


def next_automated_test_id(tests: list[AutomatedTest]) -> str:
    numbers = [int(m.group(1)) for a in tests if (m := re.fullmatch(r"AT-(\d+)", a.id))]
    return f"AT-{max(numbers, default=0) + 1:03d}"


_SERVICE: AutomationService | None = None
_SERVICE_LOCK = threading.Lock()


def get_service(config: AutomationConfig) -> AutomationService:
    """The process-wide service (jobs must outlive a single page run)."""
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = AutomationService(config)
        else:
            _SERVICE.configure(config)
        return _SERVICE


def set_service(service: AutomationService | None) -> None:
    """Replace the process-wide service (tests)."""
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = service

