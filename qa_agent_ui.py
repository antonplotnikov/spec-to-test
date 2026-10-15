"""QA Agent page: plan, run, history and report of browser tests against an authorized web app.

Two modes: "Manual plan" (the tabs below, built from the open document's test
cases) and "Autonomous QA" (qa_auto_ui: discovery of a website, drafted
requirements and tests, approval, run, bug reports). The manual mode is the
default and needs an open document; the autonomous mode does not.

Rendering only; the work is in spec_to_test.qa_agent. The plan of the open
document is saved after every edit (RunStore, which follows the storage mode).
A run needs approved cases, an operator allowlist and the person's explicit
authorization, which resets after every run. While a run executes, the page
shows its progress; the browser itself works in a separate thread.
"""

from collections.abc import Callable
from typing import Any

import streamlit as st

import theme_ui
from projects_ui import active_project_id
from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import t
from spec_to_test.llm.config import AIConfig
from spec_to_test.llm.providers import AIError
from spec_to_test.models import ChangeImpact, Severity, Workspace
from spec_to_test.qa_agent import ai as qa_ai
from spec_to_test.qa_agent import planner
from spec_to_test.qa_agent import service as qa_service
from spec_to_test.qa_agent.executor import SCREENSHOT_WITHHELD, step_label
from spec_to_test.qa_agent.models import CaseOrigin, PlanCase, QARun, RunStatus, TestPlan
from spec_to_test.qa_agent.report import (
    bugs_csv,
    bundle,
    coverage,
    markdown_report,
    reason_text,
    results_csv,
    summary,
)
from spec_to_test.qa_agent.safety import QASettings, load_qa_settings
from spec_to_test.qa_agent.steps import StepError, format_steps
from spec_to_test.qa_agent.store import RunStore, open_run_store

PLAN = "qa_plan"
SELECTED = "qa_selected_run"
COUNTER = "qa_authorizations"  # part of the authorization checkbox keys: they reset after every run
MESSAGE = "qa_message"
STATUS_ICONS = {"passed": "✅", "failed": "❌", "blocked": "⛔", "not_run": "⏸️"}
STATUS_TONES = {"passed": "success", "failed": "danger", "blocked": "warning", "not_run": "neutral"}
COVERAGE_ICONS = {"passed": "✅", "partial": "🟡", "failed": "❌", "blocked": "⛔", "not_run": "⏸️", "not_covered": "➖"}
MAX_IMPORT_BYTES = planner.MAX_PLAN_BYTES


def _message(level: str, key: str, **params: Any) -> None:
    st.session_state[MESSAGE] = (level, key, {k: str(v) for k, v in params.items()})


def _show_message(lang: str) -> None:
    # Always drawn, even when empty: the tabs below must keep their place in the page,
    # or Streamlit re-creates them and jumps back to the first tab after every action.
    slot = st.container(key="qa_message_slot")
    if message := st.session_state.pop(MESSAGE, None):
        level, key, params = message
        try:
            text = t(key, lang, **params)
        except (KeyError, IndexError, ValueError):
            text = t(key, lang)
        getattr(slot, level)(text)


def _error_text(error: qa_service.QAError, lang: str) -> str:
    if error.code == "url":
        return reason_text("url", error.params, lang)
    return t(f"qaagent.error.{error.code}", lang)


def _store() -> RunStore:
    return open_run_store(st.session_state, active_project_id())


def _plan(store: RunStore, workspace: Workspace) -> TestPlan:
    plan: TestPlan | None = st.session_state.get(PLAN)
    if plan is None or plan.document_hash != workspace.document_hash:
        plan = store.load_plan(workspace.document_hash) or planner.new_plan(workspace)
        st.session_state[PLAN] = plan
        st.session_state.pop("qa_url", None)
    return plan


def _save(store: RunStore, plan: TestPlan) -> None:
    st.session_state[PLAN] = plan
    try:
        store.save_plan(plan)
    except (OSError, ValueError):
        _message("warning", "qaagent.plan.save_failed")


def _forget_case_widgets(case_id: str) -> None:
    for prefix in ("qa_title_", "qa_req_", "qa_steps_", "qa_expected_"):
        st.session_state.pop(f"{prefix}{case_id}", None)


# ---------------------------------------------------------------------------
# Callbacks (plan)
# ---------------------------------------------------------------------------

def _on_url(store: RunStore) -> None:
    plan: TestPlan = st.session_state[PLAN]
    plan.target_url = str(st.session_state.get("qa_url", "")).strip()[:2048]
    _save(store, plan)


def _on_generate(store: RunStore, workspace: Workspace) -> None:
    plan: TestPlan = st.session_state[PLAN]
    added = planner.add_test_cases(plan, workspace, only_approved=bool(st.session_state.get("qa_only_approved", True)))
    _save(store, plan)
    if added:
        _message("success", "qaagent.generate.added", count=added)
    else:
        _message("info", "qaagent.generate.none_added")


def _on_add_case(store: RunStore, workspace: Workspace, lang: str) -> None:
    plan: TestPlan = st.session_state[PLAN]
    try:
        case = planner.add_manual_case(plan, workspace.requirements[0].id, t("qaagent.new_case_title", lang))
    except planner.PlanError as error:
        _message("error", f"qaagent.plan_error.{error.code}")
        return
    _save(store, plan)
    _message("success", "qaagent.case.added", id=case.id)


def _on_save_case(store: RunStore, case_id: str, lang: str) -> None:
    plan: TestPlan = st.session_state[PLAN]
    if (case := plan.case(case_id)) is None:
        return
    try:
        planner.edit_case(
            case,
            title=str(st.session_state.get(f"qa_title_{case_id}", case.title)),
            requirement_id=str(st.session_state.get(f"qa_req_{case_id}", case.requirement_id)),
            steps_text=str(st.session_state.get(f"qa_steps_{case_id}", "")),
            expected_result=str(st.session_state.get(f"qa_expected_{case_id}", "")),
        )
    except StepError as error:
        problem = t(f"qaagent.step_error.{error.code}", lang)
        _message("error", "qaagent.step_error_line", line=error.line, text=error.text[:120], problem=problem)
        return
    except planner.PlanError as error:
        _message("error", f"qaagent.plan_error.{error.code}")
        return
    _save(store, plan)
    key = "qaagent.case.saved_revoked" if case.approved and not case.is_approved else "qaagent.case.saved"
    _message("success", key, id=case_id)


def _on_approve(store: RunStore, case_id: str) -> None:
    plan: TestPlan = st.session_state[PLAN]
    if (case := plan.case(case_id)) is None:
        return
    try:
        planner.approve(case)
    except planner.PlanError as error:
        _message("error", f"qaagent.plan_error.{error.code}")
        return
    _save(store, plan)
    _message("success", "qaagent.case.approved", id=case_id)


def _on_revoke(store: RunStore, case_id: str) -> None:
    plan: TestPlan = st.session_state[PLAN]
    if (case := plan.case(case_id)) is not None:
        planner.revoke(case)
        _save(store, plan)
        _message("info", "qaagent.case.revoked", id=case_id)


def _on_delete_case(store: RunStore, case_id: str) -> None:
    plan: TestPlan = st.session_state[PLAN]
    plan.cases = [c for c in plan.cases if c.id != case_id]
    _forget_case_widgets(case_id)
    _save(store, plan)
    _message("info", "qaagent.case.deleted", id=case_id)


def _on_import(store: RunStore, workspace: Workspace) -> None:
    uploaded = st.session_state.get("qa_import")
    if uploaded is None:
        return
    try:
        if uploaded.size > MAX_IMPORT_BYTES:
            raise planner.PlanError("too_large")
        plan = planner.import_plan(uploaded.getvalue(), workspace.document_hash)
    except planner.PlanError as error:
        _message("error", f"qaagent.plan_error.{error.code}")
        return
    for case in plan.cases:
        _forget_case_widgets(case.id)
    st.session_state.pop("qa_url", None)
    _save(store, plan)
    _message("success", "qaagent.plan.imported", count=len(plan.cases))


def _on_ai_suggest(store: RunStore, workspace: Workspace, case_id: str, ai_config: AIConfig, settings: QASettings) -> None:
    consent_key = f"qa_ai_consent_{case_id}"
    if not st.session_state.get(consent_key):
        _message("warning", "qaagent.ai.consent_needed")
        return
    st.session_state[consent_key] = False
    plan: TestPlan = st.session_state[PLAN]
    if (case := plan.case(case_id)) is None:
        return
    requirement = workspace.requirement(case.requirement_id)
    source = next((tc.steps for tc in workspace.test_cases if tc.id == case.test_case_id), [])
    try:
        steps = qa_ai.suggest_steps(
            ai_config, case, requirement.text if requirement else "", source, plan.target_url,
            list(settings.automation.secrets),
        )
    except AIError as error:
        _message("error", f"ai.error.{error.code}")
        return
    planner.set_steps(case, steps, CaseOrigin.AI)
    _forget_case_widgets(case_id)
    _save(store, plan)
    _message("success", "qaagent.ai.done", id=case_id)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

MODES = ("manual", "auto", "task")


def render_qa_agent(
    lang: str,
    workspace: Workspace | None,
    ai_config: AIConfig | None,
    docs: Any = None,
    no_document: Callable[[], object] | None = None,
    previous_impact: Callable[[Workspace], ChangeImpact | None] | None = None,
) -> None:
    """`docs` (qa_auto_ui.Documents) lets Autonomous QA and QA tasks save the workspace document;
    `no_document` draws the empty state of the manual and task modes when no document is open;
    `previous_impact` computes the Change Impact of a document that has none stored."""
    mode = st.segmented_control(t("qaagent.mode", lang), MODES, key="qa_mode", default="manual",
                                format_func=lambda m: t(f"qaagent.mode.{m}", lang), label_visibility="collapsed")
    if mode == "auto" and docs is not None:
        import qa_auto_ui  # here, not at the top: qa_auto_ui reuses helpers of this module

        _show_message(lang)
        settings = load_qa_settings()
        _setup(lang, settings)
        qa_auto_ui.render_autonomous(lang, ai_config, settings, _store(), docs)
        return
    if mode == "task":
        import qa_task_ui

        if workspace is None:
            st.caption(t("qatask.explainer", lang))
            if no_document is not None:
                no_document()
            return
        qa_task_ui.render_task(lang, workspace, docs.persist if docs is not None else None, previous_impact)
        return
    st.caption(t("qaagent.explainer", lang))
    if workspace is None:
        if no_document is not None:
            no_document()
        return
    _show_message(lang)
    settings = load_qa_settings()
    store = _store()
    plan = _plan(store, workspace)
    _setup(lang, settings)
    tabs = st.tabs([t("qaagent.tab.plan", lang), t("qaagent.tab.run", lang), t("qaagent.tab.history", lang),
                    t("qaagent.tab.report", lang)])
    with tabs[0]:
        _plan_tab(lang, workspace, plan, store, settings, ai_config)
    with tabs[1]:
        _run_tab(lang, workspace, plan, store, settings)
    runs = store.runs(workspace.document_hash)
    with tabs[2]:
        _history_tab(lang, workspace, plan, store, settings, runs)
    with tabs[3]:
        _report_tab(lang, workspace, store, runs)


def _setup(lang: str, settings: QASettings) -> None:
    with st.expander(t("qaagent.setup.heading", lang), icon=":material/shield:", expanded=not settings.enabled):
        hosts = ", ".join(str(rule) for rule in settings.automation.allowed_hosts)
        st.markdown(t("qaagent.setup.allowlist", lang, hosts=escape_markdown(hosts) if hosts else "—"))
        private = "qaagent.setup.private_on" if settings.automation.allow_private_network else "qaagent.setup.private_off"
        st.caption(t(private, lang))
        names = ", ".join(settings.automation.secrets)
        st.caption(t("qaagent.setup.secrets", lang, names=escape_markdown(names) if names else "—"))
        limits = settings.limits
        st.caption(t("qaagent.setup.limits", lang, cases=limits.max_cases, steps=limits.max_steps,
                     step=limits.step_timeout_ms // 1000, run=limits.run_timeout_s))
        if not settings.enabled:
            st.warning(t("qaagent.setup.disabled", lang))
        if not qa_service.playwright_available():
            st.warning(t("qaagent.setup.playwright_missing", lang))


# --- Plan tab ---------------------------------------------------------------

def _case_badges(lang: str, case: PlanCase) -> list[str]:
    if case.is_approved:
        state = theme_ui.badge(t("qaagent.case.badge_approved", lang), "success")
    elif case.approved:
        state = theme_ui.badge(t("qaagent.case.badge_changed", lang), "warning")
    elif not case.steps:
        state = theme_ui.badge(t("qaagent.case.badge_needs_steps", lang), "warning")
    else:
        state = theme_ui.badge(t("qaagent.case.badge_draft", lang), "neutral")
    origin = theme_ui.badge(t(f"qaagent.origin.{case.origin.value}", lang), "info" if case.origin == CaseOrigin.AI else "neutral")
    return [state, origin]


def _plan_tab(
    lang: str, workspace: Workspace, plan: TestPlan, store: RunStore, settings: QASettings, ai_config: AIConfig | None
) -> None:
    if "qa_url" not in st.session_state:
        st.session_state["qa_url"] = plan.target_url
    url = st.text_input(t("qaagent.url_label", lang), key="qa_url", on_change=_on_url, args=(store,),
                        placeholder="https://staging.example.com/", help=t("qaagent.url_help", lang))
    if url:
        try:
            qa_service.check_target(url, settings)
            st.caption(t("qaagent.url_ok", lang))
        except qa_service.QAError as error:
            st.warning(_error_text(error, lang))

    approved = sum(c.is_approved for c in plan.cases)
    needs = sum(not c.steps for c in plan.cases)
    m = st.columns(3)
    m[0].metric(t("qaagent.plan.cases", lang), len(plan.cases), border=True)
    m[1].metric(t("qaagent.plan.approved", lang), approved, border=True)
    m[2].metric(t("qaagent.plan.needs_steps", lang), needs, border=True)

    with theme_ui.card("qa_plan_actions"):
        st.checkbox(t("qaagent.generate.only_approved", lang), value=True, key="qa_only_approved")
        b1, b2 = st.columns(2)
        b1.button(t("qaagent.generate.button", lang), key="qa_generate", icon=":material/playlist_add:",
                  on_click=_on_generate, args=(store, workspace), width="stretch", type="primary")
        b2.button(t("qaagent.add_case", lang), key="qa_add_case", icon=":material/add:",
                  on_click=_on_add_case, args=(store, workspace, lang), width="stretch")
        with st.expander(t("qaagent.plan.import_export", lang), icon=":material/swap_vert:"):
            st.download_button(t("qaagent.plan.download", lang), plan.model_dump_json(indent=2),
                               file_name="qa-plan.json", mime="application/json", key="qa_plan_download",
                               icon=":material/download:")
            st.file_uploader(t("qaagent.plan.import", lang), type=["json"], key="qa_import")
            st.button(t("qaagent.plan.import_button", lang), key="qa_import_button", on_click=_on_import,
                      args=(store, workspace), icon=":material/upload:")
        with st.expander(t("qaagent.syntax.heading", lang), icon=":material/help:"):
            st.markdown(t("qaagent.syntax.body", lang))

    if unknown := planner.unknown_requirements(plan, workspace):
        st.warning(t("qaagent.plan.unknown_requirements", lang, ids=", ".join(unknown)))
    if not plan.cases:
        theme_ui.empty_state(t("qaagent.plan.empty", lang), t("qaagent.plan.empty_body", lang),
                             icon=":material/playlist_add_check:", key="qa_plan")
        return
    req_ids = [r.id for r in workspace.requirements]
    for case in plan.cases:
        _case_editor(lang, workspace, plan, case, req_ids, store, settings, ai_config)


def _case_editor(
    lang: str, workspace: Workspace, plan: TestPlan, case: PlanCase, req_ids: list[str], store: RunStore,
    settings: QASettings, ai_config: AIConfig | None,
) -> None:
    icon = "✅" if case.is_approved else ("⚠️" if not case.steps else "📝")
    label = f"{icon} {case.id} · {case.requirement_id} · {case.title}"
    with st.expander(escape_markdown(label[:160])):
        theme_ui.badges(*_case_badges(lang, case))
        if case.test_case_id:
            st.caption(t("qaagent.case.from_test_case", lang, id=case.test_case_id))
        if case.unparsed:
            st.info(t("qaagent.case.unparsed", lang))
            for number, text in enumerate(case.unparsed):
                theme_ui.list_item(f"qa_unparsed_{case.id}_{number}", ["•"], text)
        options = req_ids if case.requirement_id in req_ids else [case.requirement_id, *req_ids]
        with st.form(key=f"qa_form_{case.id}", border=False):
            st.text_input(t("qaagent.case.title", lang), value=case.title, key=f"qa_title_{case.id}", max_chars=300)
            st.selectbox(t("qaagent.case.requirement", lang), options, index=options.index(case.requirement_id),
                         key=f"qa_req_{case.id}")
            st.text_area(t("qaagent.case.steps", lang), value=format_steps(case.steps), key=f"qa_steps_{case.id}",
                         height=180, help=t("qaagent.case.steps_help", lang),
                         placeholder="goto /login\nfill label=Email | demo@example.com\nclick role=button[name=Sign in]\nexpect_text Welcome")
            st.text_area(t("qaagent.case.expected", lang), value=case.expected_result, key=f"qa_expected_{case.id}",
                         height=80)
            st.form_submit_button(t("qaagent.case.save", lang), icon=":material/save:",
                                  on_click=_on_save_case, args=(store, case.id, lang))
        row = st.columns(3)
        if case.is_approved:
            row[0].button(t("qaagent.case.revoke", lang), key=f"qa_revoke_{case.id}", icon=":material/undo:",
                          on_click=_on_revoke, args=(store, case.id), width="stretch")
        else:
            problem = planner.approval_problem(case)
            row[0].button(t("qaagent.case.approve", lang), key=f"qa_approve_{case.id}", icon=":material/verified:",
                          on_click=_on_approve, args=(store, case.id), width="stretch", type="primary",
                          disabled=problem is not None,
                          help=t(f"qaagent.plan_error.{problem}", lang) if problem else None)
        row[1].button(t("qaagent.case.delete", lang), key=f"qa_delete_{case.id}", icon=":material/delete:",
                      on_click=_on_delete_case, args=(store, case.id), width="stretch")
        if ai_config is not None:
            with row[2].popover(t("qaagent.ai.button", lang), icon=":material/auto_awesome:", width="stretch"):
                st.caption(t("qaagent.ai.explainer", lang, provider=ai_config.provider_name))
                st.checkbox(t("qaagent.ai.consent", lang), key=f"qa_ai_consent_{case.id}")
                st.button(t("qaagent.ai.run", lang), key=f"qa_ai_{case.id}", on_click=_on_ai_suggest,
                          args=(store, workspace, case.id, ai_config, settings))


# --- Run tab ----------------------------------------------------------------

def _host_of(url: str) -> str:
    rest = url.split("://", 1)[-1]
    return rest.split("/", 1)[0] or "—"


def _execute(
    lang: str, cases: list[PlanCase], url: str, store: RunStore, settings: QASettings, workspace: Workspace,
    allow_destructive: bool, parent_run_id: str = "", allow_forms: bool = False,
) -> None:
    st.session_state[COUNTER] = st.session_state.get(COUNTER, 0) + 1  # authorization is asked again next time
    bar = st.progress(0.0, text=t("qaagent.run.starting", lang))

    def progress(done: int, total: int, result: Any) -> None:
        bar.progress(done / max(total, 1), text=t("qaagent.run.progress", lang, done=done, total=total,
                                                  case=result.case_id, status=t(f"qaagent.status.{result.status.value}", lang)))

    try:
        run = qa_service.run_cases(
            cases, url, settings, store, authorized=True, allow_destructive=allow_destructive,
            allow_forms=allow_forms, document_hash=workspace.document_hash, document_title=workspace.title, parent_run_id=parent_run_id,
            on_progress=progress,
        )
    except qa_service.QAError as error:
        bar.empty()
        st.error(_error_text(error, lang))
        return
    st.session_state[SELECTED] = run.id
    _forget_pickers()
    counts = run.counts()
    _message("success", "qaagent.run.done", **counts, bugs=len(run.bugs))
    st.rerun()


def _run_tab(lang: str, workspace: Workspace, plan: TestPlan, store: RunStore, settings: QASettings) -> None:
    approved = [c for c in plan.cases if c.is_approved]
    url = plan.target_url
    st.markdown(t("qaagent.run.summary", lang, count=len(approved), total=len(plan.cases),
                  url=escape_markdown(url) if url else "—"))
    st.caption(t("qaagent.run.not_approved_note", lang))
    ready = True
    if not settings.enabled:
        st.warning(t("qaagent.error.disabled", lang))
        ready = False
    elif not qa_service.playwright_available():
        st.warning(t("qaagent.error.playwright_missing", lang))
        ready = False
    if not url:
        st.info(t("qaagent.run.no_url", lang))
        ready = False
    if not approved:
        st.info(t("qaagent.error.nothing_approved", lang))
        ready = False
    counter = st.session_state.get(COUNTER, 0)
    authorized = st.checkbox(t("qaagent.run.authorize", lang, host=escape_markdown(_host_of(url)), count=len(approved)),
                             key=f"qa_authorize_{counter}", disabled=not ready)
    destructive = st.checkbox(t("qaagent.run.destructive", lang), key=f"qa_destructive_{counter}", disabled=not ready,
                              help=t("qaagent.run.destructive_help", lang))
    allow_forms = _allow_forms(lang, [c for c in approved if c.risk], f"qa_forms_{counter}", not ready)
    if st.button(t("qaagent.run.start", lang, count=len(approved)), key="qa_run", type="primary",
                 icon=":material/play_arrow:", disabled=not (ready and authorized)):
        _execute(lang, plan.cases, url, store, settings, workspace, destructive, allow_forms=allow_forms)


def _allow_forms(lang: str, risky: list[PlanCase], key: str, disabled: bool = False) -> bool:
    """The run-level permission for cases that submit forms (shown only when there are any)."""
    if not risky:
        return False
    return st.checkbox(t("qaauto.run.allow_forms", lang, count=len(risky)), key=key, disabled=disabled,
                       help=t("qaauto.run.allow_forms_help", lang))


# --- History tab ------------------------------------------------------------

def _run_label(lang: str, run: QARun) -> str:
    counts = run.counts()
    parts = [f"{STATUS_ICONS[s]} {counts[s]}" for s in STATUS_ICONS if counts[s]]
    retest = f" · {t('qaagent.history.retest_badge', lang)}" if run.parent_run_id else ""
    return f"{run.created_at.replace('T', ' ')[:19]} · {run.id[:8]} · {' '.join(parts) or '—'}{retest}"


def _pick_run(lang: str, runs: list[QARun], key: str) -> QARun:
    ids = [r.id for r in runs]
    selected = st.session_state.get(SELECTED)
    index = ids.index(selected) if selected in ids else 0
    by_id = {r.id: r for r in runs}
    chosen = st.selectbox(t("qaagent.history.select", lang), ids, index=index, key=key,
                          format_func=lambda rid: _run_label(lang, by_id[rid]))
    st.session_state[SELECTED] = chosen
    return by_id[str(chosen)]


def _table(rows: list[dict]) -> None:
    safe = [{escape_markdown(str(k)): escape_markdown(str(v)) for k, v in row.items()} for row in rows]
    st.table(safe, hide_index=True, border="horizontal")


def _on_save_bug(store: RunStore, run_id: str, bug_id: str) -> None:
    run = store.load(run_id)
    if run is None:
        return
    for bug in run.bugs:
        if bug.id == bug_id:
            title = str(st.session_state.get(f"qa_bug_title_{bug_id}", bug.title)).strip()
            bug.title = (title or bug.title)[:300]
            bug.severity = Severity(st.session_state.get(f"qa_bug_severity_{bug_id}", bug.severity.value))
    store.save(run)
    _message("success", "qaagent.bug.saved", id=bug_id)


def _forget_pickers() -> None:
    """Let the run pickers follow SELECTED again (they keep their own state otherwise)."""
    for key in ("qa_history_pick", "qa_report_pick"):
        st.session_state.pop(key, None)


def _on_delete_run(store: RunStore, run_id: str) -> None:
    store.delete(run_id)
    st.session_state.pop(SELECTED, None)
    _forget_pickers()
    _message("info", "qaagent.history.deleted")


def _history_tab(
    lang: str, workspace: Workspace, plan: TestPlan, store: RunStore, settings: QASettings, runs: list[QARun]
) -> None:
    if not runs:
        theme_ui.empty_state(t("qaagent.history.empty", lang), t("qaagent.history.empty_body", lang),
                             icon=":material/history:", key="qa_history")
        return
    run = _pick_run(lang, runs, "qa_history_pick")
    counts = run.counts()
    m = st.columns(4)
    for col, status in zip(m, STATUS_ICONS, strict=True):
        col.metric(f"{STATUS_ICONS[status]} {t(f'qaagent.status.{status}', lang)}", counts[status], border=True)
    st.caption(t("qaagent.history.meta", lang, url=run.target_url, started=run.created_at, finished=run.finished_at or "—",
                 browser=run.browser or "—", state=t(f"qaagent.state.{run.state.value}", lang)))
    if run.parent_run_id:
        st.caption(t("qaagent.history.parent", lang, id=run.parent_run_id))
    if run.error:
        st.error(t("qaagent.history.run_error", lang))
        st.code(run.error, language=None)
    for result in run.results:
        icon = STATUS_ICONS[result.status.value]
        with st.expander(escape_markdown(f"{icon} {result.case_id} · {result.requirement_id} · {result.title}"[:160])):
            theme_ui.badges(theme_ui.badge(t(f"qaagent.status.{result.status.value}", lang),
                                           STATUS_TONES[result.status.value]))
            if result.reason:
                st.markdown(f"**{t('qaagent.report.reason', lang)}:** "
                            f"{escape_markdown(reason_text(result.reason, result.reason_params, lang))}")
            if result.expected_result:
                st.markdown(f"**{t('qaagent.history.expected', lang)}:**")
                st.text(result.expected_result)
            if result.actual_result:
                st.markdown(f"**{t('qaagent.history.actual', lang)}:**")
                st.text(result.actual_result)
            if result.error:
                st.markdown(f"**{t('qaagent.history.error', lang)}:**")
                st.code(result.error, language=None)
            if result.steps:
                _table([
                    {
                        "#": s.index + 1,
                        t("qaagent.history.step", lang): step_label(s.step),
                        t("qaagent.report.result", lang): f"{STATUS_ICONS[s.status.value]} "
                                                          f"{t(f'qaagent.status.{s.status.value}', lang)}",
                        "ms": s.duration_ms,
                    }
                    for s in result.steps
                ])
            if result.screenshot == SCREENSHOT_WITHHELD:
                st.caption(t("qaagent.report.screenshot_withheld", lang))
            elif (path := store.evidence(run, result.screenshot)) is not None:
                st.image(str(path), caption=t("qaagent.history.screenshot", lang, name=result.screenshot))
            if result.console_errors:
                st.markdown(f"**{t('qaagent.history.console', lang)}:**")
                st.code("\n".join(result.console_errors), language=None)
            if result.blocked_requests:
                st.markdown(f"**{t('qaagent.history.blocked_requests', lang)}:**")
                st.code("\n".join(result.blocked_requests), language=None)
    _bugs(lang, run, store)
    _retest(lang, workspace, plan, store, settings, run)
    st.button(t("qaagent.history.delete", lang), key=f"qa_delete_run_{run.id}", icon=":material/delete:",
              on_click=_on_delete_run, args=(store, run.id))


def _bugs(lang: str, run: QARun, store: RunStore) -> None:
    theme_ui.section(t("qaagent.report.bug_reports", lang), ":material/bug_report:")
    if not run.bugs:
        st.caption(t("qaagent.report.no_bugs", lang))
        return
    severities = [s.value for s in Severity]
    for bug in run.bugs:
        with st.expander(escape_markdown(f"🐞 {bug.id} · {bug.title}"[:160])):
            with st.form(key=f"qa_bug_form_{bug.id}", border=False):
                st.text_input(t("qaagent.bug.title", lang), value=bug.title, key=f"qa_bug_title_{bug.id}", max_chars=300)
                st.selectbox(t("qaagent.bug.severity", lang), severities, index=severities.index(bug.severity.value),
                             key=f"qa_bug_severity_{bug.id}", format_func=lambda s: t(f"severity.{s}", lang))
                st.form_submit_button(t("qaagent.bug.save", lang), on_click=_on_save_bug,
                                      args=(store, run.id, bug.id), icon=":material/save:")
            st.markdown(f"**{t('qaagent.bug.steps', lang)}:**")
            st.text("\n".join(f"{i}. {s}" for i, s in enumerate(bug.steps_to_reproduce, start=1)))
            st.markdown(f"**{t('qaagent.history.expected', lang)}:**")
            st.text(bug.expected or "—")
            st.markdown(f"**{t('qaagent.history.actual', lang)}:**")
            st.text(bug.actual or "—")
            st.markdown(f"**{t('qaagent.bug.evidence', lang)}:**")
            st.text("\n".join(bug.evidence) or "—")
            st.markdown(f"**{t('qaagent.bug.environment', lang)}:**")
            st.text("\n".join(f"{k}: {v}" for k, v in bug.environment.items()))


def _retest(lang: str, workspace: Workspace, plan: TestPlan, store: RunStore, settings: QASettings, run: QARun) -> None:
    cases = qa_service.retest_cases(run, plan.cases)
    theme_ui.section(t("qaagent.history.retest_heading", lang), ":material/replay:")
    if not cases:
        st.caption(t("qaagent.history.nothing_to_retest", lang))
        return
    counter = st.session_state.get(COUNTER, 0)
    authorized = st.checkbox(
        t("qaagent.run.authorize", lang, host=escape_markdown(_host_of(run.target_url)), count=len(cases)),
        key=f"qa_retest_authorize_{counter}",
    )
    destructive = st.checkbox(t("qaagent.run.destructive", lang), key=f"qa_retest_destructive_{counter}",
                              help=t("qaagent.run.destructive_help", lang))
    allow_forms = _allow_forms(lang, [c for c in cases if c.risk], f"qa_retest_forms_{counter}")
    if st.button(t("qaagent.history.retest", lang, count=len(cases)), key="qa_retest", icon=":material/replay:",
                 disabled=not authorized):
        _execute(lang, cases, run.target_url, store, settings, workspace, destructive, parent_run_id=run.id,
                 allow_forms=allow_forms)


# --- Report tab -------------------------------------------------------------

def _report_tab(lang: str, workspace: Workspace, store: RunStore, runs: list[QARun]) -> None:
    if not runs:
        theme_ui.empty_state(t("qaagent.history.empty", lang), t("qaagent.history.empty_body", lang),
                             icon=":material/summarize:", key="qa_report")
        return
    run = _pick_run(lang, runs, "qa_report_pick")
    rows = coverage(run, workspace.requirements)
    stats = summary(run, rows)
    m = st.columns(4)
    m[0].metric(t("qaagent.report.pass_rate", lang), f"{stats['pass_rate']}%", border=True,
                help=t("qaagent.report.pass_rate_note", lang))
    m[1].metric(t("qaagent.report.requirements_passed", lang),
                f"{stats['requirements_passed']}/{stats['requirements']}", border=True)
    m[2].metric(t("qaagent.report.requirements_failed", lang), stats["requirements_failed"], border=True)
    m[3].metric(t("qaagent.report.bugs", lang), stats["bugs"], border=True)
    theme_ui.section(t("qaagent.report.coverage", lang), ":material/account_tree:")
    _table([
        {
            t("column.id", lang): row.requirement_id,
            t("column.requirement", lang): row.requirement_text or "—",
            t("qaagent.report.cases", lang): ", ".join(row.case_ids) or "—",
            t("qaagent.report.result", lang): f"{COVERAGE_ICONS[row.status.value]} {t(f'qaagent.coverage.{row.status.value}', lang)}",
            t("qaagent.report.bugs", lang): ", ".join(row.bug_ids) or "—",
        }
        for row in rows
    ])
    theme_ui.section(t("qaagent.report.downloads", lang), ":material/download:")
    run_dir = store.run_dir(run.id)
    d = st.columns(3)
    d[0].download_button(t("qaagent.report.download_md", lang), markdown_report(run, workspace.requirements, lang),
                         file_name=f"qa-report-{run.id}.md", mime="text/markdown", key="qa_dl_md", width="stretch")
    d[1].download_button(t("qaagent.report.download_zip", lang), bundle(run, run_dir, workspace.requirements, lang),
                         file_name=f"qa-report-{run.id}.zip", mime="application/zip", key="qa_dl_zip", width="stretch")
    d[2].download_button(t("qaagent.report.download_json", lang), run.model_dump_json(indent=2),
                         file_name=f"qa-run-{run.id}.json", mime="application/json", key="qa_dl_json", width="stretch")
    e = st.columns(3)
    e[0].download_button(t("qaagent.report.download_results", lang), results_csv(run),
                         file_name=f"qa-results-{run.id}.csv", mime="text/csv", key="qa_dl_results", width="stretch")
    e[1].download_button(t("qaagent.report.download_bugs", lang), bugs_csv(run),
                         file_name=f"qa-bugs-{run.id}.csv", mime="text/csv", key="qa_dl_bugs", width="stretch")
    if any(r.status == RunStatus.NOT_RUN for r in run.results):
        st.caption(t("qaagent.report.not_run_note", lang))
