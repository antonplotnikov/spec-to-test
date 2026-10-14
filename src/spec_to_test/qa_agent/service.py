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

from spec_to_test.automation.security import Resolver, UrlRejected, _split, build_egress_policy
from spec_to_test.qa_agent.bugs import generate_bugs
from spec_to_test.qa_agent.executor import Executor, now
from spec_to_test.qa_agent.models import CaseResult, PlanCase, QARun, RunStatus
from spec_to_test.qa_agent.safety import RUN_SLOT, QASettings
from spec_to_test.qa_agent.store import RunStore, new_run_id

Progress = Callable[[int, int, CaseResult], None]
# Runs whose worker is alive in this process; a saved run still "running" that is not
# here was interrupted (the server stopped) and can be resumed.
ACTIVE_RUNS: set[str] = set()


class QAError(Exception):
    """A run that may not start. `code` maps to qaagent.error.<code>."""

    def __init__(self, code: str, params: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.params = params or {}


def url_error(url: str, rejected: UrlRejected) -> QAError:
    """The QAError for a rejected URL. A host that is simply not allowed also gets the exact
    AUTOMATION_ALLOWED_HOSTS entry the operator would have to add (it is only shown, never applied)."""
    params = {"code": rejected.code, **rejected.params}
    if rejected.code == "not_allowed":
        try:
            scheme, host, port = _split(url.strip())
        except UrlRejected:
            pass
        else:
            params["port"] = str(port)
            params["entry"] = host if port == (443 if scheme == "https" else 80) else f"{host}:{port}"
    return QAError("url", params)


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
        raise url_error(url, rejected) from None


def run_cases(
    cases: list[PlanCase],
    target_url: str,
    settings: QASettings,
    store: RunStore,
    *,
    authorized: bool,
    allow_destructive: bool = False,
    allow_forms: bool = False,
    document_hash: str = "",
    document_title: str = "",
    parent_run_id: str = "",
    on_progress: Progress | None = None,
    resolver: Resolver = socket.getaddrinfo,
    on_finish: Callable[[QARun], None] | None = None,
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
        raise url_error(target_url, rejected) from None
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
        allow_forms=allow_forms,
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
        ACTIVE_RUNS.add(run.id)
        try:
            store.save(run)
            executor = Executor(settings, policy, store.run_dir(run.id), allow_destructive=allow_destructive,
                                allow_forms=allow_forms)
            executor.run(run, on_case=save_progress)
            run.bugs = generate_bugs(run)
            if on_finish:  # e.g. Autonomous QA classifies the results and refines the bug reports
                on_finish(run)
            store.save(run)
            store.prune(settings.limits.max_runs_kept)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            outcome["error"] = exc
        finally:
            ACTIVE_RUNS.discard(run.id)
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
