"""Pages of the app other than Grill Mode: Home, Requirements Analysis, Test Cases,
QA Agent, Bug Reports (drawn by bug_reports_ui), RTM, Dashboard, Export and Settings.

Rendering only. The analysis, test generation, RTM, exports and AI calls are
the same functions the single-page layout used; every edit still goes through
`Page.persist`, which saves the open document. Functions that tests replace
(`automation_ui.render_automation`, `ai_analysis.run_ai_analysis`) are looked
up on their module at call time.
"""

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd
import streamlit as st

import automation_ui
import bug_reports_ui
import llm_ui
import qa_agent_ui
import qa_auto_ui
import runs_ui
import shell_ui
import theme_ui
from projects_ui import (
    INPUT_TEXT,
    active_project_id,
    input_file_key,
    project_name,
    remember_document,
    render_project_settings,
)
from spec_to_test import ai_analysis
from spec_to_test import findings as finding_status
from spec_to_test.ai_analysis import AIError
from spec_to_test.bug_generator.store import open_bug_report_store
from spec_to_test.bug_reports import defect_from_suggestion, generate_defects, next_defect_id
from spec_to_test.bulk_edit import delete_cases, filter_cases, set_review_status
from spec_to_test.change_impact import Recommendation, change_impact, recommend
from spec_to_test.duplicates import find_duplicates
from spec_to_test.execution import case_ids_in_runs, executed_requirement_ids, open_run_store
from spec_to_test.exports import (
    DEFAULT_JIRA_TEST_ISSUE_TYPE,
    impact_csv,
    impact_headers,
    impact_markdown,
    impact_rows,
    jira_defects_csv,
    jira_test_cases_csv,
    markdown_report,
    rtm_csv,
    testrail_csv,
)
from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import clarification_question, t, unit_for
from spec_to_test.impact_decisions import (
    Decision,
    DecisionError,
    DecisionRecord,
    DecisionState,
    DecisionStore,
    Snapshot,
    impact_fingerprint,
    open_decision_store,
    record_decision,
    snapshot_of,
    status_of,
)
from spec_to_test.input_parser import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    InputError,
    extract_requirements,
    read_uploaded_file,
)
from spec_to_test.llm.config import AIConfig, LLMSettings
from spec_to_test.models import (
    MAX_REASON_LENGTH,
    ChangeImpact,
    ClarificationStatus,
    DefectReport,
    Finding,
    FindingEvent,
    Requirement,
    ReviewStatus,
    Severity,
    TestCase,
    TestPriority,
    TestType,
    Workspace,
)
from spec_to_test.projects import ProjectStore, document_title, now
from spec_to_test.quality import QualityScore, average_score, score_all
from spec_to_test.rtm import (
    Coverage,
    RTMRow,
    build_rtm,
    coverage_levels,
    filter_rows,
    orphan_test_case_ids,
    summarize,
    traceability_gaps,
)
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.scenario_coverage import ScenarioCategory, categories_of_test_case, scenario_coverage
from spec_to_test.storage import document_hash, persistence_enabled
from spec_to_test.suites import SuiteKind, plan_suites, suite_workspace
from spec_to_test.test_critic import CriticIssue, TestCaseScore, score_test_case
from spec_to_test.test_design import TestDesign, design_tests, format_value
from spec_to_test.test_generator import generate_test_cases, is_partial_check, next_test_case_id, other_conditions

SEVERITY_BADGES = {"high": "🔴", "medium": "🟠", "low": "🟡"}
SEVERITY_TONES = {"high": "danger", "medium": "warning", "low": "neutral"}
STATUS_BADGES = {"clear": "✅", "needs_clarification": "⚠️", "resolved": "☑️"}
COVERAGE_BADGES = {"covered": "✅", "partial": "🟡", "not_covered": "❌"}
REVIEW_BADGES = {"draft": "📝", "reviewed": "👀", "approved": "✅"}
REVIEW_TONES = {"draft": "neutral", "reviewed": "info", "approved": "success"}
GRADE_BADGES = {"good": "🟢", "fair": "🟠", "poor": "🔴"}
ALL = "__all__"
TABLE_SCROLL_ROWS = 15
TABLE_MAX_HEIGHT = 720
WORKSPACE = "workspace"


@dataclass
class Page:
    lang: str
    store: ProjectStore
    persist: Callable[[Workspace], None]
    ai_config: AIConfig | None
    automation_ai: AIConfig | None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def bar_chart(counts: dict[str, int]) -> None:
    st.bar_chart(
        pd.DataFrame({"label": list(counts), "count": list(counts.values())}),
        x="label", y="count", x_label="", y_label="", horizontal=True, sort=False, height=200,
    )


def show_table(rows: list[dict]) -> None:
    """Full-width table that wraps long text, so nothing is cut off.

    Long tables scroll inside a fixed height instead of stretching the page.
    """
    # Cells are rendered as Markdown; escape so user text appears exactly as written.
    safe_rows = [
        {escape_markdown(str(k)): escape_markdown(v) if isinstance(v, str) else v for k, v in row.items()}
        for row in rows
    ]
    st.table(
        safe_rows,
        hide_index=True,
        border="horizontal",
        height=TABLE_MAX_HEIGHT if len(rows) > TABLE_SCROLL_ROWS else "content",
    )


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def flash(message: str, icon: str = "✅") -> None:
    """Show a confirmation after the next rerun (messages before st.rerun() are lost)."""
    st.session_state.setdefault("flash", []).append((message, icon))


def show_flash() -> None:
    for message, icon in st.session_state.pop("flash", []):
        st.toast(message, icon=icon)


def _workspace(p: Page, key: str) -> Workspace | None:
    """The open document, or an empty state that leads to Home."""
    ws: Workspace | None = st.session_state.get(WORKSPACE)
    if ws is None:
        theme_ui.empty_state(t("ui.empty.no_document", p.lang), t("ui.empty.no_document_body", p.lang),
                             icon=":material/description:", key=key)
        st.button(t("ui.empty.go_home", p.lang), key=f"{key}_go_home", icon=":material/arrow_forward:",
                  type="primary", on_click=shell_ui.nav_callback, args=("home",))
    return ws


def _restored_note(lang: str) -> None:
    if restored := st.session_state.get("restored"):
        st.info(t("storage.kept_in_session" if restored == "session" else "storage.restored", lang), icon="💾")


def _req_label(ws: Workspace, req_id: str) -> str:
    req = ws.requirement(req_id)
    snippet = req.text if req and len(req.text) <= 60 else (req.text[:59] + "…" if req else "")
    return f"{req_id} — {snippet}"


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

def home(p: Page) -> None:
    lang = p.lang
    overview = st.container()  # filled after the input, so a failed Analyze shows no stale results
    active = next(pr for pr in p.store.projects() if pr.id == active_project_id())
    with theme_ui.card("input"):
        theme_ui.section(
            t("ui.home.add_heading", lang), ":material/upload_file:",
            t("projects.input_heading", lang, name=escape_markdown(project_name(active, lang))),
        )
        col_text, col_file = st.columns([3, 2], gap="medium")
        with col_text:
            text = st.text_area(
                t("input.text_label", lang), placeholder=t("input.text_placeholder", lang), height=220, key=INPUT_TEXT,
            )
        with col_file:
            uploaded = st.file_uploader(
                t("input.file_label", lang, max_mb=MAX_FILE_SIZE_BYTES // (1024 * 1024)),
                type=[ext.lstrip(".") for ext in ALLOWED_EXTENSIONS],
                key=input_file_key(),
            )
            if uploaded is not None:
                st.info(t("input.file_used", lang), icon="📎")
        analyze = st.button(t("input.analyze_button", lang), type="primary", icon=":material/search:", key="analyze")
    if analyze:
        _analyze(p, text, uploaded)

    ws: Workspace | None = st.session_state.get(WORKSPACE)
    with overview:
        if ws is None:
            st.info(t("input.empty_state", lang), icon="💡")
            _how_it_works(lang)
        else:
            _restored_note(lang)
            _document_overview(p, ws)


def _analyze(p: Page, text: str, uploaded) -> None:  # noqa: ANN001 - Streamlit's UploadedFile
    lang = p.lang
    st.session_state.pop("restored", None)
    st.session_state["ai_consent"] = False  # consent is per document and per run
    try:
        with st.spinner(t("input.analyzing", lang)):
            source = read_uploaded_file(uploaded.name, uploaded.getvalue()) if uploaded else text
            requirements = extract_requirements(source)
            doc_hash = document_hash(source.strip())
            # Same document again in this project: reopen its saved work. "session" mode keeps
            # it in this session only; "local" mode reloads the saved file, which may hold newer
            # edits from another tab (keeping the session copy would overwrite them).
            saved = p.store.load(active_project_id(), doc_hash)
            if saved is not None:
                workspace = saved
                st.session_state["restored"] = "disk" if persistence_enabled() else "session"
            else:
                result = analyze_requirements(requirements)
                workspace = Workspace(
                    document_hash=doc_hash,
                    title=document_title(source, uploaded.name if uploaded else None),
                    created_at=now(),
                    requirements=result.requirements,
                    findings=result.findings,
                )
                workspace.test_cases = generate_test_cases(workspace, lang)
                project_id = active_project_id()
                workspace.change_impact = change_impact(
                    workspace, p.store.documents(project_id), lambda h: p.store.load(project_id, h),
                )
            p.persist(workspace)
            remember_document(active_project_id(), doc_hash)
        shell_ui.go_to("analysis")
        st.rerun()  # the sidebar shows the project's documents, including this one
    except InputError as error:
        st.session_state.pop(WORKSPACE, None)
        st.error(t(f"error.{error.code}", lang, **error.params))


def _how_it_works(lang: str) -> None:
    cols = st.columns(4)
    for col, (step, icon) in zip(cols, [
        ("analyze", ":material/fact_check:"), ("grill", ":material/forum:"),
        ("tests", ":material/checklist:"), ("export", ":material/ios_share:"),
    ], strict=True):
        with col, theme_ui.card(f"step_{step}"):
            st.markdown(f"**{icon} {t(f'ui.home.step_{step}', lang)}**")
            st.caption(t(f"ui.home.step_{step}_body", lang))


def _document_overview(p: Page, ws: Workspace) -> None:
    lang = p.lang
    scores = score_all(ws.requirements, ws.findings)
    summary = summarize(build_rtm(ws, scores), ws)
    with theme_ui.card("document"):
        theme_ui.section(t("ui.home.open_document", lang), ":material/description:")
        title = ws.title or (ws.requirements[0].text if ws.requirements else "")
        st.markdown(f"**{escape_markdown(title)}**")
        if ws.created_at:
            st.caption(t("ui.home.created", lang, date=ws.created_at[:16].replace("T", " ")))
        m = st.columns(5)
        m[0].metric(t("dash.requirements", lang), summary.requirements, border=True)
        m[1].metric(t("dash.open_issues", lang), summary.open_issues, border=True)
        overall = average_score(scores.values())
        m[2].metric(t("dash.avg_quality", lang), "—" if overall is None else overall, border=True)
        m[3].metric(t("dash.test_cases", lang), summary.test_cases, border=True)
        m[4].metric(t("dash.coverage", lang), f"{summary.coverage_percent:g}%", border=True,
                    help=t("dash.coverage_help", lang, any=f"{summary.any_test_percent:g}"))
        actions = st.columns(4)
        for col, (page, icon) in zip(actions, [
            ("analysis", ":material/fact_check:"), ("grill", ":material/forum:"),
            ("tests", ":material/checklist:"), ("export", ":material/ios_share:"),
        ], strict=True):
            col.button(t(f"ui.home.open_{page}", lang), key=f"home_open_{page}", icon=icon, width="stretch",
                       type="primary" if page == "grill" and summary.open_issues else "secondary",
                       on_click=shell_ui.nav_callback, args=(page,))


# ---------------------------------------------------------------------------
# Requirements Analysis
# ---------------------------------------------------------------------------

_BUTTON_KEYS = {Decision.ACCEPTED: "accept", Decision.REJECTED: "reject", Decision.DEFERRED: "defer"}


@dataclass(frozen=True)
class _PendingDecision:
    """What a confirmation needs, computed when the page is drawn (so the buttons act on what is shown)."""

    recommendation: Recommendation
    snapshot: Snapshot
    previous_hash: str
    new_hash: str
    position_based: bool


def _decision_label(lang: str, state: DecisionState, latest: DecisionRecord | None) -> str:
    if latest is None or state == DecisionState.UNDECIDED:
        return t("impact.decision.undecided", lang)
    if state == DecisionState.STALE:
        return t("impact.decision.stale", lang)
    return t(f"impact.decision.{latest.decision.value}", lang)


def _record_decision(store: DecisionStore, project_id: str, lang: str, pending: _PendingDecision,
                     decision: Decision, comment_key: str) -> None:
    """Record one confirmation. A callback: it runs before the page is drawn again. Changes no test case."""
    comment = str(st.session_state.get(comment_key, ""))
    try:
        record = record_decision(
            store, project_id, recommendation=pending.recommendation, snapshot=pending.snapshot, decision=decision,
            previous_hash=pending.previous_hash, new_hash=pending.new_hash,
            position_based=pending.position_based, comment=comment,
        )
    except DecisionError as error:
        flash(t(f"impact.decision.error.{error.code}", lang), icon="⚠️")
        return
    except (OSError, ValueError):
        flash(t("storage.save_failed", lang), icon="⚠️")
        return
    flash(t("impact.decision.saved", lang, id=record.id, decision=t(f"impact.decision.{decision.value}", lang)),
          icon="✅")


def _recommendations_block(p: Page, ws: Workspace, impact: ChangeImpact) -> None:
    """Suggested action per changed requirement, the decision taken on each, and the Impact Report.

    Suggestions only: a decision records a confirmation and changes no test case."""
    lang = p.lang
    project_id = active_project_id()
    recommendations = recommend(impact, [req.id for req in ws.requirements])
    changed = [r for r in recommendations if r.change != "unchanged"]
    previous = p.store.load(project_id, impact.previous_document_hash) if impact.previous_document_hash else None
    impact_fp = impact_fingerprint(recommendations, impact.previous_document_hash, ws.document_hash)
    store = open_decision_store(st.session_state)
    records = store.records(project_id)
    pending: dict[str, _PendingDecision] = {}
    labels: dict[str, str] = {}
    for rec in changed:
        snapshot = snapshot_of(rec, impact, previous, impact_fp)
        state, latest = status_of(records, rec.requirement_id, snapshot)
        labels[rec.requirement_id] = _decision_label(lang, state, latest)
        req = ws.requirement(rec.requirement_id)
        pending[rec.requirement_id] = _PendingDecision(
            recommendation=rec, snapshot=snapshot, previous_hash=impact.previous_document_hash,
            new_hash=ws.document_hash, position_based=req is not None and not req.has_explicit_id,
        )
    for rec in recommendations:
        labels.setdefault(rec.requirement_id, "—")
    with st.expander(t("impact.rec.heading", lang), icon=":material/checklist:", expanded=True):
        rows = [dict(zip(impact_headers(lang), row, strict=True)) for row in impact_rows(changed, lang)]
        for row, rec in zip(rows, changed, strict=True):
            row[t("impact.decision.column", lang)] = labels[rec.requirement_id]
        show_table(rows)
        st.caption(t("impact.rec.keep_count", lang, count=len(recommendations) - len(changed)))
        md_col, csv_col = st.columns(2)
        md_col.download_button(
            t("impact.rec.download_md", lang),
            impact_markdown(ws, recommendations, lang, decisions=labels).encode("utf-8"),
            file_name="impact_report.md", mime="text/markdown", icon=":material/download:", width="stretch",
        )
        csv_col.download_button(
            t("impact.rec.download_csv", lang), impact_csv(recommendations, lang, decisions=labels).encode("utf-8"),
            file_name="impact_recommendations.csv", mime="text/csv", icon=":material/download:", width="stretch",
        )
    if not changed:
        return
    with st.expander(t("impact.decision.heading", lang), icon=":material/how_to_reg:", expanded=True):
        st.caption(t("impact.decision.hint", lang))
        pick = st.selectbox(
            t("impact.decision.pick", lang), [r.requirement_id for r in changed],
            format_func=lambda rid: f"{rid} — {labels[rid]}", key=f"impact_pick_{ws.document_hash}",
        )
        if pending[pick].position_based:
            st.warning(t("impact.decision.position_note", lang), icon="⚠️")
        comment_key = f"impact_comment_{ws.document_hash}"
        st.text_input(t("impact.decision.comment", lang), key=comment_key)
        for col, decision in zip(st.columns(3), (Decision.ACCEPTED, Decision.REJECTED, Decision.DEFERRED),
                                 strict=True):
            col.button(
                t(f"impact.decision.{_BUTTON_KEYS[decision]}", lang),
                key=f"impact_{decision.value}_{ws.document_hash}", width="stretch",
                on_click=_record_decision, args=(store, project_id, lang, pending[pick], decision, comment_key),
            )


def _change_impact_note(p: Page, ws: Workspace) -> None:
    lang = p.lang
    """Differences from the previous version and the test cases there that need review."""
    impact = ws.change_impact
    if impact is None:
        return
    if impact.status == "unknown":
        st.warning(t("impact.unknown_previous", lang, title=escape_markdown(impact.previous_title)), icon="❓")
        return
    previous = t("impact.previous", lang, title=escape_markdown(impact.previous_title),
                 date=impact.previous_created_at[:16].replace("T", " "))
    if not impact.changes:
        st.info(t("impact.no_changes", lang, previous=previous), icon="✅")
        return
    counts = {kind: sum(c.kind == kind for c in impact.changes) for kind in ("added", "modified", "removed", "unknown")}
    lines = [t("impact.heading", lang, previous=previous, **counts)]
    if impact.test_cases:
        lines += ["", t("impact.review_heading", lang)]
        lines += [
            f"- {t('impact.previous_ids', lang, ids=tc.test_case_id)}, {t(f'review.{tc.review_status.value}', lang)}"
            f" — {t('impact.previous_ids', lang, ids=tc.requirement_id)}: {t(f'impact.reason.{tc.reason}', lang)}"
            for tc in impact.test_cases
        ]
        lines += ["", t("impact.statuses_kept", lang)]
    st.warning("\n".join(lines), icon="🔀")
    _recommendations_block(p, ws, impact)
    with st.expander(t("impact.changes_heading", lang, count=len(impact.changes)), icon=":material/difference:"):
        show_table([
            {
                t("impact.column.change", lang): t(f"impact.kind.{c.kind}", lang)
                + (f" ({t('impact.similarity', lang, percent=round(c.similarity * 100))})" if c.similarity else ""),
                t("impact.column.old", lang): f"{c.old_id}: {c.old_text}" if c.old_id else "—",
                t("impact.column.new", lang): f"{c.new_id}: {c.new_text}" if c.new_id else "—",
            }
            for c in impact.changes
        ])


def analysis(p: Page) -> None:
    lang = p.lang
    if (ws := _workspace(p, "analysis")) is None:
        return
    _restored_note(lang)
    _change_impact_note(p, ws)
    result = ws.analysis
    scores = score_all(ws.requirements, ws.findings)
    statuses = {req.id: result.status_of(req.id) for req in result.requirements}
    open_findings = [f for f in result.findings if f.status == ClarificationStatus.NEEDS_CLARIFICATION]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(t("results.requirements_count", lang), len(result.requirements), border=True)
    col2.metric(t("results.findings_count", lang), len(result.findings), border=True)
    col3.metric(
        t("results.needs_clarification_count", lang),
        sum(status == "needs_clarification" for status in statuses.values()),
        border=True,
    )
    overall = average_score(scores.values())
    col4.metric(t("dash.avg_quality", lang), "—" if overall is None else overall, border=True)

    left, right = st.columns([3, 2], gap="medium")
    with left:
        theme_ui.quality_card(lang, list(scores.values()), "analysis_quality")
    with right, theme_ui.card("severity"):
        theme_ui.section(t("ui.analysis.open_by_severity", lang), ":material/report:")
        counts = {s.value: sum(f.severity == s for f in open_findings) for s in reversed(list(Severity))}
        theme_ui.badges(*(
            theme_ui.badge(f"{t(f'severity.{k}', lang)}: {v}", SEVERITY_TONES[k]) for k, v in counts.items()
        ))
        st.caption(t("ui.analysis.grill_hint", lang))
        st.button(
            t("ui.analysis.launch_grill", lang), key="analysis_launch_grill", icon=":material/forum:",
            type="primary", width="stretch", on_click=shell_ui.nav_callback, args=("grill",),
        )

    tab_requirements, tab_findings, tab_gaps, tab_design, tab_defects, tab_ai = st.tabs([
        t("results.tab_requirements", lang), t("results.tab_findings", lang), t("tab.gaps", lang),
        t("tab.design", lang), t("tab.defects", lang), t("tab.ai", lang),
    ])
    with tab_requirements:
        _requirements_tab(lang, ws, scores, statuses)
    with tab_findings:
        _findings_tab(lang, ws)
        _finding_changes(p, ws)
    with tab_gaps:
        _gaps_tab(lang, ws, scores)
    with tab_design:
        _design_tab(lang, ws)
    with tab_defects:
        _defects_tab(p, ws)
    with tab_ai:
        _ai_tab(p, ws)


def _gaps_tab(lang: str, ws: Workspace, scores: dict[str, QualityScore]) -> None:
    """Traceability gaps: requirements without test cases and test cases without a requirement."""
    gaps = traceability_gaps(build_rtm(ws, scores), ws)
    st.caption(t("gaps.explainer", lang))
    m = st.columns(3)
    m[0].metric(t("gaps.untested", lang), len(gaps.untested), border=True)
    m[1].metric(t("gaps.unknown", lang), len(gaps.unknown), border=True)
    m[2].metric(t("gaps.unlinked", lang), len(gaps.unlinked), border=True)
    if not (gaps.gaps or gaps.unknown):
        st.success(t("gaps.none", lang), icon=":material/link:")
        return
    if gaps.untested:
        st.warning("\n".join([t("gaps.untested_heading", lang),
                              *(f"- {escape_markdown(_req_label(ws, r))}" for r in gaps.untested)]))
    if gaps.unknown:
        st.info("\n".join([t("gaps.unknown_heading", lang),
                           *(f"- {escape_markdown(_req_label(ws, r))}" for r in gaps.unknown)]), icon="❓")
    if gaps.unlinked:
        cases = {tc.id: tc for tc in ws.test_cases}
        st.warning("\n".join([t("gaps.unlinked_heading", lang), *(
            f"- {escape_markdown(f'{i} · {cases[i].title} — ')}"
            f"{t('gaps.not_in_document', lang, req=escape_markdown(cases[i].requirement_id))}"
            for i in gaps.unlinked
        )]))


def _requirements_tab(lang: str, ws: Workspace, scores: dict[str, QualityScore], statuses: dict) -> None:
    show_table(
        [
            {
                t("column.id", lang): req.id,
                t("column.requirement", lang): req.text,
                t("column.language", lang): t(f"language.{req.language.value}", lang),
                t("column.status", lang): (
                    f"{STATUS_BADGES[statuses[req.id].value]} "
                    f"{t(f'status.{statuses[req.id].value}', lang)}"
                ),
                t("column.quality", lang): scores[req.id].score,
            }
            for req in ws.analysis.requirements
        ],
    )
    with st.expander(t("quality.heading", lang), icon=":material/grading:"):
        st.caption(t("quality.explainer", lang))
        quality_req = st.selectbox(
            t("quality.select", lang), [r.id for r in ws.requirements],
            format_func=lambda v: _req_label(ws, v), key="quality_req",
        )
        score = scores[quality_req]
        st.markdown(
            f"**{t('column.quality', lang)}: {score.score}/100** · "
            f"{GRADE_BADGES[score.grade]} {t(f'grade.{score.grade}', lang)}"
        )
        show_table(
            [
                {
                    t("quality.criterion", lang): t(f"criterion.{c.key}", lang),
                    t("quality.points", lang): f"{c.points}/{c.max_points}",
                    t("quality.rule", lang): t(f"criterion.{c.key}.rule", lang),
                    t("quality.evidence", lang): ", ".join(c.evidence) if c.evidence else "—",
                }
                for c in score.criteria
            ]
        )


def _duplicates_block(lang: str, ws: Workspace) -> None:
    """Requirements that may repeat each other: a question for the BA/PO, not a finding (scores do not change)."""
    pairs = find_duplicates(ws.requirements)
    if not pairs:
        return
    lines = [t("dups.heading", lang)]
    for pair in pairs:
        ids = {"first": escape_markdown(pair.first_id), "second": escape_markdown(pair.second_id)}
        if pair.exact:
            lines.append(f"- {t('dups.exact', lang, **ids)}")
        else:
            lines.append(f"- {t('dups.near', lang, percent=round(pair.similarity * 100), **ids)}")
    st.warning("\n".join(lines), icon=":material/content_copy:")


def _findings_tab(lang: str, ws: Workspace) -> None:
    result = ws.analysis
    st.caption(f":material/info: {t('results.rule_disclaimer', lang)}")
    _duplicates_block(lang, ws)
    if not result.findings:
        st.success(t("results.no_findings", lang))
        return
    show_table(
        [
            {
                t("column.id", lang): f.requirement_id,
                t("column.issue", lang): t(f"finding.{f.type.value}", lang),
                t("column.severity", lang): (
                    f"{SEVERITY_BADGES[f.severity.value]} {t(f'severity.{f.severity.value}', lang)}"
                ),
                t("column.source", lang): t(f"source.{f.source.value}", lang),
                t("column.matched", lang): ", ".join(f.matched_terms),
                t("column.question", lang): clarification_question(f, lang),
                t("column.status", lang): (
                    f"{STATUS_BADGES[f.status.value]} {t(f'status.{f.status.value}', lang)}"
                ),
            }
            for f in result.findings
        ],
    )


def _finding_label(lang: str, finding: Finding) -> str:
    related = f" ⟷ {', '.join(finding.related_requirement_ids)}" if finding.related_requirement_ids else ""
    terms = f" — {', '.join(finding.matched_terms)}" if finding.matched_terms else ""
    return f"{finding.requirement_id}{related} · {t(f'finding.{finding.type.value}', lang)}{terms}"


def _event_rows(lang: str, ws: Workspace, events: list[FindingEvent]) -> list[dict]:
    rows = []
    for event in reversed(events):
        finding = finding_status.finding_by_key(ws, event.finding_key)
        row = {
            t("findings.col_time", lang): event.at[:16].replace("T", " ") if event.at else "—",
            t("findings.col_change", lang): t(f"findings.change.{event.change.value}", lang),
            t("findings.col_finding", lang): _finding_label(lang, finding) if finding else event.finding_key,
            t("findings.col_via", lang): t(f"findings.via.{event.via}", lang)
            + (f" ({event.grill_session_id[:8]})" if event.grill_session_id else ""),
            t("findings.col_reason", lang): event.reason or event.clarification or "—",
        }
        rows.append(row)
    return rows


def _on_reopen(p: Page, select_key: str, reason_key: str) -> None:
    ws: Workspace | None = st.session_state.get(WORKSPACE)
    key = st.session_state.get(select_key)
    if ws is None or not key:
        return
    try:
        p.persist(finding_status.reopen(ws, key, reason=str(st.session_state.get(reason_key) or "")))
    except finding_status.FindingError as exc:
        flash(t(f"findings.error.{exc.code}", p.lang), icon="⚠️")
        return
    st.session_state[reason_key] = ""
    flash(t("findings.reopened", p.lang))


def _on_undo(p: Page, reason_key: str) -> None:
    ws: Workspace | None = st.session_state.get(WORKSPACE)
    if ws is None:
        return
    try:
        p.persist(finding_status.undo_last(ws, reason=str(st.session_state.get(reason_key) or "")))
    except finding_status.FindingError as exc:
        flash(t(f"findings.error.{exc.code}", p.lang), icon="⚠️")
        return
    st.session_state[reason_key] = ""
    flash(t("findings.undone", p.lang))


def _finding_changes(p: Page, ws: Workspace) -> None:
    """Reopen a resolved finding, undo the last change, and see every change with its reason."""
    lang = p.lang
    resolved = finding_status.resolved_findings(ws)
    last = finding_status.last_change(ws)
    with theme_ui.card("finding_changes"):
        theme_ui.section(t("findings.heading", lang, count=len(resolved)), ":material/rule_settings:",
                         t("findings.explainer", lang))
        reason_key = "finding_reason"
        if resolved:
            options = {f.key: f for f in resolved}
            select_key = "finding_reopen_select"
            st.selectbox(t("findings.select", lang), list(options), key=select_key,
                         format_func=lambda k: _finding_label(lang, options[k]))
            chosen = st.session_state.get(select_key)
            if chosen in options and not finding_status.history(ws, chosen):
                st.caption(t("findings.no_history", lang))
        else:
            st.caption(t("findings.none_resolved", lang))
        if resolved or last:
            st.text_input(t("findings.reason_label", lang), key=reason_key, max_chars=MAX_REASON_LENGTH,
                          placeholder=t("findings.reason_placeholder", lang))
        with st.container(horizontal=True, key="finding_actions"):
            st.button(
                t("findings.reopen", lang), key="finding_reopen", icon=":material/undo:", disabled=not resolved,
                on_click=_on_reopen, args=(p, "finding_reopen_select", reason_key), help=t("findings.reopen_help", lang),
            )
            undo_help = t("findings.undo_none", lang)
            if last:
                undo_help = t("findings.undo_help", lang, change=t(f"findings.change.{last[-1].change.value}", lang),
                              count=len(last))
            st.button(
                t("findings.undo", lang), key="finding_undo", icon=":material/history:", disabled=not last,
                on_click=_on_undo, args=(p, reason_key), help=undo_help,
            )
        if last:
            st.caption(undo_help)
        if ws.finding_history:
            with st.expander(t("findings.history_heading", lang, count=len(ws.finding_history)), icon=":material/history:"):
                show_table(_event_rows(lang, ws, ws.finding_history))


def _design_tab(lang: str, ws: Workspace) -> None:
    st.caption(t("design.explainer", lang))
    design_req = st.selectbox(
        t("quality.select", lang), [r.id for r in ws.requirements],
        format_func=lambda v: _req_label(ws, v), key="design_req",
    )
    req = next(r for r in ws.requirements if r.id == design_req)
    design = design_tests(req)
    if design.is_empty:
        st.info(t("design.not_applicable", lang))
    for boundary in design.boundaries:
        st.markdown(f"**{t('design.bva', lang)}** — “{escape_markdown(boundary.constraint.phrase)}”")
        show_table(
            [
                {
                    t("design.value", lang): (
                        f"{format_value(v.value)} {unit_for(boundary.constraint.unit, format_value(v.value), lang)}"
                    ),
                    t("design.expectation", lang): t(f"design.{v.expectation}", lang),
                }
                for v in boundary.values
            ]
        )
        _partial_check_warning(lang, req, design, boundary.constraint.phrase)
    for classes in design.partitions:
        st.markdown(f"**{t('design.ep', lang)}** — “{escape_markdown(classes.constraint.phrase)}”")
        show_table(
            [
                {
                    t("design.partition", lang): f"{part.interval} {unit_for(classes.constraint.unit, part.interval, lang)}",
                    t("design.representative", lang): format_value(part.representative),
                    t("design.expectation", lang): t(f"design.{part.expectation}", lang),
                }
                for part in classes.partitions
            ]
        )
        _partial_check_warning(lang, req, design, classes.constraint.phrase)
    if table := design.decision_table:
        st.markdown(f"**{t('design.dt', lang)}** ({t(f'design.connector_{table.connector}', lang)})")
        rows = []
        for index, rule in enumerate(table.rules, start=1):
            row = {t("design.rule", lang): f"R{index}"}
            for cond, value in zip(table.conditions, rule.values, strict=True):
                row[cond] = t(f"design.{str(value).lower()}", lang)
            row[t("design.outcome", lang)] = rule.outcome or f"⚠️ {t('design.unspecified', lang)}"
            rows.append(row)
        show_table(rows)
        if any(rule.outcome is None for rule in table.rules):
            st.warning(t("design.unspecified_warning", lang))


def _partial_check_warning(lang: str, req: Requirement, design: TestDesign, phrase: str) -> None:
    """Under values that vary one numeric limit: the requirement's other conditions they do not check,
    as the boundary and equivalence test cases note it (tc.assumption_partial_check)."""
    if not is_partial_check(req.text, design):
        return
    if conditions := other_conditions(req.text, design):
        quoted = ", ".join(t("design.quote", lang, text=c) for c in conditions)
        text = t("design.partial_check", lang, phrase=phrase, req=req.id, conditions=quoted)
    else:
        text = t("design.partial_check_unnamed", lang, phrase=phrase, req=req.id)
    st.warning(escape_markdown(text), icon=":material/rule:")


def _defects_tab(p: Page, ws: Workspace) -> None:
    lang = p.lang
    req_ids = [r.id for r in ws.requirements]
    st.caption(t("bugs.explainer", lang))
    if st.button(t("bugs.generate", lang), icon=":material/bug_report:", key="bug_generate"):
        created_bugs = generate_defects(ws, lang)
        ws.defects.extend(created_bugs)
        p.persist(ws)
        flash(t("bugs.generated", lang, count=len(created_bugs)))
        st.rerun()
    if not ws.defects:
        st.info(t("bugs.none", lang))
        return
    show_table(
        [
            {
                t("column.bug_id", lang): d.id,
                t("column.id", lang): d.requirement_id,
                t("column.title", lang): d.title,
                t("column.severity", lang): (
                    f"{SEVERITY_BADGES[d.severity.value]} {t(f'severity.{d.severity.value}', lang)}"
                ),
                t("column.source", lang): t(f"source.{d.source.value}", lang),
            }
            for d in ws.defects
        ],
    )
    bug_ids = [d.id for d in ws.defects]
    if st.session_state.get("bug_selected") not in bug_ids:
        st.session_state["bug_selected"] = bug_ids[0]
    bug_titles = {d.id: d.title for d in ws.defects}
    bug_id = st.selectbox(
        t("bugs.select", lang), bug_ids, format_func=lambda i: f"{i} — {bug_titles[i]}", key="bug_selected"
    )
    bug = next(d for d in ws.defects if d.id == bug_id)
    with st.form(key=f"bug_form_{bug.id}"):
        bug_title = st.text_input(t("column.title", lang), bug.title)
        g1, g2 = st.columns(2)
        severities = list(Severity)
        bug_severity = g1.selectbox(
            t("column.severity", lang), severities, index=severities.index(bug.severity),
            format_func=lambda v: t(f"severity.{v.value}", lang),
        )
        bug_req = g2.selectbox(
            t("column.id", lang), req_ids,
            index=req_ids.index(bug.requirement_id) if bug.requirement_id in req_ids else 0,
        )
        bug_description = st.text_area(t("bugs.description", lang), bug.description)
        bug_expected = st.text_area(t("bugs.expected", lang), bug.expected_behavior)
        bug_context = st.text_area(t("bugs.context", lang), bug.reproduction_context, height=150)
        bug_saved = st.form_submit_button(t("action.save", lang), type="primary")
    if bug_saved:
        if not bug_title.strip():
            st.error(t("bugs.validation", lang))
        else:
            updated_bug = bug.model_copy(
                update={
                    "title": bug_title.strip(),
                    "severity": bug_severity,
                    "requirement_id": bug_req,
                    "description": bug_description.strip(),
                    "expected_behavior": bug_expected.strip(),
                    "reproduction_context": bug_context.strip(),
                }
            )
            ws.defects = [updated_bug if d.id == bug.id else d for d in ws.defects]
            p.persist(ws)
            flash(t("action.saved", lang, id=bug.id))
            st.rerun()
    e1, e2 = st.columns([1, 3])
    bug_confirm = e2.checkbox(t("action.confirm_delete", lang, id=bug.id), key=f"bug_confirm_{bug.id}")
    if e1.button(t("action.delete", lang), icon=":material/delete:", disabled=not bug_confirm, key=f"bug_delete_{bug.id}"):
        ws.defects = [d for d in ws.defects if d.id != bug.id]
        p.persist(ws)
        st.session_state.pop("bug_selected", None)
        flash(t("action.deleted", lang, id=bug.id), icon="🗑️")
        st.rerun()


def _ai_tab(p: Page, ws: Workspace) -> None:
    lang, ai_config = p.lang, p.ai_config
    st.caption(t("ai.explainer", lang))
    if ai_config is None:
        st.info(t("ai.not_configured", lang), icon="🔌")
    else:
        st.markdown(
            t("ai.configured", lang, provider=ai_config.provider_name, model=escape_markdown(ai_config.model))
        )
        if st.session_state.pop("ai_consent_reset", False):
            st.session_state["ai_consent"] = False
        consent = st.checkbox(
            t("ai.consent", lang, provider=ai_config.provider_name, count=len(ws.requirements)), key="ai_consent"
        )
        if st.button(t("ai.run", lang), icon=":material/psychology:", disabled=not consent, key="ai_run"):
            st.session_state["ai_consent_reset"] = True  # ask again before the next run
            try:
                with st.spinner(t("ai.running", lang)):
                    suggestions = ai_analysis.run_ai_analysis(ws.requirements, ai_config, consent=consent, lang=lang)
                ws.ai_suggestions = suggestions
                ws.ai_model = ai_config.model
                p.persist(ws)
                flash(t("ai.done", lang, count=len(suggestions)))
                st.rerun()
            except AIError as error:
                st.error(t(f"ai.error.{error.code}", lang))
    if not ws.ai_suggestions:
        return
    st.warning(t("ai.disclaimer", lang, model=ws.ai_model or "AI"), icon="🤖")
    show_table(
        [
            {
                t("column.ai_id", lang): s.id,
                t("column.id", lang): ", ".join(s.requirement_ids),
                t("column.issue", lang): t(f"ai_type.{s.type.value}", lang),
                t("column.description", lang): s.description,
                t("column.quote", lang): (
                    f"{'✅' if s.quote_verified else '⚠️'} “{s.quote}”" if s.quote else "—"
                ),
                t("column.question", lang): s.question,
                t("column.source", lang): t("source.ai", lang),
            }
            for s in ws.ai_suggestions
        ],
    )
    st.caption(t("ai.quote_legend", lang))
    suggestion_ids = [s.id for s in ws.ai_suggestions]
    chosen = st.selectbox(t("ai.select", lang), suggestion_ids, key="ai_selected")
    if st.button(t("ai.to_bug", lang), icon=":material/bug_report:", key="ai_to_bug"):
        suggestion = next(s for s in ws.ai_suggestions if s.id == chosen)
        if any(d.origin_key == f"ai|{suggestion.id}" for d in ws.defects):
            st.info(t("ai.bug_exists", lang))
        else:
            report: DefectReport = defect_from_suggestion(suggestion, ws, next_defect_id(ws.defects), lang)
            ws.defects.append(report)
            p.persist(ws)
            flash(t("bugs.generated", lang, count=1))
            st.rerun()


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def tests(p: Page) -> None:
    lang = p.lang
    if (ws := _workspace(p, "tests")) is None:
        return
    counts = {s.value: sum(tc.review_status == s for tc in ws.test_cases) for s in ReviewStatus}
    m = st.columns(4)
    m[0].metric(t("dash.test_cases", lang), len(ws.test_cases), border=True)
    for col, status in zip(m[1:], ReviewStatus, strict=True):
        col.metric(t(f"review.{status.value}", lang), counts[status.value], border=True)
    tab_tests, tab_suites, tab_runs, tab_automation = st.tabs([
        t("tab.tests", lang), t("tab.suites", lang), t("tab.runs", lang), t("tab.automation", lang),
    ])
    with tab_tests:
        _test_case_editor(p, ws)
    with tab_suites:
        _suites_tab(lang, ws)
    with tab_runs:
        runs_ui.render_runs(lang, ws, active_project_id(), open_run_store(st.session_state))
    with tab_automation:
        automation_ui.render_automation(lang, ws, p.automation_ai, p.persist)


def _suites_tab(lang: str, ws: Workspace) -> None:
    """Smoke / Regression / Full suites picked from the existing test cases."""
    st.caption(t("suites.explainer", lang))
    if not ws.test_cases:
        st.info(t("suites.no_test_cases", lang))
        return
    plan = plan_suites(ws)
    m = st.columns(len(SuiteKind))
    for col, kind in zip(m, SuiteKind, strict=True):
        col.metric(t(f"suites.{kind.value}", lang), len(plan.suites[kind]), border=True)
    st.info(t("suites.no_criticality", lang), icon=":material/help:")
    if plan.smoke_missing:
        st.warning(t("suites.smoke_missing", lang, ids=", ".join(plan.smoke_missing)))
    kind = st.selectbox(t("suites.select", lang), list(SuiteKind), key="suite_kind",
                        format_func=lambda k: t(f"suites.{k.value}", lang)) or SuiteKind.SMOKE
    st.caption(t(f"suites.criteria.{kind.value}", lang))
    selected = set(plan.suites[kind])
    cases = [tc for tc in ws.test_cases if tc.id in selected]
    if not cases:
        st.info(t("suites.empty", lang))
        return
    show_table([
        {
            t("column.test_id", lang): tc.id,
            t("column.id", lang): tc.requirement_id,
            t("column.title", lang): tc.title,
            t("column.test_type", lang): t(f"test_type.{tc.test_type.value}", lang),
            t("column.priority", lang): t(f"priority.{tc.priority.value}", lang),
            t("column.review", lang): t(f"review.{tc.review_status.value}", lang),
        }
        for tc in cases
    ])
    suite = suite_workspace(ws, kind)
    name = t(f"suites.{kind.value}", lang)
    e1, e2 = st.columns(2)
    e1.download_button(
        t("suites.export_jira", lang, suite=name),
        jira_test_cases_csv(suite, False, DEFAULT_JIRA_TEST_ISSUE_TYPE).encode("utf-8"),
        file_name=f"jira_{kind.value}_suite.csv", mime="text/csv", icon=":material/download:", width="stretch",
    )
    e2.download_button(
        t("suites.export_testrail", lang, suite=name),
        testrail_csv(suite, False).encode("utf-8"),
        file_name=f"testrail_{kind.value}_suite.csv", mime="text/csv", icon=":material/download:", width="stretch",
    )


# ---------------------------------------------------------------------------
# QA Agent
# ---------------------------------------------------------------------------

def qa_agent(p: Page) -> None:
    project_id = active_project_id()
    docs = qa_auto_ui.Documents(
        load=lambda doc_hash: p.store.load(project_id, doc_hash),
        persist=p.persist,
        remember=lambda doc_hash: remember_document(project_id, doc_hash),
    )
    qa_agent_ui.render_qa_agent(
        p.lang, st.session_state.get(WORKSPACE), p.ai_config, docs, no_document=lambda: _workspace(p, "qa_agent"),
        previous_impact=lambda ws: change_impact(
            ws, p.store.documents(project_id), lambda h: p.store.load(project_id, h),
        ),
    )


# ---------------------------------------------------------------------------
# Bug Reports (product bugs of the project; no document needed)
# ---------------------------------------------------------------------------

def bug_reports(p: Page) -> None:
    project_id = active_project_id()
    active = next((pr for pr in p.store.projects() if pr.id == project_id), None)
    bug_reports_ui.render_bug_reports(
        p.lang, project_id, project_name(active, p.lang) if active else "", open_bug_report_store(st.session_state),
    )


def _risk_of(ws: Workspace, requirement_id: str) -> Severity | None:
    """Highest severity among the requirement's open findings."""
    open_severities = {
        f.severity for f in ws.findings
        if f.requirement_id == requirement_id and f.status == ClarificationStatus.NEEDS_CLARIFICATION
    }
    return next((s for s in (Severity.HIGH, Severity.MEDIUM, Severity.LOW) if s in open_severities), None)


def _run_case_ids(ws: Workspace) -> set[str]:
    """Test case IDs that runs of this document refer to: a new test case must not take one of them."""
    return case_ids_in_runs(open_run_store(st.session_state).runs(active_project_id()), ws.document_hash)


BULK_KEY = "tc_bulk_select"  # the test cases chosen for bulk actions (session state)
BULK_CONFIRM = "tc_bulk_confirm"  # the delete confirmation (session state)


def _bulk_set_status(p: Page, ws: Workspace, status: ReviewStatus) -> None:
    """Set the review status of the chosen test cases. A callback: it runs before the page is drawn."""
    changed = set_review_status(ws, st.session_state.get(BULK_KEY, []), status)
    p.persist(ws)
    st.session_state[BULK_KEY] = []
    flash(t("tests.bulk.changed", p.lang, count=changed, status=t(f"review.{status.value}", p.lang)))


def _bulk_delete(p: Page, ws: Workspace) -> None:
    """Delete the chosen test cases. Only enabled after the confirmation; a callback like the one above."""
    removed = delete_cases(ws, st.session_state.get(BULK_KEY, []))
    p.persist(ws)
    st.session_state[BULK_KEY] = []
    st.session_state[BULK_CONFIRM] = False
    st.session_state.pop("tc_selected", None)
    flash(t("tests.bulk.deleted", p.lang, count=removed), icon="🗑️")


def _bulk_actions(p: Page, ws: Workspace, cases: list[TestCase]) -> None:
    """Bulk actions on the chosen test cases: a review status for all of them, or delete after a confirmation."""
    lang = p.lang
    titles = {tc.id: tc.title for tc in cases}
    with st.expander(t("tests.bulk.heading", lang), icon=":material/checklist:"):
        # Drop choices the search or filter has hidden before the widget is drawn again.
        if BULK_KEY in st.session_state:
            st.session_state[BULK_KEY] = [i for i in st.session_state[BULK_KEY] if i in titles]
        chosen = st.multiselect(t("tests.bulk.select", lang), list(titles), key=BULK_KEY,
                                format_func=lambda i: f"{i} — {titles[i]}")
        if not chosen:
            st.caption(t("tests.bulk.hint", lang))
            return
        for col, status in zip(st.columns(len(ReviewStatus)), ReviewStatus, strict=True):
            col.button(t("tests.bulk.set", lang, status=t(f"review.{status.value}", lang)),
                       key=f"tc_bulk_{status.value}", width="stretch",
                       on_click=_bulk_set_status, args=(p, ws, status))
        st.caption(t("tests.bulk.approve_note", lang))
        st.checkbox(t("tests.bulk.confirm_delete", lang, count=len(chosen)), key=BULK_CONFIRM)
        st.button(t("tests.bulk.delete", lang), icon=":material/delete:", key="tc_bulk_delete",
                  disabled=not st.session_state.get(BULK_CONFIRM), on_click=_bulk_delete, args=(p, ws))


def _test_case_editor(p: Page, ws: Workspace) -> None:
    lang = p.lang
    req_ids = [r.id for r in ws.requirements]
    st.caption(t("tests.explainer", lang))
    tc_filter = st.selectbox(
        t("tests.filter_requirement", lang), [ALL, *req_ids],
        format_func=lambda v: t("filter.all", lang) if v == ALL else _req_label(ws, v),
        key="tc_filter",
    )
    cases = [tc for tc in ws.test_cases if tc_filter == ALL or tc.requirement_id == tc_filter]
    search_col, status_col = st.columns([3, 2], gap="medium")
    query = search_col.text_input(t("tests.search", lang), key="tc_search")
    statuses = status_col.multiselect(
        t("tests.filter_status", lang), list(ReviewStatus), key="tc_status_filter",
        format_func=lambda v: t(f"review.{v.value}", lang),
    )
    cases = filter_cases(cases, query, set(statuses))
    filtered = bool(query.strip() or statuses)
    scores = {tc.id: score_test_case(tc, ws) for tc in ws.test_cases}

    b1, b2 = st.columns(2)
    if b1.button(t("tests.add", lang), icon=":material/add:", key="tc_add", width="stretch"):
        target = tc_filter if tc_filter != ALL else req_ids[0]
        new_case = TestCase(
            id=next_test_case_id(ws.test_cases, reserved=_run_case_ids(ws)),
            requirement_id=target,
            title=t("tests.new_title", lang),
            test_type=TestType.POSITIVE,
            steps=[t("tests.new_step", lang)],
            expected_result=t("tests.new_expected", lang),
        )
        ws.test_cases.append(new_case)
        p.persist(ws)
        st.session_state["tc_selected"] = new_case.id
        st.rerun()
    if b2.button(t("tests.generate_missing", lang), icon=":material/auto_awesome:", key="tc_generate", width="stretch"):
        missing = [req for req in ws.requirements if not ws.tests_for(req.id)]
        scratch = Workspace(requirements=missing, findings=ws.findings, test_cases=ws.test_cases)
        created = generate_test_cases(scratch, lang, reserved=_run_case_ids(ws))
        ws.test_cases.extend(created)
        p.persist(ws)
        flash(t("tests.generated", lang, count=len(created)))
        st.rerun()

    if not cases:
        st.info(t("tests.bulk.none" if filtered else "tests.none", lang))
        return
    show_table(
        [
            {
                t("column.test_id", lang): tc.id,
                t("column.id", lang): tc.requirement_id,
                t("column.title", lang): tc.title,
                t("column.test_type", lang): t(f"test_type.{tc.test_type.value}", lang),
                t("column.priority", lang): t(f"priority.{tc.priority.value}", lang),
                t("column.review", lang): (
                    f"{REVIEW_BADGES[tc.review_status.value]} {t(f'review.{tc.review_status.value}', lang)}"
                ),
                t("column.quality", lang): scores[tc.id].score,
            }
            for tc in cases
        ],
    )
    _bulk_actions(p, ws, cases)
    case_ids = [tc.id for tc in cases]
    if st.session_state.get("tc_selected") not in case_ids:
        st.session_state["tc_selected"] = case_ids[0]
    titles = {tc.id: tc.title for tc in cases}
    selected_id = st.selectbox(
        t("tests.select", lang), case_ids, format_func=lambda i: f"{i} — {titles[i]}", key="tc_selected",
    )
    tc = next(c for c in ws.test_cases if c.id == selected_id)
    _test_case_detail(lang, ws, tc)
    _approval_check(lang, ws, tc, scores[tc.id])
    if tc.clarification_questions:
        st.warning(
            t("tests.open_questions", lang)
            + "\n\n"
            + "\n".join(f"- {escape_markdown(q)}" for q in tc.clarification_questions)
        )
    with st.expander(t("ui.tests.edit", lang, id=tc.id), icon=":material/edit:"), st.form(key=f"tc_form_{tc.id}"):
        title = st.text_input(t("column.title", lang), value=tc.title)
        fc1, fc2, fc3 = st.columns(3)
        requirement_id = fc1.selectbox(
            t("column.id", lang), req_ids,
            index=req_ids.index(tc.requirement_id) if tc.requirement_id in req_ids else 0,
        )
        types = list(TestType)
        test_type = fc2.selectbox(
            t("column.test_type", lang), types, index=types.index(tc.test_type),
            format_func=lambda v: t(f"test_type.{v.value}", lang),
        )
        statuses_list = list(ReviewStatus)
        review_status = fc3.selectbox(
            t("column.review", lang), statuses_list, index=statuses_list.index(tc.review_status),
            format_func=lambda v: t(f"review.{v.value}", lang),
        )
        priorities = list(TestPriority)
        priority = st.selectbox(
            t("column.priority", lang), priorities, index=priorities.index(tc.priority),
            format_func=lambda v: t(f"priority.{v.value}", lang),
        )
        preconditions = st.text_area(t("tests.preconditions", lang), "\n".join(tc.preconditions))
        steps = st.text_area(t("tests.steps", lang), "\n".join(tc.steps))
        expected = st.text_area(t("tests.expected", lang), tc.expected_result)
        assumptions = st.text_area(t("tests.assumptions", lang), "\n".join(tc.assumptions))
        comment = st.text_input(t("tests.comment", lang), tc.reviewer_comment)
        saved_form = st.form_submit_button(t("action.save", lang), type="primary")
    if saved_form:
        if not title.strip() or not lines(steps) or not expected.strip():
            st.error(t("tests.validation", lang))
        else:
            updated = tc.model_copy(
                update={
                    "title": title.strip(),
                    "requirement_id": requirement_id,
                    "test_type": test_type,
                    "review_status": review_status,
                    "priority": priority,
                    "preconditions": lines(preconditions),
                    "steps": lines(steps),
                    "expected_result": expected.strip(),
                    "assumptions": lines(assumptions),
                    "reviewer_comment": comment.strip(),
                }
            )
            ws.test_cases = [updated if c.id == tc.id else c for c in ws.test_cases]
            p.persist(ws)
            flash(t("action.saved", lang, id=tc.id))
            st.rerun()
    d1, d2 = st.columns([1, 3])
    confirm = d2.checkbox(t("action.confirm_delete", lang, id=tc.id), key=f"tc_confirm_{tc.id}")
    if d1.button(t("action.delete", lang), icon=":material/delete:", disabled=not confirm, key=f"tc_delete_{tc.id}"):
        ws.test_cases = [c for c in ws.test_cases if c.id != tc.id]
        p.persist(ws)
        st.session_state.pop("tc_selected", None)
        flash(t("action.deleted", lang, id=tc.id), icon="🗑️")
        st.rerun()


def _approval_check(lang: str, ws: Workspace, tc: TestCase, score: TestCaseScore) -> None:
    """Quality score, critic findings and missing scenarios to weigh before approving; never blocks the decision."""
    req = ws.requirement(tc.requirement_id)
    coverage = scenario_coverage(req, ws.tests_for(req.id)) if req else None

    def scenarios(categories: list[ScenarioCategory]) -> str:
        return ", ".join(t(f"scenario.{c.value}", lang) for c in categories)

    def issue_line(issue: CriticIssue, cost: str = "") -> str:
        return (f"- **{t(f'critic.criterion.{issue.criterion}', lang)}**{cost}: "
                f"{escape_markdown(t(f'critic.{issue.code}', lang, **issue.params))}")

    approved = tc.review_status == ReviewStatus.APPROVED
    lines = [f"**{t('approval.review_heading' if approved else 'approval.heading', lang, id=tc.id)}**", "",
             f"{t('tc_score.line', lang, score=score.score, grade=t(f'grade.{score.grade}', lang))}",
             f"_{t('tc_score.explain', lang)}_"]
    if score.deductions:
        lines += ["", t("approval.critic_problems", lang),
                  *(issue_line(d, f" (−{d.points})") for d in score.deductions)]
    if score.unknown:
        lines += ["", t("approval.critic_unknown", lang), *(issue_line(i) for i in score.unknown)]
    missing = coverage.missing if coverage else []
    if coverage is not None:
        lines.append("")
        if coverage.percent is None:
            lines.append(t("approval.coverage_unknown", lang, req=tc.requirement_id))
        else:
            lines.append(t("approval.coverage", lang, req=tc.requirement_id, percent=f"{coverage.percent:g}"))
        if missing:
            lines.append(t("approval.missing", lang, names=scenarios(missing)))
            if not approved and req is not None and (
                would := [c for c in missing if c in categories_of_test_case(tc, req)]
            ):
                lines.append(t("approval.would_cover", lang, names=scenarios(would)))
        if coverage.unknown:
            lines.append(t("approval.scenario_unknown", lang, names=scenarios(coverage.unknown)))
    lines += ["", f"_{t('approval.review_note' if approved else 'approval.not_blocked', lang)}_"]
    if score.deductions or missing:
        st.warning("\n".join(lines), icon=":material/rule:")
    else:
        st.info("\n".join(lines), icon=":material/rule:")


def _test_case_detail(lang: str, ws: Workspace, tc: TestCase) -> None:
    """Read view of one test case: what a tester needs before running it."""
    with theme_ui.card("test_case"):
        st.markdown(f"#### {escape_markdown(tc.id)} · {escape_markdown(tc.title)}")
        risk = _risk_of(ws, tc.requirement_id)
        theme_ui.badges(
            theme_ui.badge(t(f"review.{tc.review_status.value}", lang), REVIEW_TONES[tc.review_status.value]),
            theme_ui.badge(t(f"test_type.{tc.test_type.value}", lang), "accent"),
            theme_ui.badge(f"{t('column.priority', lang)}: {t(f'priority.{tc.priority.value}', lang)}", "neutral"),
            theme_ui.badge(tc.requirement_id, "info", ":material/link:"),
            theme_ui.badge(t("ui.tests.risk", lang, level=t(f"severity.{risk.value}", lang)),
                           SEVERITY_TONES[risk.value]) if risk else "",
            theme_ui.badge(t(f"source.{tc.source.value}", lang), "neutral"),
        )
        if req := ws.requirement(tc.requirement_id):
            st.caption(f"{escape_markdown(req.id)}: {escape_markdown(req.text)}")
        left, right = st.columns([1, 1], gap="medium")
        with left:
            st.markdown(f"**{t('grill.field.preconditions', lang)}**")
            st.markdown("\n".join(f"- {escape_markdown(x)}" for x in tc.preconditions) or "—")
            st.markdown(f"**{t('grill.field.steps', lang)}**")
            st.markdown("\n".join(f"{n}. {escape_markdown(x)}" for n, x in enumerate(tc.steps, start=1)))
        with right:
            st.markdown(f"**{t('grill.field.expected_result', lang)}**")
            st.markdown(escape_markdown(tc.expected_result))
            if tc.assumptions:
                st.markdown(f"**{t('grill.field.assumptions', lang)}**")
                st.markdown("\n".join(f"- {escape_markdown(x)}" for x in tc.assumptions))
            if tc.reviewer_comment:
                st.markdown(f"**{t('tests.comment', lang)}**")
                st.caption(escape_markdown(tc.reviewer_comment))


# ---------------------------------------------------------------------------
# RTM
# ---------------------------------------------------------------------------

def rtm(p: Page) -> None:
    lang = p.lang
    if (ws := _workspace(p, "rtm")) is None:
        return
    scores = score_all(ws.requirements, ws.findings)
    rows = build_rtm(ws, scores)
    summary = summarize(rows, ws)
    # Execution counts only recorded runs of this document; with none, it stays not tracked.
    doc_runs = [r for r in open_run_store(st.session_state).runs(active_project_id()) if r.document_hash == ws.document_hash]
    executed = executed_requirement_ids(doc_runs, ws.document_hash, {tc.id: tc.requirement_id for tc in ws.test_cases}) \
        if doc_runs else None
    levels = coverage_levels(rows, executed)
    # Status per requirement (Approved is a review result, not a run).
    for col, coverage in zip(st.columns(3), Coverage, strict=True):
        col.metric(
            f"{COVERAGE_BADGES[coverage.value]} {t(f'coverage.{coverage.value}', lang)}",
            summary.coverage_distribution[coverage.value], border=True,
        )
    # Design, Review and Execution are separate levels.
    design, review, execution = st.columns(3)
    design.metric(t("rtm.level.design", lang), f"{levels.design:g}%", border=True,
                  help=t("rtm.level.design_help", lang))
    review.metric(t("rtm.level.review", lang), f"{levels.review:g}%", border=True,
                  help=t("rtm.level.review_help", lang))
    execution.metric(
        t("rtm.level.execution", lang),
        t("rtm.level.not_tracked", lang) if levels.execution is None else f"{levels.execution:g}%",
        border=True, help=t("rtm.level.execution_help", lang),
    )
    with theme_ui.card("rtm"):
        st.caption(t("rtm.explainer", lang))
        show_table(_rtm_rows(lang, rows, {tc.id: score_test_case(tc, ws).score for tc in ws.test_cases}))
    if orphans := orphan_test_case_ids(ws):
        st.warning(t("rtm.orphans", lang, ids=", ".join(orphans)))


def _average_of(test_ids: list[str], scores: dict[str, int]) -> int | str:
    """Mean quality score of the given test cases; "—" when there are none to score."""
    values = [scores[i] for i in test_ids if i in scores]
    return round(sum(values) / len(values)) if values else "—"


def _rtm_rows(lang: str, rows: list[RTMRow], test_scores: dict[str, int]) -> list[dict]:
    return [
        {
            t("column.id", lang): row.requirement_id,
            t("column.requirement", lang): row.requirement_text,
            t("column.quality", lang): row.quality_score,
            t("column.test_quality", lang): _average_of(row.test_case_ids, test_scores),
            t("column.open_issues", lang): ", ".join(t(f"finding.{i}", lang) for i in row.open_issues) or "—",
            t("column.test_cases", lang): ", ".join(row.test_case_ids) or "—",
            t("column.approved", lang): ", ".join(row.approved_test_case_ids) or "—",
            t("column.bugs", lang): ", ".join(row.defect_ids) or "—",
            t("column.coverage", lang): (
                f"{COVERAGE_BADGES[row.coverage.value]} {t(f'coverage.{row.coverage.value}', lang)}"
            ),
            **_scenario_cells(lang, row),
        }
        for row in rows
    ]


def _scenario_cells(lang: str, row: RTMRow) -> dict:
    sc = row.scenarios
    if sc is None:
        return {}

    def names(categories: list) -> str:
        return ", ".join(t(f"scenario.{c.value}", lang) for c in categories) or "—"

    unknown = t("scenario.unknown", lang)
    reasons = [f"{t(f'scenario.{c.value}', lang)}: «{sc.reasons[c]}»" for c in sc.applicable]
    reasons += [
        f"{t(f'scenario.{c.value}', lang)}: {unknown}"
        f" ({f'«{sc.reasons[c]}»' if c in sc.reasons else t('scenario.no_behavior', lang)})"
        for c in sc.unknown
    ]
    return {
        t("column.scenarios_applicable", lang): names(sc.applicable) if sc.applicable else unknown,
        t("column.scenarios_covered", lang): names(sc.covered),
        t("column.scenarios_missing", lang): names(sc.missing),
        t("column.scenario_coverage", lang): unknown if sc.percent is None else f"{sc.percent:g}%",
        t("column.scenario_reason", lang): "; ".join(reasons) or "—",
        t("column.scenario_unchecked", lang): (
            ", ".join(t("design.quote", lang, text=c) for c in sc.unchecked_conditions) or "—"
        ),
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def dashboard(p: Page) -> None:
    lang = p.lang
    if (ws := _workspace(p, "dashboard")) is None:
        return
    scores = score_all(ws.requirements, ws.findings)
    rtm_rows = build_rtm(ws, scores)
    with theme_ui.card("filters"):
        f1, f2, f3, f4 = st.columns(4)
        sev_filter = f1.multiselect(
            t("filter.severity", lang), [s.value for s in Severity][::-1],
            format_func=lambda v: t(f"severity.{v}", lang), key="dash_severity",
        )
        cov_filter = f2.multiselect(
            t("filter.coverage", lang), [c.value for c in Coverage],
            format_func=lambda v: t(f"coverage.{v}", lang), key="dash_coverage",
        )
        grade_filter = f3.multiselect(
            t("filter.quality", lang), ["good", "fair", "poor"],
            format_func=lambda v: t(f"grade.{v}", lang), key="dash_grade",
        )
        search = f4.text_input(t("filter.search", lang), key="dash_search")
    filtered = filter_rows(rtm_rows, set(sev_filter), set(cov_filter), set(grade_filter), search)
    summary = summarize(filtered, ws)

    m = st.columns(5)
    m[0].metric(t("dash.requirements", lang), summary.requirements, border=True)
    m[1].metric(t("dash.open_issues", lang), summary.open_issues, border=True)
    m[2].metric(t("dash.test_cases", lang), summary.test_cases, border=True)
    m[3].metric(
        t("dash.coverage", lang), f"{summary.coverage_percent:g}%", border=True,
        help=t("dash.coverage_help", lang, any=f"{summary.any_test_percent:g}"),
    )
    m[4].metric(
        t("dash.avg_quality", lang),
        "—" if summary.average_quality is None else f"{summary.average_quality:g}",
        border=True,
    )
    if ws.ai_suggestions:
        st.caption(t("dash.ai_note", lang, count=len(ws.ai_suggestions)))

    c1, c2 = st.columns(2, gap="medium")
    with c1, theme_ui.card("chart_severity"):
        st.markdown(f"**{t('dash.severity_distribution', lang)}**")
        bar_chart({t(f"severity.{k}", lang): v for k, v in summary.severity_distribution.items()})
    with c2, theme_ui.card("chart_coverage"):
        st.markdown(f"**{t('dash.coverage_distribution', lang)}**")
        bar_chart({t(f"coverage.{k}", lang): v for k, v in summary.coverage_distribution.items()})
    c3, c4 = st.columns(2, gap="medium")
    with c3, theme_ui.card("chart_review"):
        st.markdown(f"**{t('dash.review_distribution', lang)}**")
        bar_chart({t(f"review.{k}", lang): v for k, v in summary.review_distribution.items()})
    with c4, theme_ui.card("chart_quality"):
        st.markdown(f"**{t('ui.dash.quality_distribution', lang)}**")
        grades = [row.quality_grade for row in filtered]
        bar_chart({t(f"grade.{g}", lang): grades.count(g) for g in ("good", "fair", "poor")})

    with theme_ui.card("unresolved"):
        theme_ui.section(t("ui.dash.unresolved", lang), ":material/pending_actions:")
        ids = {row.requirement_id for row in filtered}
        order = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
        unresolved = sorted(
            (f for f in ws.findings if f.requirement_id in ids and f.status == ClarificationStatus.NEEDS_CLARIFICATION),
            key=lambda f: order[f.severity],
        )
        if not unresolved:
            st.caption(t("ui.dash.no_unresolved", lang))
        else:
            show_table([
                {
                    t("column.id", lang): f.requirement_id,
                    t("column.issue", lang): t(f"finding.{f.type.value}", lang),
                    t("column.severity", lang): f"{SEVERITY_BADGES[f.severity.value]} {t(f'severity.{f.severity.value}', lang)}",
                    t("column.question", lang): clarification_question(f, lang),
                }
                for f in unresolved
            ])

    if filtered:
        with theme_ui.card("dash_requirements"):
            theme_ui.section(t("results.tab_requirements", lang), ":material/list_alt:")
            _dashboard_table(lang, filtered)
    else:
        st.info(t("dash.no_match", lang))


def _dashboard_table(lang: str, filtered: list[RTMRow]) -> None:
    if filtered:
        show_table(
            [
                {
                    t("column.id", lang): row.requirement_id,
                    t("column.requirement", lang): row.requirement_text,
                    t("column.quality", lang): row.quality_score,
                    t("column.open_issues", lang): len(row.open_issues),
                    t("column.severity", lang): (
                        f"{SEVERITY_BADGES[row.highest_severity.value]} "
                        f"{t(f'severity.{row.highest_severity.value}', lang)}"
                        if row.highest_severity else "—"
                    ),
                    t("column.coverage", lang): (
                        f"{COVERAGE_BADGES[row.coverage.value]} {t(f'coverage.{row.coverage.value}', lang)}"
                    ),
                }
                for row in filtered
            ],
        )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export(p: Page) -> None:
    lang = p.lang
    if (ws := _workspace(p, "export")) is None:
        return
    rtm_rows = build_rtm(ws, score_all(ws.requirements, ws.findings))
    with theme_ui.card("export_options"):
        st.caption(t("export.explainer", lang))
        o1, o2 = st.columns(2, gap="medium")
        only_approved = o1.checkbox(t("export.only_approved", lang), key="export_only_approved")
        issue_type = o2.text_input(
            t("export.jira_issue_type", lang), DEFAULT_JIRA_TEST_ISSUE_TYPE, key="export_issue_type"
        ).strip() or DEFAULT_JIRA_TEST_ISSUE_TYPE
        approved = sum(tc.review_status == ReviewStatus.APPROVED for tc in ws.test_cases)
        exported = approved if only_approved else len(ws.test_cases)
        theme_ui.badges(
            theme_ui.badge(t("ui.export.cases", lang, count=exported), "accent" if exported else "warning"),
            theme_ui.badge(t("ui.export.approved", lang, count=approved, total=len(ws.test_cases)),
                           "success" if approved else "neutral"),
            theme_ui.badge(t("ui.export.bugs", lang, count=len(ws.defects)), "neutral"),
        )
        if not exported:
            st.warning(t("ui.export.nothing_approved" if only_approved else "ui.export.no_cases", lang))

    x1, x2 = st.columns(2, gap="medium")
    with x1, theme_ui.card("export_jira"):
        theme_ui.section("Jira", ":material/integration_instructions:", t("ui.export.jira_help", lang))
        st.download_button(
            t("export.jira_tests", lang),
            jira_test_cases_csv(ws, only_approved, issue_type).encode("utf-8"),
            file_name="jira_test_cases.csv", mime="text/csv", icon=":material/download:", width="stretch",
        )
        st.download_button(
            t("export.jira_bugs", lang),
            jira_defects_csv(ws.defects).encode("utf-8"),
            file_name="jira_bug_reports.csv", mime="text/csv", icon=":material/download:",
            disabled=not ws.defects, width="stretch",
        )
        if not ws.defects:
            st.caption(t("ui.export.no_bugs", lang))
    with x2, theme_ui.card("export_testrail"):
        theme_ui.section("TestRail", ":material/table_view:", t("ui.export.testrail_help", lang))
        st.download_button(
            t("export.testrail", lang),
            testrail_csv(ws, only_approved).encode("utf-8"),
            file_name="testrail_test_cases.csv", mime="text/csv", icon=":material/download:", width="stretch",
        )
    y1, y2 = st.columns(2, gap="medium")
    with y1, theme_ui.card("export_rtm"):
        theme_ui.section(t("tab.rtm", lang), ":material/account_tree:", t("ui.export.rtm_help", lang))
        st.download_button(
            t("export.rtm", lang),
            rtm_csv(rtm_rows).encode("utf-8-sig"),
            file_name="rtm.csv", mime="text/csv", icon=":material/download:", width="stretch",
        )
    with y2, theme_ui.card("export_report"):
        theme_ui.section(t("ui.export.report", lang), ":material/description:", t("ui.export.report_help", lang))
        st.download_button(
            t("export.markdown", lang),
            markdown_report(ws, rtm_rows, lang).encode("utf-8"),
            file_name="qa_report.md", mime="text/markdown", icon=":material/download:", width="stretch",
        )
    with st.expander(t("export.mapping", lang)):
        st.markdown(t("export.mapping_body", lang))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def settings(p: Page, llm_settings: LLMSettings) -> None:
    lang = p.lang
    tab_ai, tab_projects, tab_data = st.tabs([
        t("ui.settings.ai", lang), t("ui.settings.projects", lang), t("ui.settings.data", lang),
    ])
    with tab_ai:
        left, right = st.columns([3, 2], gap="medium")
        with left, theme_ui.card("settings_ai"):
            theme_ui.section(t("llm.heading", lang), ":material/smart_toy:")
            llm_ui.render_settings(lang, llm_settings, p.ai_config)
        with right, theme_ui.card("settings_keys"):
            theme_ui.section(t("ui.settings.keys", lang), ":material/key:")
            st.markdown(t("ui.settings.keys_body", lang))
            st.info(t("sidebar.privacy_ai" if p.ai_config else "sidebar.privacy", lang), icon=":material/shield:")
    with tab_projects, theme_ui.card("settings_projects"):
        theme_ui.section(t("projects.settings_heading", lang), ":material/folder:")
        render_project_settings(lang, p.store)
    with tab_data, theme_ui.card("settings_data"):
        theme_ui.section(t("ui.settings.data", lang), ":material/database:")
        st.markdown(t("sidebar.storage" if persistence_enabled() else "sidebar.storage_session", lang))
