"""Streamlit entry point. Run with: streamlit run app.py"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Make the `src/` package importable without installing it.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from spec_to_test import __version__  # noqa: E402
from spec_to_test.ai_analysis import AIError, load_config, run_ai_analysis  # noqa: E402
from spec_to_test.bug_reports import (  # noqa: E402
    defect_from_suggestion,
    generate_defects,
    next_defect_id,
)
from spec_to_test.exports import (  # noqa: E402
    DEFAULT_JIRA_TEST_ISSUE_TYPE,
    jira_defects_csv,
    jira_test_cases_csv,
    markdown_report,
    rtm_csv,
    testrail_csv,
)
from spec_to_test.formatting import escape_markdown  # noqa: E402
from spec_to_test.i18n import LANGUAGES, clarification_question, t  # noqa: E402
from spec_to_test.input_parser import (  # noqa: E402
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    InputError,
    extract_requirements,
    read_uploaded_file,
)
from spec_to_test.models import (  # noqa: E402
    DefectReport,
    ReviewStatus,
    Severity,
    TestCase,
    TestType,
    Workspace,
)
from spec_to_test.quality import score_all  # noqa: E402
from spec_to_test.rtm import (  # noqa: E402
    Coverage,
    build_rtm,
    filter_rows,
    orphan_test_case_ids,
    summarize,
)
from spec_to_test.rule_engine import analyze_requirements  # noqa: E402
from spec_to_test.storage import (  # noqa: E402
    document_hash,
    load_latest,
    load_workspace,
    persistence_enabled,
    save_workspace,
)
from spec_to_test.test_design import design_tests, format_value  # noqa: E402
from spec_to_test.test_generator import generate_test_cases, next_test_case_id  # noqa: E402

st.set_page_config(page_title="Spec-to-Test", page_icon="🧪", layout="wide")

# Visual polish on top of the theme in .streamlit/config.toml.
st.html(
    """
    <style>
    .block-container {
        max-width: min(100%, 2400px);
        padding: 4.5rem clamp(1rem, 3vw, 3rem) 3rem;
    }
    [data-testid="stTable"] td { vertical-align: top; white-space: pre-wrap; }
    /* IDs such as REQ-001 should not break at the hyphen. */
    [data-testid="stTable"] tbody td:first-child,
    [data-testid="stTable"] tbody td:first-child * { white-space: nowrap; }
    .st-key-hero {
        background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 55%, #DB2777 100%);
        border-radius: 1.25rem;
        padding: 2rem 2.25rem 1.75rem;
        box-shadow: 0 12px 32px -12px rgba(79, 70, 229, 0.45);
    }
    .st-key-hero h1 { color: #fff; font-weight: 700; letter-spacing: -0.02em; padding: 0; }
    .st-key-hero [data-testid="stCaptionContainer"] { opacity: 1; }
    .st-key-hero [data-testid="stCaptionContainer"] p {
        color: rgba(255, 255, 255, 0.9); font-size: 1.05rem;
    }
    .st-key-hero .hero-badges {
        display: inline-block; margin-top: 0.25rem; padding: 0.3rem 0.8rem;
        border-radius: 999px; background: rgba(255, 255, 255, 0.16);
        color: #fff; font-size: 0.8rem; font-weight: 500;
    }
    .st-key-input_text, .st-key-input_file,
    [data-testid="stMetric"], [data-testid="stTabs"] {
        background: #fff;
        box-shadow: 0 1px 2px rgba(30, 27, 58, 0.04), 0 4px 16px -8px rgba(30, 27, 58, 0.08);
    }
    [data-testid="stTabs"] { border-radius: 0.75rem; padding: 0.5rem 1rem 1rem; }
    [data-testid="stMetric"] { padding: 1rem 1.25rem; }
    [data-testid="stMetricValue"] { color: #4F46E5; font-weight: 700; }
    [data-testid="stMetricLabel"] p { white-space: normal; overflow-wrap: anywhere; }
    @media (max-width: 640px) {
        .st-key-hero { padding: 1.25rem 1.25rem 1rem; }
    }
    .stButton button[kind="primary"] {
        padding: 0.6rem 2.5rem; font-weight: 600;
        box-shadow: 0 6px 16px -6px rgba(79, 70, 229, 0.6);
    }
    </style>
    """
)

SEVERITY_BADGES = {"high": "🔴", "medium": "🟠", "low": "🟡"}
STATUS_BADGES = {"clear": "✅", "needs_clarification": "⚠️", "resolved": "☑️"}
COVERAGE_BADGES = {"covered": "✅", "partial": "🟡", "not_covered": "❌"}
REVIEW_BADGES = {"draft": "📝", "reviewed": "👀", "approved": "✅"}
GRADE_BADGES = {"good": "🟢", "fair": "🟠", "poor": "🔴"}
ALL = "__all__"
TABLE_SCROLL_ROWS = 15
TABLE_MAX_HEIGHT = 720


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


def persist(ws: Workspace) -> None:
    """Keep the session and the local save file in sync after every edit."""
    st.session_state["workspace"] = ws
    try:
        save_workspace(ws)
    except (OSError, ValueError):
        flash(t("storage.save_failed", lang), icon="⚠️")


# --- Sidebar ---------------------------------------------------------------
# Root-level secrets (Streamlit Cloud or .streamlit/secrets.toml) become environment
# variables, which is where the AI and storage settings are read from.
secrets_error = False
try:
    st.secrets.load_if_toml_exists()
except Exception:  # noqa: BLE001 - a malformed secrets file must not break the app
    secrets_error = True

current = st.session_state.get("language", "en")
lang: str = st.sidebar.selectbox(
    t("sidebar.language", current),
    options=list(LANGUAGES),
    format_func=lambda code: LANGUAGES[code],
    key="language",
) or "en"
ai_config = load_config()
st.sidebar.info(t("sidebar.privacy_ai" if ai_config else "sidebar.privacy", lang))
st.sidebar.caption(t("sidebar.storage" if persistence_enabled() else "sidebar.storage_session", lang))
if secrets_error:
    st.sidebar.warning(t("sidebar.secrets_invalid", lang))
st.sidebar.caption(t("sidebar.version", lang, version=__version__))

# Restore the last saved workspace once per browser session.
if not st.session_state.get("restore_checked"):
    st.session_state["restore_checked"] = True
    if (saved := load_latest()) is not None:
        st.session_state["workspace"] = saved
        st.session_state["restored"] = True

# --- Input -----------------------------------------------------------------
with st.container(key="hero"):
    st.title(t("app.title", lang))
    st.caption(t("app.subtitle", lang))
    st.html(f'<span class="hero-badges">{t("app.badges", lang)}</span>')

col_text, col_file = st.columns([3, 2], gap="medium")
with col_text.container(border=True, key="input_text", height="stretch"):
    st.markdown(f"#### {t('input.text_heading', lang)}")
    text = st.text_area(
        t("input.text_label", lang),
        placeholder=t("input.text_placeholder", lang),
        height=220,
    )
with col_file.container(border=True, key="input_file", height="stretch"):
    st.markdown(f"#### {t('input.file_heading', lang)}")
    uploaded = st.file_uploader(
        t("input.file_label", lang, max_mb=MAX_FILE_SIZE_BYTES // (1024 * 1024)),
        type=[ext.lstrip(".") for ext in ALLOWED_EXTENSIONS],
    )
    if uploaded is not None:
        st.info(t("input.file_used", lang), icon="📎")

if st.button(t("input.analyze_button", lang), type="primary", icon=":material/search:"):
    st.session_state.pop("restored", None)
    st.session_state["ai_consent"] = False  # consent is per document and per run
    try:
        with st.spinner(t("input.analyzing", lang)):
            source = read_uploaded_file(uploaded.name, uploaded.getvalue()) if uploaded else text
            requirements = extract_requirements(source)
            doc_hash = document_hash(source.strip())
            saved = load_workspace(doc_hash)
            if saved is not None:
                workspace = saved
                st.session_state["restored"] = True
            else:
                result = analyze_requirements(requirements)
                workspace = Workspace(
                    document_hash=doc_hash,
                    requirements=result.requirements,
                    findings=result.findings,
                )
                workspace.test_cases = generate_test_cases(workspace, lang)
            persist(workspace)
    except InputError as error:
        st.session_state.pop("workspace", None)
        st.error(t(f"error.{error.code}", lang, **error.params))

# --- Results ---------------------------------------------------------------
loaded: Workspace | None = st.session_state.get("workspace")
if loaded is None:
    st.info(t("input.empty_state", lang), icon="💡")
    st.stop()
ws: Workspace = loaded

if st.session_state.get("restored"):
    st.info(t("storage.restored", lang), icon="💾")
show_flash()

result = ws.analysis
scores = score_all(ws.requirements, ws.findings)
statuses = {req.id: result.status_of(req.id) for req in result.requirements}
st.subheader(t("results.heading", lang))
col1, col2, col3 = st.columns(3)
col1.metric(t("results.requirements_count", lang), len(result.requirements), border=True)
col2.metric(t("results.findings_count", lang), len(result.findings), border=True)
col3.metric(
    t("results.needs_clarification_count", lang),
    sum(status == "needs_clarification" for status in statuses.values()),
    border=True,
)

(
    tab_requirements,
    tab_findings,
    tab_dashboard,
    tab_rtm,
    tab_tests,
    tab_design,
    tab_defects,
    tab_ai,
    tab_export,
) = st.tabs(
    [
        t("results.tab_requirements", lang),
        t("results.tab_findings", lang),
        t("tab.dashboard", lang),
        t("tab.rtm", lang),
        t("tab.tests", lang),
        t("tab.design", lang),
        t("tab.defects", lang),
        t("tab.ai", lang),
        t("tab.export", lang),
    ]
)

req_ids = [req.id for req in ws.requirements]


def req_label(req_id: str) -> str:
    req = ws.requirement(req_id)
    snippet = req.text if req and len(req.text) <= 60 else (req.text[:59] + "…" if req else "")
    return f"{req_id} — {snippet}"


# --- Requirements ----------------------------------------------------------
with tab_requirements:
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
            for req in result.requirements
        ],
    )
    with st.expander(t("quality.heading", lang), icon=":material/grading:"):
        st.caption(t("quality.explainer", lang))
        quality_req = st.selectbox(
            t("quality.select", lang), req_ids, format_func=req_label, key="quality_req"
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

# --- Findings --------------------------------------------------------------
with tab_findings:
    st.caption(f":material/info: {t('results.rule_disclaimer', lang)}")
    if not result.findings:
        st.success(t("results.no_findings", lang))
    else:
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

rtm_rows = build_rtm(ws, scores)

# --- Dashboard -------------------------------------------------------------
with tab_dashboard:
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

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"**{t('dash.severity_distribution', lang)}**")
        bar_chart({t(f"severity.{k}", lang): v for k, v in summary.severity_distribution.items()})
    with c2:
        st.markdown(f"**{t('dash.coverage_distribution', lang)}**")
        bar_chart({t(f"coverage.{k}", lang): v for k, v in summary.coverage_distribution.items()})
    with c3:
        st.markdown(f"**{t('dash.review_distribution', lang)}**")
        bar_chart({t(f"review.{k}", lang): v for k, v in summary.review_distribution.items()})

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
    else:
        st.info(t("dash.no_match", lang))

# --- RTM -------------------------------------------------------------------
with tab_rtm:
    st.caption(t("rtm.explainer", lang))
    show_table(
        [
            {
                t("column.id", lang): row.requirement_id,
                t("column.requirement", lang): row.requirement_text,
                t("column.quality", lang): row.quality_score,
                t("column.open_issues", lang): ", ".join(t(f"finding.{i}", lang) for i in row.open_issues) or "—",
                t("column.test_cases", lang): ", ".join(row.test_case_ids) or "—",
                t("column.approved", lang): ", ".join(row.approved_test_case_ids) or "—",
                t("column.bugs", lang): ", ".join(row.defect_ids) or "—",
                t("column.coverage", lang): (
                    f"{COVERAGE_BADGES[row.coverage.value]} {t(f'coverage.{row.coverage.value}', lang)}"
                ),
            }
            for row in rtm_rows
        ],
    )
    if orphans := orphan_test_case_ids(ws):
        st.warning(t("rtm.orphans", lang, ids=", ".join(orphans)))

# --- Test case editor ------------------------------------------------------
with tab_tests:
    st.caption(t("tests.explainer", lang))
    tc_filter = st.selectbox(
        t("tests.filter_requirement", lang), [ALL, *req_ids],
        format_func=lambda v: t("filter.all", lang) if v == ALL else req_label(v),
        key="tc_filter",
    )
    cases = [tc for tc in ws.test_cases if tc_filter == ALL or tc.requirement_id == tc_filter]

    b1, b2 = st.columns(2)
    if b1.button(t("tests.add", lang), icon=":material/add:", key="tc_add"):
        target = tc_filter if tc_filter != ALL else req_ids[0]
        new_case = TestCase(
            id=next_test_case_id(ws.test_cases),
            requirement_id=target,
            title=t("tests.new_title", lang),
            test_type=TestType.POSITIVE,
            steps=[t("tests.new_step", lang)],
            expected_result=t("tests.new_expected", lang),
        )
        ws.test_cases.append(new_case)
        persist(ws)
        st.session_state["tc_selected"] = new_case.id
        st.rerun()
    if b2.button(t("tests.generate_missing", lang), icon=":material/auto_awesome:", key="tc_generate"):
        missing = [req for req in ws.requirements if not ws.tests_for(req.id)]
        scratch = Workspace(requirements=missing, findings=ws.findings, test_cases=ws.test_cases)
        created = generate_test_cases(scratch, lang)
        ws.test_cases.extend(created)
        persist(ws)
        flash(t("tests.generated", lang, count=len(created)))
        st.rerun()

    if not cases:
        st.info(t("tests.none", lang))
    else:
        show_table(
            [
                {
                    t("column.test_id", lang): tc.id,
                    t("column.id", lang): tc.requirement_id,
                    t("column.title", lang): tc.title,
                    t("column.test_type", lang): t(f"test_type.{tc.test_type.value}", lang),
                    t("column.review", lang): (
                        f"{REVIEW_BADGES[tc.review_status.value]} {t(f'review.{tc.review_status.value}', lang)}"
                    ),
                }
                for tc in cases
            ],
        )
        case_ids = [tc.id for tc in cases]
        if st.session_state.get("tc_selected") not in case_ids:
            st.session_state["tc_selected"] = case_ids[0]
        titles = {tc.id: tc.title for tc in cases}
        selected_id = st.selectbox(
            t("tests.select", lang), case_ids,
            format_func=lambda i: f"{i} — {titles[i]}", key="tc_selected",
        )
        tc = next(c for c in ws.test_cases if c.id == selected_id)
        if tc.clarification_questions:
            st.warning(
                t("tests.open_questions", lang)
                + "\n\n"
                + "\n".join(f"- {escape_markdown(q)}" for q in tc.clarification_questions)
            )
        with st.form(key=f"tc_form_{tc.id}"):
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
                        "preconditions": lines(preconditions),
                        "steps": lines(steps),
                        "expected_result": expected.strip(),
                        "assumptions": lines(assumptions),
                        "reviewer_comment": comment.strip(),
                    }
                )
                ws.test_cases = [updated if c.id == tc.id else c for c in ws.test_cases]
                persist(ws)
                flash(t("action.saved", lang, id=tc.id))
                st.rerun()
        d1, d2 = st.columns([1, 3])
        confirm = d2.checkbox(t("action.confirm_delete", lang, id=tc.id), key=f"tc_confirm_{tc.id}")
        if d1.button(t("action.delete", lang), icon=":material/delete:", disabled=not confirm, key=f"tc_delete_{tc.id}"):
            ws.test_cases = [c for c in ws.test_cases if c.id != tc.id]
            persist(ws)
            st.session_state.pop("tc_selected", None)
            flash(t("action.deleted", lang, id=tc.id), icon="🗑️")
            st.rerun()

# --- Test design -----------------------------------------------------------
with tab_design:
    st.caption(t("design.explainer", lang))
    design_req = st.selectbox(t("quality.select", lang), req_ids, format_func=req_label, key="design_req")
    design = design_tests(next(r for r in ws.requirements if r.id == design_req))
    if design.is_empty:
        st.info(t("design.not_applicable", lang))
    for analysis in design.boundaries:
        unit = t(f"unit.{analysis.constraint.unit}", lang)
        st.markdown(f"**{t('design.bva', lang)}** — “{escape_markdown(analysis.constraint.phrase)}”")
        show_table(
            [
                {
                    t("design.value", lang): f"{format_value(v.value)} {unit}",
                    t("design.expectation", lang): t(f"design.{v.expectation}", lang),
                }
                for v in analysis.values
            ]
        )
    for classes in design.partitions:
        unit = t(f"unit.{classes.constraint.unit}", lang)
        st.markdown(f"**{t('design.ep', lang)}** — “{escape_markdown(classes.constraint.phrase)}”")
        show_table(
            [
                {
                    t("design.partition", lang): f"{p.interval} {unit}",
                    t("design.representative", lang): format_value(p.representative),
                    t("design.expectation", lang): t(f"design.{p.expectation}", lang),
                }
                for p in classes.partitions
            ]
        )
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

# --- Bug reports -----------------------------------------------------------
with tab_defects:
    st.caption(t("bugs.explainer", lang))
    if st.button(t("bugs.generate", lang), icon=":material/bug_report:", key="bug_generate"):
        created_bugs = generate_defects(ws, lang)
        ws.defects.extend(created_bugs)
        persist(ws)
        flash(t("bugs.generated", lang, count=len(created_bugs)))
        st.rerun()
    if not ws.defects:
        st.info(t("bugs.none", lang))
    else:
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
                persist(ws)
                flash(t("action.saved", lang, id=bug.id))
                st.rerun()
        e1, e2 = st.columns([1, 3])
        bug_confirm = e2.checkbox(t("action.confirm_delete", lang, id=bug.id), key=f"bug_confirm_{bug.id}")
        if e1.button(t("action.delete", lang), icon=":material/delete:", disabled=not bug_confirm, key=f"bug_delete_{bug.id}"):
            ws.defects = [d for d in ws.defects if d.id != bug.id]
            persist(ws)
            st.session_state.pop("bug_selected", None)
            flash(t("action.deleted", lang, id=bug.id), icon="🗑️")
            st.rerun()

# --- AI analysis -----------------------------------------------------------
with tab_ai:
    st.caption(t("ai.explainer", lang))
    if ai_config is None:
        st.info(t("ai.not_configured", lang), icon="🔌")
    else:
        st.markdown(
            t("ai.configured", lang, provider=ai_config.provider, model=escape_markdown(ai_config.model))
        )
        if st.session_state.pop("ai_consent_reset", False):
            st.session_state["ai_consent"] = False
        consent = st.checkbox(
            t("ai.consent", lang, provider=ai_config.provider, count=len(ws.requirements)), key="ai_consent"
        )
        if st.button(t("ai.run", lang), icon=":material/psychology:", disabled=not consent, key="ai_run"):
            st.session_state["ai_consent_reset"] = True  # ask again before the next run
            try:
                with st.spinner(t("ai.running", lang)):
                    suggestions = run_ai_analysis(ws.requirements, ai_config, consent=consent, lang=lang)
                ws.ai_suggestions = suggestions
                ws.ai_model = ai_config.model
                persist(ws)
                flash(t("ai.done", lang, count=len(suggestions)))
                st.rerun()
            except AIError as error:
                st.error(t(f"ai.error.{error.code}", lang))
    if ws.ai_suggestions:
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
                persist(ws)
                flash(t("bugs.generated", lang, count=1))
                st.rerun()

# --- Exports ---------------------------------------------------------------
with tab_export:
    st.caption(t("export.explainer", lang))
    only_approved = st.checkbox(t("export.only_approved", lang), key="export_only_approved")
    issue_type = st.text_input(
        t("export.jira_issue_type", lang), DEFAULT_JIRA_TEST_ISSUE_TYPE, key="export_issue_type"
    ).strip() or DEFAULT_JIRA_TEST_ISSUE_TYPE
    x1, x2 = st.columns(2)
    x1.download_button(
        t("export.jira_tests", lang),
        jira_test_cases_csv(ws, only_approved, issue_type).encode("utf-8"),
        file_name="jira_test_cases.csv", mime="text/csv", icon=":material/download:",
    )
    x2.download_button(
        t("export.testrail", lang),
        testrail_csv(ws, only_approved).encode("utf-8"),
        file_name="testrail_test_cases.csv", mime="text/csv", icon=":material/download:",
    )
    x1.download_button(
        t("export.jira_bugs", lang),
        jira_defects_csv(ws.defects).encode("utf-8"),
        file_name="jira_bug_reports.csv", mime="text/csv", icon=":material/download:",
        disabled=not ws.defects,
    )
    x2.download_button(
        t("export.rtm", lang),
        rtm_csv(rtm_rows).encode("utf-8-sig"),
        file_name="rtm.csv", mime="text/csv", icon=":material/download:",
    )
    x1.download_button(
        t("export.markdown", lang),
        markdown_report(ws, rtm_rows, lang).encode("utf-8"),
        file_name="qa_report.md", mime="text/markdown", icon=":material/download:",
    )
    with st.expander(t("export.mapping", lang)):
        st.markdown(t("export.mapping_body", lang))
