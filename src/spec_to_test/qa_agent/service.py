"""Starting a QA run: checks, execution and saving, in one place for the page and the CLI.

A run starts only when
1. the person confirmed they are authorized to test the target and approved the run,
2. the operator configured an allowlist (AUTOMATION_ALLOWED_HOSTS) and the URL passes
   the SSRF checks (`build_egress_policy`),
3. at least one case is approved, and
4. no other run is using the browser in this server process.

The browser works in its own thread (Playwright's sync API must not share a
thread with an event loop); the caller's thread receives progress through
`on_progress`, so it can safely update the page.
"""

import queue
import socket
import threading
from collections.abc import Callable

from spec_to_test.automation.security import Resolver, UrlRejected, build_egress_policy
from spec_to_test.qa_agent.bugs import generate_bugs
from spec_to_test.qa_agent.executor import Executor, now
from spec_to_test.qa_agent.models import CaseResult, PlanCase, QARun, RunStatus
from spec_to_test.qa_agent.safety import RUN_SLOT, QASettings
from spec_to_test.qa_agent.store import RunStore, new_run_id

Progress = Callable[[int, int, CaseResult], None]


class QAError(Exception):
    """A run that may not start. `code` maps to qaagent.error.<code>."""

    def __init__(self, code: str, params: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.params = params or {}


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def check_target(url: str, settings: QASettings, resolver: Resolver = socket.getaddrinfo) -> None:
    """Raise QAError when the URL may not be tested (allowlist, SSRF checks)."""
    if not settings.enabled:
        raise QAError("disabled")
    try:
        build_egress_policy(url, settings.automation, resolver)
    except UrlRejected as rejected:
        raise QAError("url", {"code": rejected.code, **rejected.params}) from None


def run_cases(
    cases: list[PlanCase],
    target_url: str,
    settings: QASettings,
    store: RunStore,
    *,
    authorized: bool,
    allow_destructive: bool = False,
    document_hash: str = "",
    document_title: str = "",
    parent_run_id: str = "",
    on_progress: Progress | None = None,
    resolver: Resolver = socket.getaddrinfo,
) -> QARun:
    if not authorized:
        raise QAError("not_authorized")
    if not settings.enabled:
        raise QAError("disabled")
    if not playwright_available():
        raise QAError("playwright_missing")
    try:
        policy = build_egress_policy(target_url, settings.automation, resolver)
    except UrlRejected as rejected:
        raise QAError("url", {"code": rejected.code, **rejected.params}) from None
    if not any(case.is_approved for case in cases):
        raise QAError("nothing_approved")
    if not RUN_SLOT.acquire(blocking=False):
        raise QAError("busy")
    run = QARun(
        id=new_run_id(),
        document_hash=document_hash,
        document_title=document_title,
        target_url=policy.base_url,
        created_at=now(),
        authorized=True,
        allow_destructive=allow_destructive,
        parent_run_id=parent_run_id,
        limits=settings.limits.model_dump(),
        cases=[case.model_copy(deep=True) for case in cases],
    )
    events: queue.Queue[CaseResult | None] = queue.Queue()
    outcome: dict[str, BaseException] = {}

    def save_progress(current: QARun, result: CaseResult) -> None:
        store.save(current)
        events.put(result)

    def work() -> None:
        # The worker finishes the run (bug reports, saving, freeing the slot) even when
        # the caller stops listening, e.g. because the person left the page mid-run.
        try:
            store.save(run)
            executor = Executor(settings, policy, store.run_dir(run.id), allow_destructive=allow_destructive)
            executor.run(run, on_case=save_progress)
            run.bugs = generate_bugs(run)
            store.save(run)
            store.prune(settings.limits.max_runs_kept)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            outcome["error"] = exc
        finally:
            RUN_SLOT.release()
            events.put(None)

    try:
        worker = threading.Thread(target=work, name=f"qa-run-{run.id}", daemon=True)
        worker.start()
    except BaseException:
        RUN_SLOT.release()
        raise
    done = 0
    while (event := events.get()) is not None:
        done += 1
        if on_progress:
            on_progress(done, len(run.cases), event)
    worker.join()
    if "error" in outcome:
        raise outcome["error"]
    return run


RETEST_STATUSES = (RunStatus.FAILED, RunStatus.BLOCKED)


def retest_cases(run: QARun, current: list[PlanCase]) -> list[PlanCase]:
    """The failed and blocked cases of `run`, as they are in the plan now (approval included).

    Retesting uses today's version of each case, so a fix to the steps is
    picked up; a case deleted from the plan is retested as it was, but only
    if its approval still matches its content.
    """
    by_id = {c.id: c for c in current}
    cases = []
    for result in run.results:
        if result.status in RETEST_STATUSES and (case := by_id.get(result.case_id) or run.case(result.case_id)):
            cases.append(case)
    return cases
