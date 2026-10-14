"""Autonomous QA: URL → discovery → draft requirements → test plan → approval → run → bugs → report.

What happens without asking (all read-only):
- discovery of the authorized site (qa_agent.discovery),
- drafting requirements from the evidence (qa_agent.inference) and test cases
  for them (qa_agent.autoplan).

What needs a person:
- confirming they may test the host, before discovery and again before every run;
- approving requirements (observed, inferred or unknown alike), and the test
  plan; cases that submit forms need their own approval and a run-level
  permission; destructive actions are never automated here;
- answering questions where the expected behaviour is unknown.

Runs use the existing QA Agent service (allowlist, SSRF checks, egress
policy, secrets, one browser at a time) with `allow_destructive=False`.
Sessions are saved after every page and every step, so an interrupted
discovery or run can be resumed.
"""

import queue
import socket
import threading
from collections.abc import Callable

from spec_to_test.automation.security import Resolver, UrlRejected, build_egress_policy
from spec_to_test.qa_agent import service
from spec_to_test.qa_agent.auto_models import AutoSession, DiscoveryState, PageInfo
from spec_to_test.qa_agent.autoplan import generate_cases
from spec_to_test.qa_agent.discovery import Discoverer
from spec_to_test.qa_agent.executor import now
from spec_to_test.qa_agent.inference import draft_requirements
from spec_to_test.qa_agent.models import CaseResult, PlanCase, QARun, RunState, RunStatus
from spec_to_test.qa_agent.safety import RUN_SLOT, QASettings
from spec_to_test.qa_agent.service import QAError
from spec_to_test.qa_agent.store import RunStore, new_run_id
from spec_to_test.qa_agent.triage import refine_bugs

PageProgress = Callable[[int, int, PageInfo], None]
# Sessions whose discovery is running in this process (see `effective_state`).
ACTIVE_DISCOVERIES: set[str] = set()


def new_session(url: str, settings: QASettings, lang: str, *, authorized: bool,
                resolver: Resolver = socket.getaddrinfo) -> AutoSession:
    """A session for an authorized, allowed URL. Raises QAError otherwise."""
    if not authorized:
        raise QAError("not_authorized")
    if not settings.enabled:
        raise QAError("disabled")
    try:
        policy = build_egress_policy(url.strip(), settings.automation, resolver)
    except UrlRejected as rejected:
        raise service.url_error(url, rejected) from None
    stamp = now()
    return AutoSession(id=new_run_id(), target_url=policy.base_url, lang=lang, created_at=stamp, updated_at=stamp,
                       authorized=True, limits=settings.limits.model_dump())


def effective_state(session: AutoSession) -> DiscoveryState:
    """A discovery saved as running whose worker is gone was interrupted (e.g. a restart)."""
    if session.state == DiscoveryState.RUNNING and session.id not in ACTIVE_DISCOVERIES:
        return DiscoveryState.INTERRUPTED
    return session.state


def discover(
    session: AutoSession,
    settings: QASettings,
    store: RunStore,
    lang: str,
    *,
    authorized: bool,
    on_page: PageProgress | None = None,
    resolver: Resolver = socket.getaddrinfo,
) -> AutoSession:
    """Run (or resume) discovery, then draft requirements and cases. Blocks until done.

    The browser works in its own thread; `on_page` is called in the caller's thread.
    """
    if not authorized:
        raise QAError("not_authorized")
    if not settings.enabled:
        raise QAError("disabled")
    if not service.playwright_available():
        raise QAError("playwright_missing")
    try:
        policy = build_egress_policy(session.target_url, settings.automation, resolver)
    except UrlRejected as rejected:
        raise service.url_error(session.target_url, rejected) from None
    if not RUN_SLOT.acquire(blocking=False):
        raise QAError("busy")
    events: queue.Queue[PageInfo | None] = queue.Queue()
    outcome: dict[str, BaseException] = {}

    def saved(current: AutoSession, page: PageInfo) -> None:
        current.updated_at = now()
        store.save_session(current)
        events.put(page)

    def work() -> None:
        ACTIVE_DISCOVERIES.add(session.id)
        try:
            session.limits = settings.limits.model_dump()
            Discoverer(settings, policy).run(session, on_page=saved)
            draft_requirements(session, lang)
            generate_cases(session, lang)
            session.updated_at = now()
            store.save_session(session)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            outcome["error"] = exc
        finally:
            ACTIVE_DISCOVERIES.discard(session.id)
            RUN_SLOT.release()
            events.put(None)

    try:
        worker = threading.Thread(target=work, name=f"qa-discovery-{session.id}", daemon=True)
        worker.start()
    except BaseException:
        RUN_SLOT.release()
        raise
    done = 0
    while (page := events.get()) is not None:
        done += 1
        if on_page:
            on_page(done, done + len(session.queue), page)
    worker.join()
    if "error" in outcome:
        raise outcome["error"]
    return session


def execute(
    session: AutoSession,
    cases: list[PlanCase],
    settings: QASettings,
    store: RunStore,
    *,
    authorized: bool,
    allow_forms: bool,
    document_title: str = "",
    parent_run_id: str = "",
    on_progress: service.Progress | None = None,
    resolver: Resolver = socket.getaddrinfo,
) -> QARun:
    """Run the session's approved plan cases. Destructive actions are never allowed here."""
    run = service.run_cases(
        cases, session.target_url, settings, store, authorized=authorized, allow_destructive=False,
        allow_forms=allow_forms, document_hash=session.document_hash, document_title=document_title,
        parent_run_id=parent_run_id, on_progress=on_progress, resolver=resolver,
        on_finish=lambda finished: refine_bugs(finished, session),
    )
    session.run_ids.append(run.id)
    session.updated_at = now()
    store.save_session(session)
    return run


def session_runs(session: AutoSession, store: RunStore) -> list[QARun]:
    """The session's runs, newest first."""
    runs = [run for run in (store.load(run_id) for run_id in session.run_ids) if run is not None]
    return sorted(runs, key=lambda r: (r.created_at, r.id), reverse=True)


def interrupted(run: QARun) -> bool:
    """Saved as running but no worker is executing it, or aborted part-way."""
    return (run.state == RunState.RUNNING and run.id not in service.ACTIVE_RUNS) or run.state == RunState.ABORTED


def unfinished_cases(run: QARun, current: list[PlanCase]) -> list[PlanCase]:
    """Cases of an interrupted run that have no result (or were not run because it stopped)."""
    done = {r.case_id for r in run.results if not (r.status == RunStatus.NOT_RUN and r.reason == "aborted")}
    by_id = {c.id: c for c in current}
    return [by_id.get(c.id, c) for c in run.cases if c.id not in done]


def mark_interrupted(run: QARun, store: RunStore) -> None:
    """Close a run the server stopped mid-way, keeping the results it saved."""
    if run.state == RunState.RUNNING and run.id not in service.ACTIVE_RUNS:
        run.state = RunState.ABORTED
        run.error = run.error or "interrupted"
        run.finished_at = run.finished_at or now()
        store.save(run)


def latest_results(run: QARun) -> dict[str, CaseResult]:
    return {r.case_id: r for r in run.results}
