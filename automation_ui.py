"""Automation tab: Approved test case -> validated Playwright test.

Rendering only. Jobs run in the background (`spec_to_test.automation.service`),
so this page never waits for the browser or the model: it submits a job and
re-reads its state; while a job is active a fragment refreshes it every two
seconds. Jobs belong to this browser session (or to "local" on a single-user
machine) and nobody else can see or cancel them.

AI is opt-in per run: the consent box resets after every request. A test can
be approved only after a real run passed; approved tests are stored in the
workspace (`Workspace.automated_tests`) through the page's `persist`.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import streamlit as st

from spec_to_test.ai_analysis import AIConfig
from spec_to_test.automation.config import AutomationConfig, load_automation_config, missing_prerequisites
from spec_to_test.automation.export import approved_bundle, job_bundle
from spec_to_test.automation.models import ACTIVE_STATUSES, AutomationJob, JobStatus
from spec_to_test.automation.store import AutomationError, new_owner_id
from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import TRANSLATIONS, t
from spec_to_test.models import Requirement, ReviewStatus, TestCase, Workspace

if TYPE_CHECKING:  # the service needs the automation extras (mcp, anyio); imported only when they exist
    from spec_to_test.automation.service import AutomationService

Persist = Callable[[Workspace], None]
OWNER = "automation_owner"
SELECTED = "automation_job"
RUNS = "automation_runs"  # part of the consent checkbox key: consent resets after every request
MESSAGE = "automation_message"  # (level, translation key, params), shown once on the next run
WORKSPACE = "workspace"
STATUS_ICONS = {
    "queued": "⏳", "planning": "🧭", "exploring": "🔎", "generating": "🛠️", "validating": "▶️",
    "passed": "✅", "failed": "❌", "blocked": "⛔", "cancelled": "🚫",
}
PROGRESS = {"queued": 0.05, "planning": 0.15, "exploring": 0.4, "generating": 0.65, "validating": 0.8}
REFRESH_SECONDS = 2


def _text(key: str, lang: str, params: dict[str, str] | None = None) -> str:
    """Translate with parameters; a missing parameter never breaks the page."""
    try:
        return t(key, lang, **(params or {}))
    except (KeyError, IndexError, ValueError):
        return t(key, lang)


def _message(level: str, key: str, **params: Any) -> None:
    st.session_state[MESSAGE] = (level, key, {k: str(v) for k, v in params.items()})


def _owner() -> str:
    if OWNER not in st.session_state:
        st.session_state[OWNER] = new_owner_id()
    return str(st.session_state[OWNER])


def _reason(code: str, params: dict[str, str], lang: str) -> str:
    params = dict(params)
    if code == "ai_error":
        return t(f"ai.error.{params.get('code', 'api')}", lang)
    if code == "ai_blocker":
        params["reason"] = t(f"automation.blocker.{params.get('reason', 'other')}", lang)
    return _text(f"automation.reason.{code}", lang, params)


def reason_text(job: AutomationJob, lang: str) -> str:
    return _reason(job.reason, job.reason_params, lang)


def _event_text(code: str, params: dict[str, str], lang: str) -> str:
    key = f"automation.event.{code}"
    return _text(key, lang, params) if key in TRANSLATIONS else _reason(code, params, lang)


def _status(status: JobStatus, lang: str) -> str:
    return f"{STATUS_ICONS[status.value]} {t(f'automation.status.{status.value}', lang)}"


def _duration(ms: int) -> str:
    return f"{ms / 1000:.1f} s"


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _on_submit(
    service: "AutomationService", test_case: TestCase, requirement: Requirement | None,
    ai_config: AIConfig | None, consent_key: str,
) -> None:
    st.session_state[RUNS] = st.session_state.get(RUNS, 0) + 1  # ask for consent again next time
    try:
        job = service.submit(
            _owner(),
            test_case,
            requirement,
            str(st.session_state.get("automation_url", "")),
            ai_config,
            consent=bool(st.session_state.get(consent_key)),
            allow_destructive=bool(st.session_state.get("automation_destructive")),
        )
    except AutomationError as error:
        _message("error", f"automation.error.{error.code}")
        return
    st.session_state[SELECTED] = job.id
    _message("success", "automation.submitted", id=test_case.id)


def _on_cancel(service: "AutomationService", job_id: str) -> None:
    if service.cancel(_owner(), job_id):
        _message("info", "automation.cancel_requested")


def _on_approve(service: "AutomationService", job_id: str, persist: Persist) -> None:
    workspace: Workspace | None = st.session_state.get(WORKSPACE)
    if workspace is None:
        _message("error", "automation.error.job_missing")
        return
    try:
        record = service.approve(_owner(), job_id, workspace)
    except AutomationError as error:
        _message("error", f"automation.error.{error.code}")
        return
    persist(workspace)
    _message("success", "automation.approved", id=record.id, tc=record.test_case_id)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def render_automation(lang: str, workspace: Workspace, ai_config: AIConfig | None, persist: Persist) -> None:
    st.caption(t("automation.explainer", lang))
    if message := st.session_state.pop(MESSAGE, None):
        level, key, params = message
        getattr(st, level)(_text(key, lang, params))

    config = load_automation_config()
    missing = ([] if ai_config else ["ai"]) + missing_prerequisites(config)
    if missing:
        st.info(
            t("automation.not_ready", lang) + "\n\n" + "\n".join(f"- {t(f'automation.missing.{m}', lang)}" for m in missing),
            icon="🔌",
        )
    else:
        from spec_to_test.automation.service import get_service

        service = get_service(config)
        _new_job_form(lang, workspace, ai_config, config, service)
        _jobs_section(lang, service, persist)
    _approved_section(lang, workspace)


def _new_job_form(
    lang: str, workspace: Workspace, ai_config: AIConfig | None, config: AutomationConfig, service: "AutomationService"
) -> None:
    approved = [tc for tc in workspace.test_cases if tc.review_status == ReviewStatus.APPROVED]
    with st.container(border=True, key="automation_new"):
        st.markdown(f"#### {t('automation.new_heading', lang)}")
        if not approved:
            st.info(t("automation.no_approved", lang))
            return
        titles = {tc.id: tc.title for tc in approved}
        tc_id = st.selectbox(
            t("automation.select_tc", lang), list(titles),
            format_func=lambda i: f"{i} — {titles[i]}", key="automation_tc",
        )
        test_case = next(tc for tc in approved if tc.id == tc_id)
        hosts = [str(rule) for rule in config.allowed_hosts]
        default_host = next((h for h in hosts if not h.startswith("*.")), "")
        if "automation_url" not in st.session_state and default_host:
            scheme = "http" if default_host.startswith(("localhost", "127.")) else "https"
            st.session_state["automation_url"] = f"{scheme}://{default_host}/"
        st.text_input(t("automation.target_url", lang), key="automation_url", placeholder="https://staging.example.com/")
        st.caption(t("automation.allowed_hosts", lang, hosts=", ".join(hosts)))
        st.checkbox(
            t("automation.allow_destructive", lang), key="automation_destructive",
            help=t("automation.allow_destructive_help", lang),
        )
        if config.secrets:
            st.caption(t("automation.secrets", lang, names=", ".join(config.secrets)))
        assert ai_config is not None  # checked by the caller
        consent_key = f"automation_consent_{st.session_state.get(RUNS, 0)}"
        consent = st.checkbox(
            t("automation.consent", lang, provider=ai_config.provider_name, model=escape_markdown(ai_config.model)),
            key=consent_key,
        )
        busy = any(job.status in ACTIVE_STATUSES for job in service.jobs(_owner()))
        st.button(
            t("automation.run", lang), type="primary", icon=":material/play_circle:", key="automation_run",
            disabled=not consent or busy,
            on_click=_on_submit, args=(service, test_case, workspace.requirement(test_case.requirement_id), ai_config, consent_key),
        )
        if busy:
            st.caption(t("automation.busy_hint", lang))


def _jobs_section(lang: str, service: "AutomationService", persist: Persist) -> None:
    jobs = service.jobs(_owner())
    if not jobs:
        return
    st.markdown(f"#### {t('automation.jobs_heading', lang)}")
    st.table(
        [
            {
                escape_markdown(t("automation.column.job", lang)): job.id[:8],
                escape_markdown(t("column.test_id", lang)): escape_markdown(job.test_case_id),
                escape_markdown(t("column.status", lang)): _status(job.status, lang),
                escape_markdown(t("automation.column.started", lang)): job.created_at.replace("T", " ")[:19],
                escape_markdown(t("automation.column.target", lang)): escape_markdown(job.target_url),
            }
            for job in jobs
        ],
        hide_index=True, border="horizontal",
    )
    ids = [job.id for job in jobs]
    if st.session_state.get(SELECTED) not in ids:
        st.session_state[SELECTED] = ids[0]
    labels = {job.id: f"{job.id[:8]} · {job.test_case_id} · {_status(job.status, lang)}" for job in jobs}
    job_id = st.selectbox(t("automation.select_job", lang), ids, format_func=lambda i: labels[i], key=SELECTED)
    job = next(j for j in jobs if j.id == job_id)
    if job.status in ACTIVE_STATUSES:
        st.fragment(_live_status, run_every=REFRESH_SECONDS)(lang, service, job_id)
    else:
        _job_view(lang, service, job, persist)


def _live_status(lang: str, service: "AutomationService", job_id: str) -> None:
    job = service.job(_owner(), job_id)
    if job is None:
        return
    if job.status.is_terminal:
        st.rerun()  # the whole page shows the results
    _progress(lang, job)
    st.button(
        t("automation.cancel", lang), icon=":material/stop_circle:", key=f"automation_cancel_{job.id}",
        on_click=_on_cancel, args=(service, job.id),
    )
    _activity(lang, job, expanded=True)


def _progress(lang: str, job: AutomationJob) -> None:
    label = t("automation.progress", lang, status=_status(job.status, lang), calls=job.tool_calls)
    st.progress(PROGRESS.get(job.status.value, 1.0), text=label)


def _activity(lang: str, job: AutomationJob, expanded: bool = False) -> None:
    with st.expander(t("automation.activity", lang), expanded=expanded, icon=":material/list:"):
        for event in job.events[-30:]:
            st.text(f"{event.at[11:19]}  {_status(event.status, lang)} — {_event_text(event.code, event.params, lang)}")


def _job_view(lang: str, service: "AutomationService", job: AutomationJob, persist: Persist) -> None:
    level = {"passed": st.success, "failed": st.error, "blocked": st.warning}.get(job.status.value, st.info)
    level(f"**{_status(job.status, lang)}** — {escape_markdown(reason_text(job, lang))}")
    run = job.last_run
    m = st.columns(4)
    m[0].metric(t("automation.metric.runs", lang), len(job.runs), border=True)
    m[1].metric(t("automation.metric.duration", lang), _duration(run.duration_ms) if run else "—", border=True)
    m[2].metric(t("automation.metric.tool_calls", lang), job.tool_calls, border=True)
    m[3].metric(t("automation.metric.tokens", lang), f"{job.input_tokens + job.output_tokens:,}", border=True)
    if job.repair_attempted:
        st.caption(t("automation.repair_note", lang))
    _activity(lang, job)

    if job.script and job.script.notes:
        st.markdown(f"**{t('automation.notes_heading', lang)}**")
        st.text(job.script.notes)
    if job.assertion_checks:
        st.markdown(f"**{t('automation.assertions_heading', lang)}**")
        st.caption(t("automation.assertions_explainer", lang))
        st.table(
            [
                {
                    escape_markdown(t("automation.column.assertion", lang)): escape_markdown(c.action),
                    escape_markdown(t("automation.column.expected", lang)): escape_markdown(c.value),
                    escape_markdown(t("automation.column.quote", lang)): escape_markdown(c.evidence),
                    escape_markdown(t("automation.column.source", lang)): t(f"automation.source.{c.source}", lang),
                    escape_markdown(t("automation.column.trace", lang)): t(f"automation.check.{c.status}", lang),
                }
                for c in job.assertion_checks
            ],
            hide_index=True, border="horizontal",
        )
    if job.code:
        with st.expander(t("automation.code_heading", lang), expanded=job.status == JobStatus.PASSED, icon=":material/code:"):
            st.code(job.code, language="typescript")
    if run is not None:
        _results(lang, service, job)
    _approval(lang, service, job, persist)


def _results(lang: str, service: "AutomationService", job: AutomationJob) -> None:
    run = job.last_run
    assert run is not None
    st.markdown(f"**{t('automation.results_heading', lang)}**")
    if run.tests:
        st.table(
            [
                {
                    escape_markdown(t("column.title", lang)): escape_markdown(o.title),
                    escape_markdown(t("column.status", lang)): ("✅ " if o.status == "passed" else "❌ ") + o.status,
                    escape_markdown(t("automation.metric.duration", lang)): _duration(o.duration_ms),
                    escape_markdown(t("automation.column.location", lang)): escape_markdown(o.error_location or "—"),
                }
                for o in run.tests
            ],
            hide_index=True, border="horizontal",
        )
    if not run.passed and (summary := run.failure_summary()):
        st.code(summary, language="text")
    store = service.store
    screenshots = [a for a in job.artifacts if a.kind == "screenshot"]
    if screenshots:
        st.markdown(f"**{t('automation.screenshots', lang)}**")
        for artifact in screenshots[:4]:
            if (path := store.artifact_path(job, artifact.path)) is not None:
                st.image(path.read_bytes(), caption=artifact.path.split("/")[-1], width=640)
    d1, d2, d3 = st.columns(3)
    if job.code:
        d1.download_button(
            t("automation.download.spec", lang), job.code.encode("utf-8"), file_name=job.spec_file.split("/")[-1],
            mime="text/plain", icon=":material/download:", key=f"automation_dl_spec_{job.id}",
        )
    trace = next((a for a in job.artifacts if a.kind == "trace"), None)
    if trace and (trace_path := store.artifact_path(job, trace.path)) is not None:
        d2.download_button(
            t("automation.download.trace", lang), trace_path.read_bytes(), file_name=f"trace-{job.id[:8]}.zip",
            mime="application/zip", icon=":material/download:", key=f"automation_dl_trace_{job.id}",
        )
    d3.download_button(
        t("automation.download.evidence", lang), job_bundle(store, job), file_name=f"automation-{job.id[:8]}.zip",
        mime="application/zip", icon=":material/download:", key=f"automation_dl_bundle_{job.id}",
    )


def _approval(lang: str, service: "AutomationService", job: AutomationJob, persist: Persist) -> None:
    if job.status != JobStatus.PASSED:
        return
    if job.approved:
        st.success(t("automation.already_approved", lang), icon=":material/verified:")
        return
    st.caption(t("automation.approve_help", lang))
    st.button(
        t("automation.approve", lang), type="primary", icon=":material/verified:", key=f"automation_approve_{job.id}",
        on_click=_on_approve, args=(service, job.id, persist),
    )


def _approved_section(lang: str, workspace: Workspace) -> None:
    st.markdown(f"#### {t('automation.approved_heading', lang)}")
    if not workspace.automated_tests:
        st.caption(t("automation.approved_none", lang))
        return
    st.table(
        [
            {
                escape_markdown(t("automation.column.test", lang)): escape_markdown(a.id),
                escape_markdown(t("column.test_id", lang)): escape_markdown(a.test_case_id),
                escape_markdown(t("column.id", lang)): escape_markdown(a.requirement_id),
                escape_markdown(t("automation.column.file", lang)): escape_markdown(a.file_name),
                escape_markdown(t("automation.column.approved_at", lang)): a.approved_at.replace("T", " ")[:19],
            }
            for a in workspace.automated_tests
        ],
        hide_index=True, border="horizontal",
    )
    st.download_button(
        t("automation.download.approved", lang), approved_bundle(workspace.automated_tests),
        file_name="playwright-tests.zip", mime="application/zip", icon=":material/download:",
        key="automation_dl_approved",
    )
