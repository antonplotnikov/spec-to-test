"""Autonomous QA mode of the QA Agent page.

URL → discovery → draft requirements → test plan → approval → run → bug reports → final report.

Rendering only; the work is in spec_to_test.qa_agent (autonomous, discovery,
inference, autoplan, triage, auto_report). Discovery and drafting start from
one button once the person confirmed they may test the host; requirements,
cases (separately for those that submit forms) and every run need explicit
approval. Approved work is sent to a workspace document, so Requirements
Analysis, Grill Mode, Test Cases, the RTM and the manual QA Agent tabs see it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import streamlit as st

import theme_ui
from qa_agent_ui import COUNTER, PLAN, STATUS_ICONS, _bugs, _error_text, _host_of, _message, _table
from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import t
from spec_to_test.llm.config import AIConfig
from spec_to_test.llm.providers import AIError
from spec_to_test.models import Workspace
from spec_to_test.qa_agent import auto_ai, autonomous, autoplan
from spec_to_test.qa_agent import service as qa_service
from spec_to_test.qa_agent.auto_models import AutoSession, Basis, Decision, DiscoveryState
from spec_to_test.qa_agent.auto_report import final_bundle, final_report
from spec_to_test.qa_agent.discovery import path_of
from spec_to_test.qa_agent.executor import step_label
from spec_to_test.qa_agent.models import QARun, TestPlan
from spec_to_test.qa_agent.report import reason_text
from spec_to_test.qa_agent.safety import QASettings
from spec_to_test.qa_agent.steps import format_steps
from spec_to_test.qa_agent.store import RunStore
from spec_to_test.qa_agent.triage import Outcome, outcomes

SESSION = "qa_auto_session"
PICK = "qa_auto_pick"
PENDING_PICK = "qa_auto_pending_pick"  # applied to the picker before it is drawn on the next run
NEW = "__new__"
BASIS_TONES = {"observed": "success", "inferred": "warning", "unknown": "neutral"}
BASIS_ICONS = {"observed": "👁️", "inferred": "💭", "unknown": "❓"}
DECISION_TONES = {"proposed": "neutral", "approved": "success", "rejected": "danger", "deferred": "info"}
OUTCOME_ICONS = {"passed": "✅", "defect": "🐞", "uncertain_expectation": "❔", "timeout": "⏱️",
                 "environment": "🖥️", "security_block": "🛡️", "not_run": "⏸️"}


@dataclass
class Documents:
    """How the page reads and saves workspace documents of the active project."""

    load: Callable[[str], Workspace | None]
    persist: Callable[[Workspace], None]
    remember: Callable[[str], None]


def _save(store: RunStore, session: AutoSession) -> None:
    try:
        store.save_session(session)
    except (OSError, ValueError):
        _message("warning", "qaagent.plan.save_failed")


def _current(sessions: list[AutoSession]) -> AutoSession | None:
    chosen = st.session_state.get(SESSION)
    return next((s for s in sessions if s.id == chosen), None)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _on_decide(store: RunStore, session_id: str, requirement_id: str, decision: str, lang: str) -> None:
    if (session := store.load_session(session_id)) is None:
        return
    autoplan.decide(session, requirement_id, Decision(decision), lang)
    _save(store, session)
    _message("success", f"qaauto.decided.{decision}", id=requirement_id)


def _on_bulk(store: RunStore, session_id: str, basis: str, decision: str, lang: str) -> None:
    if (session := store.load_session(session_id)) is None:
        return
    count = 0
    for req in session.requirements:
        if req.basis.value == basis and req.decision == Decision.PROPOSED:
            autoplan.decide(session, req.id, Decision(decision), lang)
            count += 1
    _save(store, session)
    _message("success", "qaauto.bulk_done", count=count)


def _on_edit(store: RunStore, session_id: str, requirement_id: str, lang: str) -> None:
    if (session := store.load_session(session_id)) is None:
        return
    autoplan.edit_requirement(
        session, requirement_id,
        str(st.session_state.get(f"qa_auto_desc_{requirement_id}", "")),
        str(st.session_state.get(f"qa_auto_answer_{requirement_id}", "")), lang,
    )
    _save(store, session)
    _message("success", "qaauto.req_saved", id=requirement_id)


def _on_approve_cases(store: RunStore, session_id: str, case_ids: list[str]) -> None:
    if (session := store.load_session(session_id)) is None:
        return
    count = autoplan.approve_cases(session, case_ids)
    _save(store, session)
    _message("success" if count else "info", "qaauto.cases_approved", count=count)


def _on_approve_risky(store: RunStore, session_id: str, case_id: str) -> None:
    if not st.session_state.get(f"qa_auto_risk_ok_{case_id}"):
        _message("warning", "qaauto.risk_confirm_needed")
        return
    _on_approve_cases(store, session_id, [case_id])


def _on_revoke_case(store: RunStore, session_id: str, case_id: str) -> None:
    if (session := store.load_session(session_id)) is None or (case := session.case(case_id)) is None:
        return
    case.approved = False
    _save(store, session)
    _message("info", "qaagent.case.revoked", id=case_id)


def _on_ai(store: RunStore, session_id: str, ai_config: AIConfig, lang: str) -> None:
    if not st.session_state.get("qa_auto_ai_consent"):
        _message("warning", "qaagent.ai.consent_needed")
        return
    st.session_state["qa_auto_ai_consent"] = False
    if (session := store.load_session(session_id)) is None:
        return
    try:
        added, questions = auto_ai.interpret(ai_config, session, lang)
    except AIError as error:
        _message("error", f"ai.error.{error.code}")
        return
    _save(store, session)
    _message("success", "qaauto.ai_done", count=added, questions=questions)


def _on_delete_session(store: RunStore, session_id: str) -> None:
    store.delete_session(session_id)
    st.session_state.pop(SESSION, None)
    st.session_state[PENDING_PICK] = NEW
    _message("info", "qaauto.session_deleted")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def render_autonomous(lang: str, ai_config: AIConfig | None, settings: QASettings, store: RunStore,
                      docs: Documents) -> None:
    st.caption(t("qaauto.explainer", lang))
    sessions = store.sessions()
    _start(lang, settings, store, sessions)
    session = _current(sessions)
    if session is None:
        theme_ui.empty_state(t("qaauto.empty", lang), t("qaauto.empty_body", lang), icon=":material/travel_explore:",
                             key="qa_auto")
        return
    _status(lang, session, settings, store)
    tabs = st.tabs([t("qaauto.tab.site", lang), t("qaauto.tab.requirements", lang), t("qaauto.tab.plan", lang),
                    t("qaauto.tab.run", lang), t("qaauto.tab.report", lang)])
    with tabs[0]:
        _site_tab(lang, session)
    with tabs[1]:
        _requirements_tab(lang, session, store, ai_config)
    with tabs[2]:
        _plan_tab(lang, session, store, docs)
    runs = autonomous.session_runs(session, store)
    with tabs[3]:
        _run_tab(lang, session, store, settings, docs, runs)
    with tabs[4]:
        _report_tab(lang, session, store, docs, runs)


def _session_label(lang: str, session: AutoSession) -> str:
    approved = sum(r.decision == Decision.APPROVED for r in session.requirements)
    state = t(f"qaauto.state.{autonomous.effective_state(session).value}", lang)
    return t("qaauto.session_label", lang, created=session.created_at.replace("T", " ")[:16],
             host=_host_of(session.target_url), state=state, total=len(session.requirements), approved=approved)


def _start(lang: str, settings: QASettings, store: RunStore, sessions: list[AutoSession]) -> None:
    with theme_ui.card("qa_auto_start"):
        ids = [NEW, *[s.id for s in sessions]]
        by_id = {s.id: s for s in sessions}
        if (pending := st.session_state.pop(PENDING_PICK, None)) in ids:
            st.session_state[PICK] = pending  # allowed: the picker is not drawn yet in this run
        elif st.session_state.get(PICK) not in ids:
            st.session_state[PICK] = ids[1] if sessions else NEW  # the newest session, or a new one
        picked = st.selectbox(t("qaauto.session", lang), ids, key=PICK,
                              format_func=lambda sid: t("qaauto.new_session", lang) if sid == NEW
                              else _session_label(lang, by_id[sid]))
        st.session_state[SESSION] = None if picked == NEW else picked
        if picked != NEW:
            return
        url = st.text_input(t("qaagent.url_label", lang), key="qa_auto_url", placeholder="https://staging.example.com/",
                            help=t("qaauto.url_help", lang))
        ready = settings.enabled and qa_service.playwright_available()
        if url:
            try:
                qa_service.check_target(url, settings)
                st.caption(t("qaagent.url_ok", lang))
            except qa_service.QAError as error:
                st.warning(_error_text(error, lang))
                ready = False
        limits = settings.limits
        st.caption(t("qaauto.discovery_limits", lang, pages=limits.discovery_max_pages,
                     depth=limits.discovery_max_depth, seconds=limits.discovery_timeout_s))
        counter = st.session_state.get(COUNTER, 0)
        authorized = st.checkbox(t("qaauto.authorize", lang, host=escape_markdown(_host_of(url)) if url else "—"),
                                 key=f"qa_auto_authorize_{counter}", disabled=not (ready and url))
        if st.button(t("qaauto.start", lang), key="qa_auto_start_button", type="primary",
                     icon=":material/travel_explore:", disabled=not (ready and url and authorized)):
            try:
                session = autonomous.new_session(url, settings, lang, authorized=authorized)
            except qa_service.QAError as error:
                st.error(_error_text(error, lang))
                return
            store.save_session(session)
            _discover(lang, session, settings, store)


def _discover(lang: str, session: AutoSession, settings: QASettings, store: RunStore) -> None:
    st.session_state[COUNTER] = st.session_state.get(COUNTER, 0) + 1  # authorization is asked again next time
    bar = st.progress(0.0, text=t("qaauto.discovering", lang))

    def progress(done: int, total: int, page: Any) -> None:
        bar.progress(min(done / max(total, 1), 1.0), text=t("qaauto.discovery_progress", lang, done=done,
                                                             path=page.path))

    try:
        autonomous.discover(session, settings, store, lang, authorized=True, on_page=progress)
    except qa_service.QAError as error:
        bar.empty()
        st.error(_error_text(error, lang))
        return
    st.session_state[SESSION] = session.id
    st.session_state[PENDING_PICK] = session.id
    _message("success", "qaauto.discovered", pages=len(session.pages), requirements=len(session.requirements),
             cases=len(session.cases))
    st.rerun()


def _status(lang: str, session: AutoSession, settings: QASettings, store: RunStore) -> None:
    # Always drawn with the same structure: the tabs below must keep their place.
    with st.container(key="qa_auto_status"):
        state = autonomous.effective_state(session)
        approved_reqs = sum(r.decision == Decision.APPROVED for r in session.requirements)
        approved_cases = sum(c.approved for c in session.cases)
        active_cases = sum(not c.retired for c in session.cases)
        m = st.columns(4)
        m[0].metric(t("qaauto.metric.pages", lang), len(session.pages), border=True)
        m[1].metric(t("qaauto.metric.requirements", lang), f"{approved_reqs}/{len(session.requirements)}", border=True,
                    help=t("qaauto.metric.requirements_help", lang))
        m[2].metric(t("qaauto.metric.cases", lang), f"{approved_cases}/{active_cases}", border=True,
                    help=t("qaauto.metric.cases_help", lang))
        m[3].metric(t("qaauto.metric.runs", lang), len(session.run_ids), border=True)
        st.caption(t("qaauto.target", lang, url=escape_markdown(session.target_url), id=session.id,
                     state=t(f"qaauto.state.{state.value}", lang)))
        if state in (DiscoveryState.INTERRUPTED, DiscoveryState.FAILED):
            st.warning(t("qaauto.interrupted", lang, pages=len(session.pages), queued=len(session.queue)))
            if session.error and session.error not in ("timeout", "interrupted"):
                st.code(session.error, language=None)
            counter = st.session_state.get(COUNTER, 0)
            ok = st.checkbox(t("qaauto.authorize", lang, host=escape_markdown(_host_of(session.target_url))),
                             key=f"qa_auto_resume_authorize_{counter}")
            if st.button(t("qaauto.resume", lang), key="qa_auto_resume", icon=":material/resume:", disabled=not ok):
                _discover(lang, session, settings, store)


# --- Site map ---------------------------------------------------------------------

def _site_tab(lang: str, session: AutoSession) -> None:
    theme_ui.section(t("qaauto.site.pages", lang), ":material/account_tree:")
    if not session.pages:
        st.caption(t("qaauto.site.none", lang))
        return
    _table([
        {
            t("qaauto.report.path", lang): page.path,
            t("qaauto.report.status", lang): t(f"qaauto.page_error.{page.error}", lang) if page.error else page.status,
            t("qaauto.report.page_title", lang): page.title or "—",
            t("qaauto.report.heading", lang): page.h1 or "—",
            t("qaauto.report.forms", lang): ", ".join(page.form_ids) or "—",
            t("qaauto.site.from", lang): (path_of(page.linked_from) if page.linked_from else "—")
            + (f" ← {page.redirected_from}" if page.redirected_from else ""),
        }
        for page in session.pages
    ])
    theme_ui.section(t("qaauto.site.forms", lang), ":material/edit_note:")
    if not session.forms:
        st.caption(t("qaauto.site.no_forms", lang))
    for form in session.forms:
        label = f"{form.id} · {path_of(form.page_url)} · {form.display} · {t(f'qaauto.form_kind.{form.kind.value}', lang)}"
        with st.expander(escape_markdown(label[:160])):
            if form.destructive_term:
                st.warning(t("qaauto.site.destructive_form", lang, term=form.destructive_term))
            _table([
                {
                    t("qaauto.site.field", lang): f.display,
                    t("qaauto.site.type", lang): f.type or f.tag,
                    t("qaauto.site.required", lang): "✓" if f.required else "",
                    "maxlength": f.maxlength or "",
                    t("qaauto.site.locator", lang): f.locator or t("qaauto.site.no_locator", lang),
                    t("qaauto.report.evidence", lang): f.evidence_id,
                }
                for f in form.fields
            ])
            st.caption(t("qaauto.site.submit", lang, label=escape_markdown(form.submit_label or "—"),
                         method=form.method.upper(), action=escape_markdown(path_of(form.action))))
    skipped = [(page, link) for page in session.pages for link in page.links if link.skipped]
    blocked = [(page, request) for page in session.pages for request in page.blocked_requests]
    if skipped or blocked:
        theme_ui.section(t("qaauto.site.not_opened", lang), ":material/block:",
                         caption=t("qaauto.site.not_opened_help", lang))
        rows = [{t("qaauto.report.path", lang): page.path, t("qaauto.site.link", lang): link.text or link.url,
                 t("qaauto.site.address", lang): link.url, t("qaauto.site.why", lang):
                 t(f"qaauto.skipped.{link.skipped}", lang)} for page, link in skipped[:100]]
        rows += [{t("qaauto.report.path", lang): page.path, t("qaauto.site.link", lang): "—",
                  t("qaauto.site.address", lang): request, t("qaauto.site.why", lang): t("qaauto.skipped.request", lang)}
                 for page, request in blocked[:50]]
        _table(rows)
    with st.expander(t("qaauto.site.evidence", lang, count=len(session.evidence)), icon=":material/fact_check:"):
        _table([
            {"ID": e.id, t("qaauto.site.kind", lang): t(f"qaauto.evidence.{e.kind.value}", lang),
             "URL": path_of(e.url), t("qaauto.site.text", lang): e.text or "—", t("qaauto.site.locator", lang):
             e.locator or "—"}
            for e in session.evidence
        ])


# --- Requirements -------------------------------------------------------------------

def _requirements_tab(lang: str, session: AutoSession, store: RunStore, ai_config: AIConfig | None) -> None:
    st.caption(t("qaauto.req.explainer", lang))
    if not session.requirements:
        st.caption(t("qaauto.req.none", lang))
        return
    with theme_ui.card("qa_auto_bulk"):
        b = st.columns(3)
        b[0].button(t("qaauto.bulk.approve_observed", lang), key="qa_auto_bulk_observed", icon=":material/done_all:",
                    on_click=_on_bulk, args=(store, session.id, Basis.OBSERVED.value, Decision.APPROVED.value, lang),
                    width="stretch")
        b[1].button(t("qaauto.bulk.defer_unknown", lang), key="qa_auto_bulk_unknown", icon=":material/schedule:",
                    on_click=_on_bulk, args=(store, session.id, Basis.UNKNOWN.value, Decision.DEFERRED.value, lang),
                    width="stretch")
        if ai_config is not None:
            with b[2].popover(t("qaauto.ai.button", lang), icon=":material/auto_awesome:", width="stretch"):
                st.caption(t("qaauto.ai.explainer", lang, provider=ai_config.provider_name))
                st.checkbox(t("qaauto.ai.consent", lang), key="qa_auto_ai_consent")
                st.button(t("qaagent.ai.run", lang), key="qa_auto_ai_run", on_click=_on_ai,
                          args=(store, session.id, ai_config, lang))
        else:
            b[2].caption(t("qaauto.ai.off", lang))
    filters = st.segmented_control(t("qaauto.req.filter", lang), ["all", *[b.value for b in Basis]],
                                   key="qa_auto_req_filter", default="all",
                                   format_func=lambda v: t("qaauto.req.all", lang) if v == "all"
                                   else t(f"qaauto.basis.{v}", lang))
    for req in session.requirements:
        if filters not in (None, "all") and req.basis.value != filters:
            continue
        _requirement(lang, session, store, req)


def _requirement(lang: str, session: AutoSession, store: RunStore, req: Any) -> None:
    decision_icon = {"approved": "✅", "rejected": "🚫", "deferred": "⏳", "proposed": "📝"}[req.decision.value]
    label = (f"{decision_icon} {req.id} · {BASIS_ICONS[req.basis.value]} {t(f'qaauto.basis.{req.basis.value}', lang)} "
             f"· {req.confidence}% · {req.description}")
    with st.expander(escape_markdown(label[:200])):
        theme_ui.badges(
            theme_ui.badge(t(f"qaauto.basis.{req.basis.value}", lang), BASIS_TONES[req.basis.value]),
            theme_ui.badge(t(f"qaauto.decision.{req.decision.value}", lang), DECISION_TONES[req.decision.value]),
            theme_ui.badge(t(f"qaauto.origin.{req.origin.value}", lang), "info" if req.origin.value == "ai" else "neutral"),
            theme_ui.badge(t("qaauto.confidence", lang, value=req.confidence), "neutral"),
        )
        st.caption(t(f"qaauto.basis_help.{req.basis.value}", lang))
        if req.url:
            st.caption(f"URL: {escape_markdown(req.url)}")
        if req.evidence_ids:
            st.markdown(f"**{t('qaauto.report.evidence', lang)}:**")
            for evidence_id in req.evidence_ids:
                if (item := session.evidence_item(evidence_id)) is not None:
                    text = f" — “{item.text}”" if item.text else ""
                    locator = f" · {item.locator}" if item.locator else ""
                    st.markdown(escape_markdown(f"{item.id} · {t(f'qaauto.evidence.{item.kind.value}', lang)} · "
                                                f"{path_of(item.url)}{text}{locator}"))
        if req.questions:
            st.markdown(f"**{t('qaauto.report.questions', lang)}:**")
            for question in req.questions:
                st.markdown(f"- {escape_markdown(question)}")
        with st.form(key=f"qa_auto_req_form_{req.id}", border=False):
            st.text_area(t("qaauto.req.description", lang), value=req.description, key=f"qa_auto_desc_{req.id}",
                         height=80, max_chars=1000)
            if req.questions:
                st.text_input(t("qaauto.req.answer", lang), value=req.answer, key=f"qa_auto_answer_{req.id}",
                              max_chars=500, help=t("qaauto.req.answer_help", lang))
            st.form_submit_button(t("qaagent.case.save", lang), icon=":material/save:", on_click=_on_edit,
                                  args=(store, session.id, req.id, lang))
        row = st.columns(3)
        for col, decision, icon in zip(row, (Decision.APPROVED, Decision.REJECTED, Decision.DEFERRED),
                                       (":material/verified:", ":material/block:", ":material/schedule:"), strict=True):
            col.button(t(f"qaauto.action.{decision.value}", lang), key=f"qa_auto_{decision.value}_{req.id}", icon=icon,
                       on_click=_on_decide, args=(store, session.id, req.id, decision.value, lang), width="stretch",
                       disabled=req.decision == decision, type="primary" if decision == Decision.APPROVED else "secondary")
        if not req.template:
            st.caption(t("qaauto.req.no_template", lang))


# --- Test plan ----------------------------------------------------------------------

def _sync(lang: str, session: AutoSession, store: RunStore, docs: Documents) -> TestPlan:
    doc_hash = session.document_hash or autoplan.session_document_hash(session)
    workspace = docs.load(doc_hash)
    plan = store.load_plan(doc_hash)
    title = t("qaauto.document_title", lang, host=_host_of(session.target_url))
    workspace, plan = autoplan.sync_workspace(session, workspace, plan, lang, title)
    docs.persist(workspace)
    docs.remember(workspace.document_hash)
    store.save_plan(plan)
    st.session_state[PLAN] = plan
    st.session_state.pop("qa_url", None)
    _save(store, session)
    return plan


def _on_send(lang: str, store: RunStore, session_id: str, docs: Documents) -> None:
    if (session := store.load_session(session_id)) is None:
        return
    if not any(r.decision == Decision.APPROVED for r in session.requirements):
        _message("warning", "qaauto.plan.nothing_approved")
        return
    _sync(lang, session, store, docs)
    _message("success", "qaauto.plan.sent", requirements=sum(r.decision == Decision.APPROVED for r in session.requirements),
             cases=sum(c.approved for c in session.cases))


def _plan_tab(lang: str, session: AutoSession, store: RunStore, docs: Documents) -> None:
    st.caption(t("qaauto.plan.explainer", lang))
    if not session.cases:
        st.caption(t("qaauto.plan.none", lang))
        return
    safe = [c.id for c in session.cases if not c.risk and not c.approved and autoplan.approvable(session, c)]
    visible = [c for c in session.cases if not c.retired]
    with theme_ui.card("qa_auto_plan_actions"):
        b = st.columns(2)
        b[0].button(t("qaauto.plan.approve_safe", lang, count=len(safe)), key="qa_auto_approve_safe",
                    icon=":material/done_all:", on_click=_on_approve_cases, args=(store, session.id, safe),
                    disabled=not safe, width="stretch")
        b[1].button(t("qaauto.plan.send", lang), key="qa_auto_send", icon=":material/send:", type="primary",
                    on_click=_on_send, args=(lang, store, session.id, docs), width="stretch",
                    help=t("qaauto.plan.send_help", lang))
        if session.document_hash:
            st.caption(t("qaauto.plan.linked", lang, hash=session.document_hash))
    for case in visible:
        req = session.requirement(case.requirement_id)
        state = "✅" if case.approved else ("⚠️" if case.risk else "📝")
        label = f"{state} {case.id} · {case.requirement_id} · {case.title}"
        with st.expander(escape_markdown(label[:180])):
            badges = [theme_ui.badge(t(f"test_type.{case.test_type.value}", lang), "info")]
            if req is not None:
                badges.append(theme_ui.badge(t(f"qaauto.basis.{req.basis.value}", lang), BASIS_TONES[req.basis.value]))
                badges.append(theme_ui.badge(t(f"qaauto.decision.{req.decision.value}", lang),
                                             DECISION_TONES[req.decision.value]))
            if case.risk:
                badges.append(theme_ui.badge(t("qaauto.plan.risk_badge", lang), "warning"))
            theme_ui.badges(*badges)
            if case.test_case_id or case.plan_case_id:
                st.caption(t("qaauto.plan.links", lang, tc=case.test_case_id or "—", qa=case.plan_case_id or "—"))
            st.code(format_steps(case.steps), language=None)
            st.markdown(f"**{t('qaagent.history.expected', lang)}:** {escape_markdown(case.expected_result)}")
            if case.risk:
                st.warning(t("qaauto.plan.risk", lang))
            if case.approved:
                st.button(t("qaagent.case.revoke", lang), key=f"qa_auto_revoke_{case.id}", icon=":material/undo:",
                          on_click=_on_revoke_case, args=(store, session.id, case.id))
            elif not autoplan.approvable(session, case):
                st.caption(t("qaauto.plan.req_not_approved", lang))
            elif case.risk:
                st.checkbox(t("qaauto.plan.risk_confirm", lang), key=f"qa_auto_risk_ok_{case.id}")
                st.button(t("qaagent.case.approve", lang), key=f"qa_auto_approve_{case.id}", icon=":material/verified:",
                          on_click=_on_approve_risky, args=(store, session.id, case.id))
            else:
                st.button(t("qaagent.case.approve", lang), key=f"qa_auto_approve_{case.id}", icon=":material/verified:",
                          on_click=_on_approve_cases, args=(store, session.id, [case.id]))


# --- Run ----------------------------------------------------------------------------

def _execute(lang: str, session: AutoSession, cases: list, settings: QASettings, store: RunStore,
             allow_forms: bool, parent_run_id: str = "") -> None:
    st.session_state[COUNTER] = st.session_state.get(COUNTER, 0) + 1
    bar = st.progress(0.0, text=t("qaagent.run.starting", lang))

    def progress(done: int, total: int, result: Any) -> None:
        bar.progress(done / max(total, 1), text=t("qaagent.run.progress", lang, done=done, total=total,
                                                  case=result.case_id, status=t(f"qaagent.status.{result.status.value}", lang)))

    try:
        run = autonomous.execute(session, cases, settings, store, authorized=True, allow_forms=allow_forms,
                                 document_title=t("qaauto.document_title", lang, host=_host_of(session.target_url)),
                                 parent_run_id=parent_run_id, on_progress=progress)
    except qa_service.QAError as error:
        bar.empty()
        st.error(_error_text(error, lang))
        return
    _message("success", "qaagent.run.done", **run.counts(), bugs=len(run.bugs))
    st.rerun()


def _run_tab(lang: str, session: AutoSession, store: RunStore, settings: QASettings, docs: Documents,
             runs: list[QARun]) -> None:
    plan = store.load_plan(session.document_hash) if session.document_hash else None
    cases = autoplan.plan_cases(session, plan) if plan is not None else []
    approved = [c for c in cases if c.is_approved]
    risky = [c for c in approved if c.risk]
    st.markdown(t("qaagent.run.summary", lang, count=len(approved), total=len(cases),
                  url=escape_markdown(session.target_url)))
    pending = sum(c.approved for c in session.cases) - len(approved)
    if pending > 0:
        st.info(t("qaauto.run.send_first", lang, count=pending))
    ready = settings.enabled and qa_service.playwright_available() and bool(approved)
    if not approved:
        st.info(t("qaauto.run.nothing", lang))
    counter = st.session_state.get(COUNTER, 0)
    authorized = st.checkbox(t("qaagent.run.authorize", lang, host=escape_markdown(_host_of(session.target_url)),
                               count=len(approved)), key=f"qa_auto_run_authorize_{counter}", disabled=not ready)
    allow_forms = False
    if risky:
        allow_forms = st.checkbox(t("qaauto.run.allow_forms", lang, count=len(risky)), key=f"qa_auto_forms_{counter}",
                                  disabled=not ready, help=t("qaauto.run.allow_forms_help", lang))
    st.caption(t("qaauto.run.no_destructive", lang))
    if st.button(t("qaagent.run.start", lang, count=len(approved)), key="qa_auto_run", type="primary",
                 icon=":material/play_arrow:", disabled=not (ready and authorized)):
        _execute(lang, session, cases, settings, store, allow_forms)
    if not runs:
        return
    run = runs[0]
    for stale in runs:
        autonomous.mark_interrupted(stale, store)
    theme_ui.section(t("qaauto.run.latest", lang, id=run.id[:8]), ":material/fact_check:")
    if autonomous.interrupted(run) and (left := autonomous.unfinished_cases(run, cases)):
        st.warning(t("qaauto.run.interrupted", lang, count=len(left)))
        ok = st.checkbox(t("qaagent.run.authorize", lang, host=escape_markdown(_host_of(session.target_url)),
                           count=len(left)), key=f"qa_auto_resume_run_authorize_{counter}")
        if st.button(t("qaauto.run.resume", lang, count=len(left)), key="qa_auto_resume_run", icon=":material/resume:",
                     disabled=not ok):
            _execute(lang, session, left, settings, store, run.allow_forms, parent_run_id=run.id)
    found = outcomes(run, session)
    counts = {o.value: sum(v == o for v in found.values()) for o in Outcome}
    st.markdown(" · ".join(f"{OUTCOME_ICONS[k]} {t(f'qaauto.outcome.{k}', lang)}: {v}" for k, v in counts.items() if v))
    _table([
        {
            t("qaagent.report.case", lang): r.case_id,
            "ID": r.requirement_id,
            t("qaagent.report.case_title", lang): r.title,
            t("qaagent.report.result", lang): f"{STATUS_ICONS[r.status.value]} {t(f'qaagent.status.{r.status.value}', lang)}",
            t("qaauto.report.outcome", lang): f"{OUTCOME_ICONS[found[r.case_id].value]} "
                                               f"{t(f'qaauto.outcome.{found[r.case_id].value}', lang)}",
            t("qaagent.report.reason", lang): reason_text(r.reason, r.reason_params, lang) if r.reason else "—",
            t("qaauto.run.failed_step", lang): step_label(r.failed_step.step) if r.failed_step else "—",
        }
        for r in run.results
    ])
    st.caption(t("qaauto.run.details", lang))
    _bugs(lang, run, store)
    retest = qa_service.retest_cases(run, cases)
    if retest:
        theme_ui.section(t("qaagent.history.retest_heading", lang), ":material/replay:")
        ok = st.checkbox(t("qaagent.run.authorize", lang, host=escape_markdown(_host_of(session.target_url)),
                           count=len(retest)), key=f"qa_auto_retest_authorize_{counter}")
        if st.button(t("qaagent.history.retest", lang, count=len(retest)), key="qa_auto_retest",
                     icon=":material/replay:", disabled=not ok):
            _execute(lang, session, retest, settings, store, run.allow_forms, parent_run_id=run.id)


# --- Final report -------------------------------------------------------------------

def _report_tab(lang: str, session: AutoSession, store: RunStore, docs: Documents, runs: list[QARun]) -> None:
    run = runs[0] if runs else None
    report = final_report(session, run, lang)
    workspace = docs.load(session.document_hash) if session.document_hash else None
    run_dir = store.run_dir(run.id) if run is not None else None
    d = st.columns(3)
    d[0].download_button(t("qaagent.report.download_md", lang), report, file_name=f"autonomous-qa-{session.id}.md",
                         mime="text/markdown", key="qa_auto_dl_md", width="stretch")
    d[1].download_button(t("qaagent.report.download_zip", lang),
                         final_bundle(session, run, run_dir, workspace.requirements if workspace else None, lang),
                         file_name=f"autonomous-qa-{session.id}.zip", mime="application/zip", key="qa_auto_dl_zip",
                         width="stretch")
    d[2].download_button(t("qaauto.report.download_session", lang), session.model_dump_json(indent=2),
                         file_name=f"autonomous-qa-session-{session.id}.json", mime="application/json",
                         key="qa_auto_dl_json", width="stretch")
    # Shown as source, not rendered: it quotes page text, which is untrusted (no live links or images).
    with st.expander(t("qaauto.report.preview", lang), icon=":material/description:", expanded=True):
        st.code(report, language="markdown", wrap_lines=True)
    st.button(t("qaauto.delete_session", lang), key=f"qa_auto_delete_{session.id}", icon=":material/delete:",
              on_click=_on_delete_session, args=(store, session.id), help=t("qaauto.delete_session_help", lang))

