"""Grill Mode page for the Streamlit app.

Rendering only: every decision is made by `spec_to_test.grill` (workflow,
planner, validation). The session lives in this browser session's
`st.session_state`, so users never share state, and it survives ordinary
reruns. Buttons use callbacks that pass the revision the page was rendered
with, so a double click or an outdated page is rejected instead of applied.

AI is optional. It is offered only when configured, and every request needs
consent; the model is called from `spec_to_test.grill.ai`, and its output
enters the session only through the workflow's AI transitions. One-off
requests (extra questions, review, test ideas) need a fresh tick each time;
the AI interviewer is switched on once per Grill session, with a consent that
covers its follow-up questions in that session only. If the model fails, the
interview simply continues with the built-in questions.

A finalized result can be downloaded as Markdown or handed to the analysis
workspace (`spec_to_test.grill.integration`); the page that owns the
workspace passes `persist`, which is used to save it. The final report
(`spec_to_test.grill.report`) separates confirmed facts, assumptions and
unknowns and lists suggested test cases.

Every change is also saved as an interview of the open project
(`spec_to_test.grill.persistence`): on disk in "local" storage mode, where the
last unfinished interview reopens after a page reload, or in this browser
session otherwise (with "save progress to a file" and "resume from a file").
The History tab shows where each decision came from and every change to it
(`spec_to_test.grill.trace`).
"""

from collections.abc import Callable
from typing import Any

import streamlit as st

import theme_ui
from projects_ui import active_project_id
from spec_to_test.ai_analysis import AIConfig, AIError
from spec_to_test.formatting import escape_markdown
from spec_to_test.grill import ai as grill_ai
from spec_to_test.grill import insights
from spec_to_test.grill.conflicts import Conflict, detect_conflicts, question_states
from spec_to_test.grill.drafts import DraftError, draft_from_text, editable_fields, is_list_field
from spec_to_test.grill.inputs import parse_draft, requirements_draft
from spec_to_test.grill.integration import (
    IntegrationError,
    add_blocker,
    add_to_workspace,
    context_blocker,
    markdown_file_name,
    resolutions,
    resolve_blocker,
    resolve_findings,
    result_markdown,
)
from spec_to_test.grill.models import (
    DRAFT_TYPES,
    AnswerStatus,
    ArtifactType,
    BugReportDraft,
    ClarificationState,
    FindingLevel,
    GrillKind,
    GrillMode,
    GrillSession,
    GrillStep,
    Priority,
    Question,
    Reproducibility,
    RequirementsDraft,
    ReviewFinding,
    TestCaseDraft,
    load_session,
)
from spec_to_test.grill.persistence import (
    InterviewStore,
    InterviewSummary,
    PersistenceError,
    SavedInterview,
    export_json,
    import_json,
    open_interview_store,
)
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW
from spec_to_test.grill.report import (
    GrillReport,
    SuggestedTestCase,
    build_report,
    case_label,
    contradiction_status,
    origin_label,
    report_markdown,
)
from spec_to_test.grill.rules import rule_question_id
from spec_to_test.grill.text import (
    draft_rows,
    field_label,
    provenance_label,
    render_choice,
    render_finding,
    render_question,
    value_text,
)
from spec_to_test.grill.trace import (
    audit_file_name,
    audit_json,
    audit_rows,
    decision_records,
    origin_text,
    retire_reason_text,
    state_counts,
    trace_markdown,
)
from spec_to_test.grill.validation import is_placeholder
from spec_to_test.grill.workflow import Action, GrillError, allowed_actions
from spec_to_test.i18n import clarification_question, t
from spec_to_test.input_parser import MAX_TEXT_CHARS, InputError
from spec_to_test.models import (
    MAX_REASON_LENGTH,
    ClarificationStatus,
    Finding,
    Requirement,
    Severity,
    Source,
    TestType,
    Workspace,
)
from spec_to_test.quality import QualityScore, score_all
from spec_to_test.storage import persistence_enabled

WF = DETERMINISTIC_WORKFLOW
STATE = "grill_session"
ERROR = "grill_error"  # (translation key, params), shown once on the next run
UNPARSED = "grill_unparsed"
NOTICE = "grill_notice"  # (translation key, params), shown once on the next run
SUCCESS = "grill_success"  # (translation key, params), shown once on the next run
WORKSPACE = "workspace"  # the analysis page's workspace (see app.py)
AI_RUNS = "grill_ai_runs"  # part of the consent checkbox key, so consent resets after every request
AI_ASKED = "grill_ai_asked"  # interview state the AI interviewer was last asked about (asked once per state)
AI_TESTS = "grill_ai_test_ideas"  # session ID -> AI test case ideas for the final report
OWNER = "grill_owner"  # (project id, document hash) the open interview belongs to
RESTORED = "grill_restored_projects"  # projects whose last interview was already reopened in this session
IMPORT = "grill_import_file"
OTHER = "__other__"

LEVEL_ICONS = {FindingLevel.BLOCKING: "⛔", FindingLevel.WARNING: "⚠️", FindingLevel.SUGGESTION: "💡"}
STATE_ICONS = {
    ClarificationState.CONFIRMED: "✅", ClarificationState.ASSUMPTION: "🟡", ClarificationState.UNKNOWN: "❓",
    ClarificationState.CONFLICT: "⚔️", ClarificationState.OPEN: "⏳",
}
PRIORITY_ICONS = {"high": "🔴", "medium": "🟠", "low": "⚪"}
PRIORITY_TONES = {"high": "danger", "medium": "warning", "low": "neutral"}
STATE_TONES = {
    ClarificationState.CONFIRMED: "success", ClarificationState.ASSUMPTION: "warning",
    ClarificationState.UNKNOWN: "neutral", ClarificationState.CONFLICT: "danger", ClarificationState.OPEN: "info",
}
LEVEL_TONES = {FindingLevel.BLOCKING: "danger", FindingLevel.WARNING: "warning", FindingLevel.SUGGESTION: "info"}
CENTER_RIGHT = [1.75, 1]  # the interview and the analysis panel beside it
SHORT_TEXT_FIELDS = {"title", "feature", "summary", "environment", "app_version", "requirement_id"}
CHOICE_FIELDS: dict[str, tuple[list[str], str]] = {
    "test_type": ([v.value for v in TestType], "test_type"),
    "severity": ([v.value for v in Severity], "severity"),
    "reproducibility": ([v.value for v in Reproducibility], "grill.reproducibility"),
    "priority": ([v.value for v in Priority], "grill.priority"),
}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _store() -> InterviewStore:
    return open_interview_store(st.session_state)


def _owner() -> tuple[str, str]:
    owner = st.session_state.get(OWNER)
    if isinstance(owner, tuple | list) and len(owner) == 2:
        return str(owner[0]), str(owner[1])
    workspace = st.session_state.get(WORKSPACE)
    return active_project_id(), workspace.document_hash if isinstance(workspace, Workspace) else ""


def _record(session: GrillSession) -> SavedInterview:
    project_id, document = _owner()
    return SavedInterview(
        project_id=project_id, document_hash=document, session=session,
        unparsed=list(st.session_state.get(UNPARSED) or []), ai_test_ideas=_ai_tests(session),
    )


def _save(session: GrillSession) -> None:
    """Keep the session in this browser session and save it as an interview of its project."""
    st.session_state[STATE] = session.model_dump(mode="json")
    record = _record(session)
    st.session_state[OWNER] = (record.project_id, record.document_hash)
    try:
        store = _store()
        store.save(record)
        store.set_last_active(record.project_id, session.id)
    except (OSError, ValueError):
        _error("grill.ui.save_failed")


def _open_record(record: SavedInterview) -> None:
    """Make a saved interview the open one, with what the page kept beside it."""
    st.session_state[STATE] = record.session.model_dump(mode="json")
    st.session_state[OWNER] = (record.project_id, record.document_hash)
    st.session_state[UNPARSED] = list(record.unparsed)
    st.session_state[AI_TESTS] = {record.session.id: [c.model_dump(mode="json") for c in record.ai_test_ideas]}
    st.session_state.pop(AI_ASKED, None)


def _current() -> GrillSession | None:
    return load_session(st.session_state.get(STATE))


def _error(key: str, **params: Any) -> None:
    st.session_state[ERROR] = (key, params)


def _notice(key: str, **params: Any) -> None:
    st.session_state[NOTICE] = (key, params)


def _success(key: str, **params: Any) -> None:
    st.session_state[SUCCESS] = (key, params)


def _run(method: Callable[..., GrillSession], revision: int, *args: Any, **kwargs: Any) -> None:
    """Apply one workflow action to the stored session (called from callbacks)."""
    session = _current()
    if session is None:
        _error("grill.ui.restore_failed")
        return
    try:
        _save(method(session, *args, expected_revision=revision, **kwargs))
    except GrillError as exc:
        _error(f"grill.error.{exc.code}")


def _key(session: GrillSession, *parts: object) -> str:
    """Widget key unique to this session, so old input never leaks into a new one."""
    return "_".join(["grill", session.id, *map(str, parts)])


def _md(text: str) -> str:
    return escape_markdown(text)


def _table(rows: list[dict[str, str]]) -> None:
    safe = [{_md(k): _md(v) for k, v in row.items()} for row in rows]
    st.table(safe, hide_index=True, border="horizontal", height=720 if len(rows) > 15 else "content")


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _on_start(
    kind: str, mode: str, artifact: str, use_analyzed: bool, context: list[Requirement], settled: list[str] | None = None,
) -> None:
    artifact_type = ArtifactType(artifact)
    unparsed: list[str] = []
    text = ""
    try:
        if artifact_type == ArtifactType.REQUIREMENTS:
            if use_analyzed:
                draft: TestCaseDraft | BugReportDraft | RequirementsDraft = RequirementsDraft(requirements=context)
            else:
                text = st.session_state.get("grill_requirements_text", "")
                draft = requirements_draft(text)
        elif GrillMode(mode) == GrillMode.INTERVIEW:
            draft = DRAFT_TYPES[artifact_type]()
        else:
            text = st.session_state.get("grill_draft_text", "")
            parsed = parse_draft(text, TestCaseDraft if artifact_type == ArtifactType.TEST_CASE else BugReportDraft)
            draft, unparsed = parsed.draft, parsed.unparsed
    except InputError as exc:
        _error(f"error.{exc.code}", **exc.params)
        return
    session = WF.start(
        GrillKind(kind),
        GrillMode(mode),
        artifact_type if GrillKind(kind) == GrillKind.REVIEW else None,
        context_requirements=None if artifact_type == ArtifactType.REQUIREMENTS else context,
        # Findings resolved in the analyzed document are not asked about again.
        settled_question_ids=settled if artifact_type == ArtifactType.REQUIREMENTS and use_analyzed else None,
    )
    st.session_state.pop(OWNER, None)  # a new interview belongs to the open project and document
    st.session_state[UNPARSED] = unparsed
    _save(WF.submit_input(session, draft, text))


def _clear_open() -> None:
    for key in (STATE, UNPARSED, AI_ASKED, AI_TESTS, OWNER):
        st.session_state.pop(key, None)


def _on_new_session() -> None:
    """Close the open interview (it stays saved) and show the start screen."""
    project_id = _owner()[0]
    _clear_open()
    try:
        _store().set_last_active(project_id, "")
    except (OSError, ValueError):
        pass


def _on_resume(session_id: str) -> None:
    record = _store().load(active_project_id(), session_id)
    if record is None:
        _error("grill.error.interview_invalid")
        return
    _open_record(record)
    try:
        _store().set_last_active(record.project_id, session_id)
    except (OSError, ValueError):
        pass
    _success("grill.ui.resumed")


def _on_delete_interview(session_id: str) -> None:
    try:
        _store().delete(active_project_id(), session_id)
    except (OSError, ValueError):
        _error("grill.ui.save_failed")
        return
    _success("grill.ui.interview_deleted")


def _on_import() -> None:
    uploaded = st.session_state.get(IMPORT)
    if uploaded is None:
        return
    try:
        record = import_json(uploaded.getvalue(), active_project_id())
    except PersistenceError as exc:
        _error(f"grill.error.{exc.code}")
        return
    _open_record(record)
    _save(record.session)
    _success("grill.ui.imported")


def _on_answer(revision: int, status: str, choice_key: str, text_key: str) -> None:
    answer_status = AnswerStatus(status)
    value = ""
    if answer_status != AnswerStatus.UNKNOWN:
        choice = st.session_state.get(choice_key)
        value = choice if choice not in (None, OTHER) else st.session_state.get(text_key, "")
    _run(WF.answer, revision, value or "", answer_status)


def _save_draft(revision: int, raw: dict[str, str | None]) -> None:
    session = _current()
    if session is None or session.draft is None:
        _error("grill.ui.restore_failed")
        return
    try:
        edited = draft_from_text(session.draft, raw)
    except DraftError as exc:
        _error(f"grill.error.{exc.code}")
        return
    _run(WF.update_draft, revision, edited)


def _on_edit_answer(revision: int, select_key: str) -> None:
    if question_id := st.session_state.get(select_key):
        _run(WF.edit_answer, revision, question_id)


def _on_request_confirmation(revision: int, accept_key: str) -> None:
    _run(WF.request_confirmation, revision, bool(st.session_state.get(accept_key, False)))


Persist = Callable[[Workspace], None]


def _finalized(revision: int) -> GrillSession | None:
    """The stored session, if it is still the one the page showed."""
    session = _current()
    if session is None or session.revision != revision:
        _error("grill.error.stale_session")
        return None
    return session


def _on_add_to_workspace(revision: int, lang: str, persist: Persist) -> None:
    if (session := _finalized(revision)) is None:
        return
    try:
        workspace, item_id = add_to_workspace(session, st.session_state.get(WORKSPACE), lang)
    except IntegrationError as exc:
        _error(f"grill.error.{exc.code}")
        return
    persist(workspace)
    _success(f"grill.ui.added_{session.artifact.value}", id=item_id)


def _on_resolve(revision: int, persist: Persist, choice_keys: dict[str, str], reason_key: str = "") -> None:
    if (session := _finalized(revision)) is None:
        return
    chosen = [qid for qid, key in choice_keys.items() if st.session_state.get(key)]
    before = st.session_state.get(WORKSPACE)
    try:
        workspace = resolve_findings(session, before, chosen, reason=str(st.session_state.get(reason_key) or ""))
    except IntegrationError as exc:
        _error(f"grill.error.{exc.code}")
        return
    assert before is not None  # resolve_findings rejects a missing workspace
    resolved = sum(old.status != new.status for old, new in zip(before.findings, workspace.findings, strict=True))
    persist(workspace)
    _success("grill.ui.resolved", count=resolved)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def _restore_last(project_id: str) -> None:
    """After a reload (a new browser session), reopen the project's last unfinished interview once."""
    restored = st.session_state.setdefault(RESTORED, [])
    if project_id in restored:
        return
    restored.append(project_id)
    try:
        store = _store()
        session_id = store.last_active(project_id)
        record = store.load(project_id, session_id) if session_id else None
    except (OSError, ValueError):
        return
    if record is not None and not record.session.is_terminal:
        _open_record(record)
        _notice("grill.ui.restored", time=_time(record.session.updated_at))


def _sync_findings(session: GrillSession, workspace: Workspace) -> GrillSession:
    """Reflect findings resolved or reopened in the analyzed document in the open interview.

    Only for a requirements interview on this very document (same document and
    the same requirement texts); finished interviews are records and stay as they are.
    """
    if session.is_terminal or not isinstance(session.draft, RequirementsDraft):
        return session
    if _owner()[1] != workspace.document_hash:
        return session
    known = {r.id: r.text for r in workspace.requirements}
    if [(r.id, r.text) for r in session.draft.requirements] != [(r.id, known.get(r.id)) for r in session.draft.requirements]:
        return session
    settled = sorted({rule_question_id(f) for f in workspace.findings if f.status == ClarificationStatus.RESOLVED})
    try:
        synced = WF.sync_settled(session, settled)
    except GrillError:
        return session
    if synced.revision == session.revision:
        return session
    before = set(session.settled_question_ids)
    _save(synced)
    _notice("grill.ui.findings_synced", resolved=len(set(settled) - before), reopened=len(before - set(settled)))
    return synced


def render_grill(
    lang: str, workspace: Workspace | None, ai_config: AIConfig | None = None, persist: Persist | None = None
) -> None:
    project_id = active_project_id()
    if st.session_state.get(STATE) is not None and _owner()[0] != project_id:
        _clear_open()  # another project's interview: it stays saved there
    if st.session_state.get(STATE) is None:
        _restore_last(project_id)
    raw = st.session_state.get(STATE)
    session = load_session(raw)
    if raw is not None and session is None:  # stale or broken state: start over, say so
        _on_new_session()
        _error("grill.ui.restore_failed")
    if session is not None and workspace is not None:
        session = _sync_findings(session, workspace)
    if error := st.session_state.pop(ERROR, None):
        key, params = error
        st.error(t(key, lang, **params), icon=":material/error:")
    if notice := st.session_state.pop(NOTICE, None):
        key, params = notice
        icon = {"grill.ui.restored": ":material/info:", "grill.ui.findings_synced": ":material/sync:"}.get(key)
        st.info(t(key, lang, **params), icon=icon or ":material/smart_toy:")
    if success := st.session_state.pop(SUCCESS, None):
        key, params = success
        st.success(t(key, lang, **params), icon=":material/check_circle:")

    if session is None:
        _start_screen(lang, workspace, ai_config)
    else:
        _session_screen(lang, session, ai_config, workspace, persist)


def _mode_note(lang: str, ai_config: AIConfig | None) -> None:
    if ai_config is None:
        st.info(t("grill.ui.mode_deterministic", lang), icon=":material/rule:")
    else:
        st.info(t("grill.ui.mode_ai_available", lang, model=_md(ai_config.model)), icon=":material/rule:")


def _time(stamp: str) -> str:
    return stamp[:16].replace("T", " ") if stamp else "—"


def _start_screen(lang: str, workspace: Workspace | None, ai_config: AIConfig | None = None) -> None:
    context = list(workspace.requirements) if workspace else []
    settled = sorted({
        rule_question_id(f) for f in (workspace.findings if workspace else [])
        if f.status == ClarificationStatus.RESOLVED
    })
    center, right = st.columns(CENTER_RIGHT, gap="large")
    with right:
        _saved_interviews(lang)
        _mode_note(lang, ai_config)
        if workspace is not None and workspace.requirements:
            theme_ui.quality_card(
                lang, list(score_all(workspace.requirements, workspace.findings).values()), "grill_doc_quality",
            )
        _states_legend(lang)
    with center, theme_ui.card("grill_panel"):
        theme_ui.section(t("ui.grill.setup", lang), ":material/play_circle:", t("grill.ui.intro", lang))
        kind = GrillKind(
            st.radio(
                t("grill.ui.choose_workflow", lang), [k.value for k in GrillKind],
                format_func=lambda v: t(f"grill.kind.{v}", lang), key="grill_kind", horizontal=True,
            )
        )
        mode, artifact = GrillMode.INTERVIEW, ArtifactType.REQUIREMENTS
        if kind in (GrillKind.TEST_CASE, GrillKind.BUG_REPORT):
            artifact = ArtifactType(kind.value)
            mode = GrillMode(
                st.radio(
                    t("grill.ui.choose_mode", lang), [m.value for m in GrillMode],
                    format_func=lambda v: t(f"grill.mode.{v}", lang), key="grill_mode", horizontal=True,
                )
            )
        elif kind == GrillKind.REVIEW:
            mode = GrillMode.REVIEW_DRAFT
            artifact = ArtifactType(
                st.radio(
                    t("grill.ui.choose_artifact", lang), [a.value for a in ArtifactType],
                    format_func=lambda v: t(f"grill.artifact.{v}", lang), key="grill_artifact", horizontal=True,
                )
            )

        use_analyzed = False
        if artifact == ArtifactType.REQUIREMENTS:
            if context:
                use_analyzed = st.checkbox(
                    t("grill.ui.use_analyzed", lang, count=len(context)), value=True, key="grill_use_analyzed"
                )
            if not use_analyzed:
                st.text_area(
                    t("grill.ui.requirements_input", lang), key="grill_requirements_text", height=200,
                    placeholder=t("grill.ui.requirements_placeholder", lang),
                )
        else:
            if context:
                st.caption(t("grill.ui.context_loaded", lang, count=len(context)))
            else:
                st.caption(t("grill.ui.context_missing", lang))
            if mode == GrillMode.REVIEW_DRAFT:
                st.text_area(
                    t("grill.ui.draft_input", lang), key="grill_draft_text", height=240,
                    placeholder=t(f"grill.ui.draft_placeholder_{artifact.value}", lang),
                )
                st.caption(t("grill.ui.draft_hint", lang))

        if use_analyzed and settled:
            st.caption(t("grill.ui.settled_note", lang, count=len(settled)))
        st.button(
            t("grill.ui.start", lang), type="primary", icon=":material/play_arrow:", key="grill_start",
            on_click=_on_start, args=(kind.value, mode.value, artifact.value, use_analyzed, context, settled),
        )


def _interview_line(lang: str, summary: InterviewSummary) -> None:
    step_tone = "success" if summary.step == GrillStep.FINALIZED.value else (
        "neutral" if summary.finished else "accent")
    theme_ui.badges(
        theme_ui.badge(t(f"grill.kind.{summary.kind.value}", lang), "info"),
        theme_ui.badge(t(f"grill.step.{summary.step}", lang), step_tone),
        theme_ui.badge(t("grill.ui.saved_progress", lang, done=summary.answered, total=summary.total), "neutral"),
        theme_ui.badge(t("grill.ui.saved_open", lang, count=summary.unresolved), "warning") if summary.unresolved else "",
    )
    st.markdown(f"**{_md(summary.title or t('grill.ui.untitled', lang))}**")
    st.caption(t("grill.ui.saved_when", lang, time=_time(summary.updated_at)))


def _saved_interviews(lang: str) -> None:
    """Interviews of the open project: resume one, delete one, or load one from a file."""
    try:
        summaries = _store().interviews(active_project_id())
    except (OSError, ValueError):
        summaries = []
    unfinished = [s for s in summaries if not s.finished]
    finished = [s for s in summaries if s.finished]
    with theme_ui.card("grill_saved"):
        theme_ui.section(
            t("grill.ui.saved_heading", lang, count=len(unfinished)), ":material/bookmark:",
            t("grill.ui.saved_disk" if persistence_enabled() else "grill.ui.saved_session", lang),
        )
        if not unfinished:
            st.caption(t("grill.ui.saved_none", lang))
        for summary in unfinished:
            with st.container(border=True, key=f"grill_saved_{summary.session_id}"):
                _interview_line(lang, summary)
                with st.container(horizontal=True):
                    st.button(t("grill.ui.resume_interview", lang), key=f"grill_resume_{summary.session_id}",
                              icon=":material/play_arrow:", type="primary", on_click=_on_resume,
                              args=(summary.session_id,), help=t("grill.ui.resume_help", lang))
                    with st.popover(t("grill.ui.delete_interview", lang), icon=":material/delete:"):
                        st.caption(t("grill.ui.delete_confirm", lang))
                        st.button(t("grill.ui.delete_yes", lang), key=f"grill_delete_{summary.session_id}",
                                  on_click=_on_delete_interview, args=(summary.session_id,))
        if finished:
            with st.expander(t("grill.ui.finished_heading", lang, count=len(finished)), icon=":material/history:"):
                for summary in finished:
                    _interview_line(lang, summary)
                    st.button(t("grill.ui.open_interview", lang), key=f"grill_resume_{summary.session_id}",
                              icon=":material/visibility:", on_click=_on_resume, args=(summary.session_id,))
        st.file_uploader(
            t("grill.ui.import_label", lang), type=["json"], key=IMPORT, help=t("grill.ui.import_help", lang),
        )
        st.button(t("grill.ui.import_button", lang), key="grill_import", icon=":material/upload:",
                  disabled=st.session_state.get(IMPORT) is None, on_click=_on_import)


def _states_legend(lang: str) -> None:
    with theme_ui.card("grill_legend"):
        theme_ui.section(t("ui.grill.legend", lang), ":material/info:")
        for state in (ClarificationState.CONFIRMED, ClarificationState.ASSUMPTION,
                      ClarificationState.UNKNOWN, ClarificationState.CONFLICT):
            st.markdown(
                theme_ui.badge(t(f"grill.state.{state.value}", lang), STATE_TONES[state])
                + " " + _md(t(f"ui.grill.legend_{state.value}", lang))
            )


def _session_screen(
    lang: str,
    session: GrillSession,
    ai_config: AIConfig | None = None,
    workspace: Workspace | None = None,
    persist: Persist | None = None,
) -> None:
    center, right = st.columns(CENTER_RIGHT, gap="large")
    with center:
        _session_center(lang, session, ai_config, workspace, persist)
    with right:
        _insights_panel(lang, session, workspace)


def _session_center(
    lang: str, session: GrillSession, ai_config: AIConfig | None, workspace: Workspace | None, persist: Persist | None,
) -> None:
    _progress_card(lang, session, ai_config)
    if (unparsed := st.session_state.get(UNPARSED)) and not session.is_terminal:
        st.warning(t("grill.ui.unparsed", lang), icon=":material/help:")
        st.code("\n".join(unparsed), language=None)  # shown literally, never interpreted

    # Results are linked to requirements by ID, so a document the session was not started on must
    # be said out loud. A cancelled session has no result left to add or download.
    if session.artifact != ArtifactType.REQUIREMENTS and session.step != GrillStep.CANCELLED:
        if blocker := context_blocker(session, workspace):
            st.warning(t(f"grill.ui.{blocker}", lang), icon=":material/warning:")

    actions = allowed_actions(session)
    if ai_config is not None and not session.is_terminal and session.kind != GrillKind.REVIEW:
        _ai_interviewer(lang, session, ai_config, actions)
    step = session.step
    if step == GrillStep.ASK_QUESTION:
        _question_panel(lang, session, actions, workspace)
    elif step == GrillStep.SHOW_DRAFT:
        _draft_panel(lang, session, actions)
    elif step == GrillStep.REVIEW:
        _review_panel(lang, session, ai_config)
        _draft_panel(lang, session, actions)
    elif step == GrillStep.AWAITING_CONFIRMATION:
        _confirmation_panel(lang, session)
    elif step == GrillStep.FINALIZED:
        st.success(t("grill.ui.finalized", lang), icon=":material/verified:")
        _result_view(lang, session)
        _use_panel(lang, session, workspace, persist)
        _report_panel(lang, session, ai_config)
    elif step == GrillStep.CANCELLED:
        st.info(t("grill.ui.cancelled", lang), icon=":material/cancel:")

    if session.is_terminal:
        st.button(t("grill.ui.new_session", lang), type="primary", key="grill_new", on_click=_on_new_session)
        return
    if ai_config is not None and Action.ADD_QUESTIONS in actions:
        _ai_panel(lang, session, ai_config)
    _answers_panel(lang, session, actions)
    _issues_panel(lang, session)
    _footer(lang, session, actions)


def _progress_card(lang: str, session: GrillSession, ai_config: AIConfig | None) -> None:
    title = t(f"grill.kind.{session.kind.value}", lang)
    if session.kind == GrillKind.REVIEW:
        title += f" · {t(f'grill.artifact.{session.artifact.value}', lang)}"
    with theme_ui.card("grill_progress"):
        st.markdown(f"#### {_md(title)}")
        theme_ui.badges(
            theme_ui.badge(t(f"grill.step.{session.step.value}", lang), "accent", ":material/flag:"),
            theme_ui.badge(t("ui.grill.ai_on" if ai_config else "ui.grill.rules_only", lang), "neutral",
                           ":material/smart_toy:" if ai_config else ":material/rule:"),
        )
        if ai_config is None:
            st.caption(t("grill.ui.mode_deterministic", lang))
        else:
            st.caption(t("grill.ui.mode_ai_available", lang, model=_md(ai_config.model)))
        _save_controls(lang, session)
        done, total = session.progress
        if not total:
            return
        st.progress(done / total, text=t("grill.ui.progress", lang, done=done, total=total))
        counts = insights.interview_counts(session)
        cols = st.columns(4)
        for col, name, value in zip(cols, ("confirmed", "assumptions", "unknowns", "conflicts"), (
            counts.confirmed, counts.assumptions, counts.unknowns, counts.conflicts,
        ), strict=True):
            with col.container(key=f"kpi_{name}"):
                st.metric(t(f"ui.grill.count_{name}", lang), value)
        st.caption(t("ui.grill.open_count", lang, count=counts.open) + " · " + t("ui.grill.count_assumptions_help", lang))


def _save_controls(lang: str, session: GrillSession) -> None:
    """Where the interview is saved, and a file to continue it elsewhere or after a reload."""
    with st.container(horizontal=True, vertical_alignment="center", key="grill_save_controls"):
        where = "grill.ui.saved_on_disk" if persistence_enabled() else "grill.ui.saved_in_session"
        st.markdown(theme_ui.badge(t(where, lang, time=_time(session.updated_at)), "success", ":material/cloud_done:"))
        st.download_button(
            t("grill.ui.export_progress", lang), export_json(_record(session)),
            file_name=f"grill-interview-{session.id[:8]}.json", mime="application/json",
            icon=":material/save_alt:", key="grill_export", help=t("grill.ui.export_help", lang),
        )


# --- Interview ----------------------------------------------------------------

def _source_label(session: GrillSession, lang: str) -> str:
    if isinstance(session.draft, RequirementsDraft) and session.input_text.strip():
        return t("ui.grill.source_pasted", lang)
    return t("ui.grill.source_document", lang)


def _requirement_card(lang: str, session: GrillSession, question: Question, workspace: Workspace | None) -> None:
    requirement = insights.focus_requirement(session, question)
    with theme_ui.card("requirement"):
        head, link = st.columns([3, 2], vertical_alignment="center")
        head.markdown(f"**:material/description: {t('ui.grill.current_requirement', lang)}**")
        if requirement is None:
            st.caption(t("ui.grill.no_requirement", lang))
            return
        findings = insights.scope_findings(session, workspace)
        score = score_all([requirement], findings)[requirement.id]
        source = _source_label(session, lang)
        if requirement.source_line:
            source += " · " + t("ui.grill.line", lang, line=requirement.source_line)
        theme_ui.badges(
            theme_ui.badge(requirement.id, "accent"),
            theme_ui.badge(source, "neutral", ":material/source:"),
            theme_ui.badge(f"{t('column.quality', lang)} {score.score}/100", theme_ui.GRADE_TONES[score.grade]),
        )
        st.markdown("> " + _md(requirement.text).replace("\n", "\n> "))
        for rid in question.requirement_ids:
            other = next((r for r in insights.session_requirements(session) if r.id == rid), None)
            if other is not None and other.id != requirement.id:
                st.caption(_md(t("grill.ui.linked", lang, id=other.id, text=other.text)))
        with link.popover(t("ui.grill.full_requirement", lang), icon=":material/open_in_full:", width="stretch"):
            _full_requirement(lang, requirement, score, [f for f in findings if f.requirement_id == requirement.id])


def _full_requirement(lang: str, requirement: Requirement, score: QualityScore, findings: list[Finding]) -> None:
    st.markdown(f"**{_md(requirement.id)}**")
    st.markdown(_md(requirement.text))
    st.caption(t("ui.grill.quality_of", lang, score=score.score, grade=t(f"grade.{score.grade}", lang)))
    lost = [c for c in score.criteria if not c.passed]
    for criterion in lost:
        evidence = ", ".join(criterion.evidence)
        st.markdown(
            f"- {t(f'criterion.{criterion.key}', lang)}: {criterion.points}/{criterion.max_points}"
            + (f" — {_md(evidence)}" if evidence else "")
        )
    if not lost:
        st.caption(t("ui.grill.all_criteria_pass", lang))
    open_ones = insights.open_findings(findings)
    if open_ones:
        st.markdown(f"**{t('ui.grill.open_findings', lang)}**")
        for finding in open_ones:
            st.markdown(f"- {t(f'finding.{finding.type.value}', lang)} · {t(f'severity.{finding.severity.value}', lang)}")


def _question_panel(
    lang: str, session: GrillSession, actions: set[Action], workspace: Workspace | None = None
) -> None:
    question = session.current_question
    assert question is not None  # guaranteed in ASK_QUESTION
    rev = session.revision
    prompt, reason = render_question(question, lang)
    _requirement_card(lang, session, question, workspace)
    with theme_ui.card("question"):
        category = insights.question_category(question)
        category_label = t(f"finding.{category}", lang) if category in {
            "ambiguous_wording", "missing_expected_result", "missing_boundary", "missing_error_handling",
        } else t(f"ui.grill.category.{category}", lang)
        theme_ui.badges(
            theme_ui.badge(t("grill.ui.importance", lang, level=t(f"grill.importance.{question.priority}", lang)),
                           PRIORITY_TONES[question.priority], ":material/priority_high:"),
            theme_ui.badge(category_label, "accent", ":material/category:"),
            *(theme_ui.badge(rid, "info", ":material/link:") for rid in question.requirement_ids),
            theme_ui.badge(t("ui.grill.tag_required", lang), "neutral", ":material/lock:") if question.essential else "",
            theme_ui.badge(t("source.ai", lang), "accent", ":material/smart_toy:")
            if question.origin == Source.AI else "",
        )
        st.markdown(f"### {_md(prompt)}")
        if reason:
            st.caption(_md(t("grill.ui.why", lang, reason=reason)))
        if question.origin == Source.AI:
            st.caption(t("grill.ui.ai_question", lang))
        if question.is_decision:
            st.warning(t("grill.ui.conflict_question", lang), icon=":material/compare_arrows:")
        if question.id in session.answers:
            state = question_states(session)[question.id]
            st.caption(t("grill.ui.current_state", lang, state=f"{STATE_ICONS[state]} {t(f'grill.state.{state.value}', lang)}"))
        if question.essential:
            st.caption(t("grill.ui.essential", lang))

        previous = session.answers.get(question.id)
        previous_value = previous.value if previous else ""
        if not previous_value and session.draft is not None and question.field:
            # A question about a filled field (e.g. vague wording) starts from its current value.
            current = value_text(session.draft, question.field, lang)
            if current and not is_placeholder(current):
                previous_value = current
        choice_key = _key(session, "choice", question.id)
        text_key = _key(session, "text", question.id)
        list_hint = t("grill.ui.one_per_line", lang) if session.draft and question.field and is_list_field(
            session.draft, question.field) else None

        show_text = True
        if question.choices:
            options = [c.value for c in question.choices] + ([OTHER] if question.allow_free_text else [])
            labels = {c.value: render_choice(c, lang) for c in question.choices}
            index = None
            if previous_value in options:
                index = options.index(previous_value)
            elif previous_value and question.allow_free_text:
                index = options.index(OTHER)
            picked = st.radio(
                t("grill.ui.choice_label", lang), options, index=index, key=choice_key,
                format_func=lambda v: t("grill.ui.choice_other", lang) if v == OTHER else _md(labels[v]),
            )
            show_text = question.allow_free_text and picked == OTHER
        if show_text:
            st.text_area(
                t("grill.ui.answer_label", lang), key=text_key, help=list_hint, max_chars=MAX_TEXT_CHARS,
                value=previous_value if previous_value not in {c.value for c in question.choices} else "",
                placeholder=t("ui.grill.answer_placeholder", lang),
            )

        history = session.history
        position = history.index(question.id) if question.id in history else 0
        with st.container(horizontal=True, key="grill_actions"):  # wraps on narrow screens
            st.button(
                t("grill.ui.answer", lang), type="primary", key="grill_answer", icon=":material/send:",
                on_click=_on_answer, args=(rev, AnswerStatus.ANSWERED.value, choice_key, text_key),
            )
            st.button(
                t("grill.ui.assume", lang), key="grill_assume", icon=":material/help_center:",
                help=t("ui.grill.assume_help", lang),
                on_click=_on_answer, args=(rev, AnswerStatus.ASSUMED.value, choice_key, text_key),
            )
            st.button(
                t("grill.ui.unknown", lang), key="grill_unknown", icon=":material/question_mark:",
                help=t("ui.grill.unknown_help", lang),
                on_click=_on_answer, args=(rev, AnswerStatus.UNKNOWN.value, choice_key, text_key),
            )
            st.button(
                t("grill.ui.skip", lang), key="grill_skip", icon=":material/skip_next:", disabled=question.essential,
                help=t("ui.grill.skip_disabled" if question.essential else "ui.grill.skip_help", lang),
                on_click=_run, args=(WF.skip, rev),
            )
        with st.container(horizontal=True, key="grill_nav"):
            st.button(
                t("grill.ui.back", lang), key="grill_back", icon=":material/arrow_back:", type="tertiary",
                disabled=position == 0 or Action.BACK not in actions, on_click=_run, args=(WF.back, rev),
            )
            st.button(
                t("grill.ui.to_draft", lang), key="grill_to_draft", icon=":material/article:", type="tertiary",
                on_click=_run, args=(WF.proceed_to_draft, rev),
            )


def _issues_panel(lang: str, session: GrillSession) -> None:
    """Everything still open, highest priority first: unanswered, unknown or skipped
    questions, and contradictions (each has its own question, shown as a conflict)."""
    states = question_states(session)
    conflict_ids = {c.id for c in detect_conflicts(session) if not c.resolved}
    open_questions = sorted(
        (q for q in session.questions if states[q.id] in (ClarificationState.OPEN, ClarificationState.UNKNOWN)),
        key=lambda q: q.rank,
    )
    with st.expander(t("grill.ui.issues_heading", lang, count=len(open_questions)), icon=":material/pending_actions:"):
        if not open_questions:
            st.caption(t("grill.ui.no_issues", lang))
            return
        rows = []
        for question in open_questions:
            state = ClarificationState.CONFLICT if question.id in conflict_ids else states[question.id]
            rows.append({
                t("grill.ui.column_priority", lang): f"{PRIORITY_ICONS[question.priority]} {t(f'grill.importance.{question.priority}', lang)}",
                t("grill.ui.column_question", lang): render_question(question, lang)[0],
                t("grill.ui.column_requirements", lang): ", ".join(question.requirement_ids) or "—",
                t("grill.ui.column_state", lang): f"{STATE_ICONS[state]} {t(f'grill.state.{state.value}', lang)}",
            })
        _table(rows)


def _answers_panel(lang: str, session: GrillSession, actions: set[Action]) -> None:
    """Questions handled so far, with their answers and states; an answer can be reopened."""
    handled = [q for q in session.questions if q.id in session.answers]
    if not handled:
        _retired_list(lang, session)
        return
    with theme_ui.card("grill_previous"):
        theme_ui.section(t("ui.grill.previous", lang, count=len(handled)), ":material/history:")
        states = question_states(session)
        rows = []
        for question in handled:
            answer = session.answers[question.id]
            state = states[question.id]
            rows.append({
                t("grill.ui.column_question", lang): render_question(question, lang)[0],
                t("grill.ui.column_answer", lang): answer.value,
                t("grill.ui.column_status", lang): t(f"grill.answer_status.{answer.status.value}", lang),
                t("grill.ui.column_state", lang): f"{STATE_ICONS[state]} {t(f'grill.state.{state.value}', lang)}",
            })
        _table(rows)
        if Action.EDIT_ANSWER in actions:
            select_key = _key(session, "edit", session.revision)
            prompts = {q.id: render_question(q, lang)[0] for q in handled}
            cols = st.columns([3, 1], vertical_alignment="bottom")
            cols[0].selectbox(t("ui.grill.edit_which", lang), list(prompts), key=select_key, format_func=prompts.__getitem__)
            cols[1].button(
                t("grill.ui.edit_answer", lang), key="grill_edit_answer", icon=":material/edit:", width="stretch",
                on_click=_on_edit_answer, args=(session.revision, select_key),
            )
        _retired_list(lang, session)


def _retired_list(lang: str, session: GrillSession) -> None:
    """Open questions that left the queue (resolved in the document, answered by another answer, ...)."""
    if not session.retired:
        return
    with st.expander(t("grill.ui.retired_heading", lang, count=len(session.retired)), icon=":material/playlist_remove:"):
        for item in session.retired:
            detail = f"{item.reason.value}:{item.covered_by}" if item.covered_by else item.reason.value
            st.markdown(
                f"- {_md(render_question(item.question, lang)[0])} — _{_md(retire_reason_text(session, detail, lang))}_"
            )


# --- Draft, review and confirmation ----------------------------------------------------

def _draft_panel(lang: str, session: GrillSession, actions: set[Action]) -> None:
    draft = session.draft
    st.markdown(f"##### {t('grill.ui.draft_heading', lang)}")
    if session.reviewed_revision is not None and not session.review_is_current:
        st.warning(t("grill.ui.review_outdated", lang), icon=":material/update:")
    if isinstance(draft, RequirementsDraft):
        _requirements_view(lang, draft)
    elif draft is not None:
        _draft_editor(lang, session, draft)
    if session.step == GrillStep.SHOW_DRAFT and session.pending_questions:
        st.button(
            t("grill.ui.continue", lang), key="grill_continue", icon=":material/forum:",
            on_click=_run, args=(WF.continue_interview, session.revision),
        )


def _draft_editor(lang: str, session: GrillSession, draft: TestCaseDraft | BugReportDraft) -> None:
    raw: dict[str, str | None] = {}
    with st.form(key=_key(session, "form", session.draft_revision), border=True):
        for field in editable_fields(draft):
            key = _key(session, "field", session.draft_revision, field)
            label = field_label(field, lang)
            value = getattr(draft, field)
            if field == "requirement_id" and session.context_requirements:
                options = ["", *[r.id for r in session.context_requirements]]
                if value and value not in options:
                    options.append(value)  # keep what the user wrote visible; the review flags it
                raw[field] = st.selectbox(label, options, index=options.index(value), key=key,
                                          format_func=lambda v: v or t("grill.ui.not_set", lang))
            elif field in CHOICE_FIELDS:
                values, prefix = CHOICE_FIELDS[field]
                options = ["", *values]
                current = value.value if value is not None else ""
                names = {v: t(f"{prefix}.{v}", lang) for v in values} | {"": t("grill.ui.not_set", lang)}
                raw[field] = st.selectbox(label, options, index=options.index(current), key=key,
                                          format_func=names.__getitem__)
            elif is_list_field(draft, field):
                raw[field] = st.text_area(label, value="\n".join(value), key=key, help=t("grill.ui.one_per_line", lang),
                                          max_chars=MAX_TEXT_CHARS)
            elif field in SHORT_TEXT_FIELDS:
                raw[field] = st.text_input(label, value=value, key=key, max_chars=MAX_TEXT_CHARS)
            else:
                raw[field] = st.text_area(label, value=value, key=key, height=100, max_chars=MAX_TEXT_CHARS)
            if origin := provenance_label(draft, field, lang):
                st.caption(t("grill.ui.origin", lang, origin=origin))
        submitted = st.form_submit_button(t("grill.ui.save_draft", lang), type="primary", icon=":material/save:")
    if submitted:  # handled inline like the app's other forms, then shown fresh
        _save_draft(session.revision, raw)
        st.rerun()


def _requirements_view(lang: str, draft: RequirementsDraft) -> None:
    st.caption(t("grill.ui.source_requirements", lang))
    _table([
        {t("grill.ui.column_requirements", lang): r.id, t("grill.ui.column_value", lang): r.text}
        for r in draft.requirements
    ])
    st.markdown(f"**{t('grill.field.statements', lang)}**")
    if not draft.statements:
        st.caption(t("grill.ui.no_statements", lang))
        return
    _table([
        {
            t("grill.ui.column_clarification", lang): s.text,
            t("grill.ui.column_requirements", lang): ", ".join(s.requirement_ids),
            t("grill.ui.column_origin", lang): t(f"grill.provenance.{s.provenance.value}", lang),
        }
        for s in draft.statements
    ])


def _findings_table(lang: str, findings: list[ReviewFinding]) -> None:
    with_source = any(f.origin == Source.AI for f in findings)
    rows = []
    for finding in findings:
        message, fix = render_finding(finding, lang)
        if quote := finding.params.get("quote"):
            message = f"“{quote}” — {message}"
        where = ", ".join(x for x in (field_label(finding.field, lang), ", ".join(finding.requirement_ids)) if x)
        row = {
            t("grill.ui.column_category", lang): t(f"grill.category.{finding.category.value}", lang),
            t("grill.ui.column_where", lang): where,
            t("grill.ui.column_issue", lang): message,
            t("grill.ui.column_fix", lang): fix,
        }
        if with_source:
            row[t("column.source", lang)] = t(f"source.{finding.origin.value}", lang)
        rows.append(row)
    _table(rows)


def _review_panel(lang: str, session: GrillSession, ai_config: AIConfig | None = None) -> None:
    findings = session.findings
    with st.container(border=True, key="grill_review"):
        st.markdown(f"##### {t('grill.ui.findings_heading', lang)}")
        if any(f.origin == Source.AI for f in findings):
            model = ai_config.model if ai_config else "AI"
            st.warning(t("grill.ui.ai_findings_note", lang, model=_md(model)), icon=":material/smart_toy:")
        by_level = {level: [f for f in findings if f.level == level] for level in FindingLevel}
        st.caption(t(
            "grill.ui.findings_summary", lang, blocking=len(by_level[FindingLevel.BLOCKING]),
            warnings=len(by_level[FindingLevel.WARNING]), suggestions=len(by_level[FindingLevel.SUGGESTION]),
        ))
        if not findings:
            st.success(t("grill.ui.no_findings", lang), icon=":material/check_circle:")
        for level, items in by_level.items():
            if items:
                st.markdown(f"**{LEVEL_ICONS[level]} {t(f'grill.level.{level.value}', lang)}**")
                _findings_table(lang, items)

        blocked = bool(by_level[FindingLevel.BLOCKING])
        accepted = True
        if blocked:
            st.error(t("grill.ui.blocked", lang), icon=":material/block:")
        elif by_level[FindingLevel.WARNING]:
            accept_key = _key(session, "accept", session.reviewed_revision)
            accepted = st.checkbox(t("grill.ui.accept_unresolved", lang), key=accept_key)
        cols = st.columns(2)
        cols[0].button(
            t("grill.ui.request_confirmation", lang), type="primary", key="grill_request_confirmation",
            width="stretch", disabled=blocked or not accepted,
            on_click=_on_request_confirmation, args=(session.revision, _key(session, "accept", session.reviewed_revision)),
        )
        cols[1].button(
            t("grill.ui.resume", lang), key="grill_resume", width="stretch",
            on_click=_run, args=(WF.resume, session.revision),
        )


def _confirmation_panel(lang: str, session: GrillSession) -> None:
    with st.container(border=True, key="grill_confirm"):
        st.markdown(f"##### {t('grill.ui.confirm_heading', lang)}")
        st.caption(t("grill.ui.confirm_body", lang))
        _result_view(lang, session)
        if session.accepted_unresolved:
            st.warning(t("grill.ui.unresolved_accepted", lang, count=len(session.warning_findings)))
            _findings_table(lang, session.warning_findings)
        cols = st.columns(2)
        cols[0].button(
            t("grill.ui.confirm", lang), type="primary", key="grill_confirm_button", icon=":material/verified:",
            width="stretch", on_click=_run, args=(WF.confirm, session.revision),
        )
        cols[1].button(
            t("grill.ui.resume", lang), key="grill_resume", width="stretch",
            on_click=_run, args=(WF.resume, session.revision),
        )


def _result_view(lang: str, session: GrillSession) -> None:
    draft = session.draft
    if isinstance(draft, RequirementsDraft):
        _requirements_view(lang, draft)
    elif draft is not None:
        _table([
            {
                t("grill.ui.column_field", lang): label,
                t("grill.ui.column_value", lang): value or "—",
                t("grill.ui.column_origin", lang): origin,
            }
            for label, value, origin in draft_rows(draft, lang)
        ])


def _use_panel(lang: str, session: GrillSession, workspace: Workspace | None, persist: Persist | None) -> None:
    """Download the confirmed result, or hand it to the analysis workspace."""
    with st.container(border=True, key="grill_use"):
        st.markdown(f"##### {t('grill.ui.use_heading', lang)}")
        report = build_report(session, lang, _ai_tests(session))
        st.download_button(
            t("grill.ui.download_markdown", lang),
            result_markdown(session, lang) + "\n" + report_markdown(report, lang) + "\n" + trace_markdown(session, lang),
            file_name=markdown_file_name(session), mime="text/markdown", icon=":material/download:",
            key="grill_download", help=t("grill.report.download_tooltip", lang),
        )
        if persist is None:
            return
        if isinstance(session.draft, RequirementsDraft):
            _resolve_panel(lang, session, workspace, persist)
            return
        blocker = add_blocker(session, workspace)
        st.button(
            t(f"grill.ui.add_{session.artifact.value}", lang), type="primary", key="grill_add",
            icon=":material/add_task:", disabled=blocker is not None,
            on_click=_on_add_to_workspace, args=(session.revision, lang, persist),
        )
        if blocker is not None:
            st.caption(t(f"grill.error.{blocker}", lang))


def _resolve_panel(lang: str, session: GrillSession, workspace: Workspace | None, persist: Persist) -> None:
    """Opt-in, per clarification: nothing is resolved unless the user ticks it."""
    st.markdown(f"**{t('grill.ui.resolve_heading', lang)}**")
    if (blocker := resolve_blocker(session, workspace)) is not None:
        st.caption(t(f"grill.error.{blocker}", lang))
        return
    options = resolutions(session, workspace)
    if not options:
        st.caption(t("grill.ui.no_resolutions", lang))
        return
    st.caption(t("grill.ui.resolve_explainer", lang))
    keys = {}
    for option in options:
        keys[option.question_id] = _key(session, "resolve", option.question_id)
        label = f"{', '.join(option.requirement_ids)} — {option.clarification}"
        st.checkbox(_md(label), value=False, key=keys[option.question_id])
    reason_key = _key(session, "resolve_reason")
    st.text_input(t("findings.reason_label", lang), key=reason_key, max_chars=MAX_REASON_LENGTH,
                  placeholder=t("findings.reason_placeholder", lang))
    st.button(
        t("grill.ui.resolve_button", lang), key="grill_resolve", icon=":material/task_alt:",
        disabled=not any(st.session_state.get(k) for k in keys.values()),
        on_click=_on_resolve, args=(session.revision, persist, keys, reason_key),
    )
    st.caption(t("grill.ui.resolve_undo_hint", lang))


# --- Optional AI ------------------------------------------------------------------------

def _ai_panel(lang: str, session: GrillSession, config: AIConfig) -> None:
    """Ask the model for questions or a review; each request needs a fresh consent."""
    with st.expander(t("grill.ui.ai_heading", lang), icon=":material/smart_toy:"):
        st.caption(t("grill.ui.ai_explainer", lang))
        what = "requirements" if isinstance(session.draft, RequirementsDraft) else "draft"
        consent = st.checkbox(
            t(f"grill.ui.ai_consent_{what}", lang, provider=config.provider_name, model=_md(config.model)),
            key=_key(session, "ai_consent", st.session_state.get(AI_RUNS, 0)),
        )
        can_review = session.step == GrillStep.REVIEW and session.review_is_current
        cols = st.columns(2)
        ask = cols[0].button(
            t("grill.ui.ai_questions", lang), key="grill_ai_questions", icon=":material/forum:",
            width="stretch", disabled=not consent,
        )
        review = cols[1].button(
            t("grill.ui.ai_review", lang), key="grill_ai_review", icon=":material/fact_check:",
            width="stretch", disabled=not consent or not can_review,
        )
        if not can_review:
            st.caption(t("grill.ui.ai_review_needs_review", lang))
        if ask or review:
            _run_ai(lang, session, config, consent, questions=ask)
            st.rerun()


def _run_ai(lang: str, session: GrillSession, config: AIConfig, consent: bool, *, questions: bool) -> None:
    st.session_state[AI_RUNS] = st.session_state.get(AI_RUNS, 0) + 1  # ask for consent again next time
    try:
        with st.spinner(t("ai.running", lang)):
            if questions:
                found = grill_ai.suggest_questions(session, config, consent, lang)
            else:
                findings = grill_ai.review_draft(session, config, consent, lang)
        if questions:
            if not found:
                _notice("grill.ui.ai_no_questions")
                return
            _save(WF.add_questions(session, found, expected_revision=session.revision))
            _notice("grill.ui.ai_questions_added", count=len(found))
        else:
            _save(WF.add_ai_findings(session, findings, expected_revision=session.revision))
            if findings:
                _notice("grill.ui.ai_findings_added", count=len(findings))
            else:
                _notice("grill.ui.ai_no_findings")
    except AIError as exc:
        _error(f"ai.error.{exc.code}")
    except GrillError as exc:
        _error(f"grill.error.{exc.code}")


def _ai_interviewer(lang: str, session: GrillSession, config: AIConfig, actions: set[Action]) -> None:
    """Switch on the AI interviewer; while on, ask it for the next question whenever one is due."""
    with st.container(border=True, key="grill_ai_interviewer"):
        on = st.checkbox(
            t("grill.ui.ai_interviewer", lang, provider=config.provider_name, model=_md(config.model)),
            key=_key(session, "ai_interviewer"), help=t("grill.ui.ai_interviewer_help", lang),
        )
        if not on:
            return
        fingerprint = grill_ai.interview_fingerprint(session)
        if grill_ai.wants_next_question(session) and st.session_state.get(AI_ASKED) != fingerprint:
            _ask_next(lang, session, config)  # once per interview state, so a failure is not retried in a loop
            st.rerun()
        if Action.ADD_QUESTIONS in actions and session.step != GrillStep.ASK_QUESTION:
            st.caption(t("grill.ui.ai_interviewer_idle", lang))
            if st.button(t("grill.ui.ai_next", lang), key="grill_ai_next", icon=":material/forum:"):
                _ask_next(lang, session, config, explicit=True)
                st.rerun()


def _ask_next(lang: str, session: GrillSession, config: AIConfig, *, explicit: bool = False) -> None:
    """Ask the interviewer for one question. Automatic requests join the ranked queue;
    an explicit request (the button) asks the new question at once."""
    st.session_state[AI_ASKED] = grill_ai.interview_fingerprint(session)
    try:
        with st.spinner(t("grill.ui.ai_thinking", lang)):
            question = grill_ai.next_question(session, config, True, lang)
        if question is None:
            if explicit or session.step == GrillStep.SHOW_DRAFT:  # only say so when the interview would end
                _notice("grill.ui.ai_interview_done")
            return
        if explicit:
            _save(WF.add_questions(session, [question], expected_revision=session.revision))
        else:
            _save(WF.merge_questions(session, [question], expected_revision=session.revision))
    except AIError as exc:
        _error(f"ai.error.{exc.code}")
        _notice("grill.ui.ai_fallback")
    except GrillError as exc:
        _error(f"grill.error.{exc.code}")


# --- Final report ----------------------------------------------------------------------

def _report_panel(lang: str, session: GrillSession, ai_config: AIConfig | None) -> None:
    """Confirmed facts, assumptions and unknowns kept apart, plus suggested test cases."""
    report = build_report(session, lang, _ai_tests(session))
    with st.container(border=True, key="grill_report"):
        st.markdown(f"##### {t('grill.report.title', lang)}")
        st.caption(t("grill.report.note", lang))
        if report.clarified_requirements:
            st.markdown(f"**{t('grill.report.clarified', lang)}**")
            _table([
                {
                    t("column.id", lang): r.id,
                    t("column.requirement", lang): r.text,
                    t("grill.report.col_confirmed", lang): "; ".join(r.confirmed) or "—",
                    t("grill.report.col_assumed", lang): "; ".join(r.assumed) or "—",
                    t("grill.report.col_open", lang): "; ".join(r.open) or "—",
                }
                for r in report.clarified_requirements
            ])
        for key, items, icon in (
            ("grill.report.confirmed", report.confirmed, "✅"),
            ("grill.report.assumptions", report.assumptions, "🟡"),
            ("grill.report.unknowns", report.unknowns, "❓"),
        ):
            st.markdown(f"**{icon} {t(key, lang)}** ({len(items)})")
            if not items:
                st.caption(t("grill.report.none", lang))
                continue
            _table([
                {
                    t("grill.report.col_statement", lang): i.text,
                    t("grill.ui.column_origin", lang): origin_label(i.origin, lang),
                    t("grill.ui.column_where", lang): i.where or "—",
                    t("grill.ui.column_requirements", lang): ", ".join(i.requirement_ids) or "—",
                }
                for i in items
            ])
        st.markdown(f"**⚔️ {t('grill.report.contradictions', lang)}** ({len(report.contradictions)})")
        if report.contradictions:
            _table([
                {
                    t("grill.report.col_conflicting", lang): " ⟷ ".join(c.statements),
                    t("grill.ui.column_requirements", lang): ", ".join(c.requirement_ids) or "—",
                    t("grill.report.col_decision", lang): contradiction_status(c, lang),
                }
                for c in report.contradictions
            ])
        else:
            st.caption(t("grill.report.none", lang))
        _suggested_tests(lang, report)
        if ai_config is not None:
            _ai_test_ideas(lang, session, ai_config)
        st.caption(t("grill.report.download_help", lang))


def _ai_tests(session: GrillSession) -> list[SuggestedTestCase]:
    stored = st.session_state.get(AI_TESTS) or {}
    return [SuggestedTestCase.model_validate(item) for item in stored.get(session.id, [])]


def _suggested_tests(lang: str, report: GrillReport) -> None:
    st.markdown(f"**🧪 {t('grill.report.tests', lang)}** ({len(report.suggested_tests)})")
    if not report.suggested_tests:
        st.caption(t("grill.report.no_tests", lang))
        return
    st.caption(t("grill.report.tests_note", lang))
    _table([
        {
            t("column.title", lang): case.title,
            t("grill.ui.column_requirements", lang): ", ".join(case.requirement_ids),
            t("grill.report.col_kind", lang): case_label(case, lang),
            t("grill.field.steps", lang): "\n".join(f"{n}. {step}" for n, step in enumerate(case.steps, start=1)),
            t("grill.field.expected_result", lang): case.expected_result,
        }
        for case in report.suggested_tests
    ])


def _ai_test_ideas(lang: str, session: GrillSession, config: AIConfig) -> None:
    what = "requirements" if isinstance(session.draft, RequirementsDraft) else "draft"
    consent = st.checkbox(
        t(f"grill.ui.ai_consent_{what}", lang, provider=config.provider_name, model=_md(config.model)),
        key=_key(session, "ai_tests_consent", st.session_state.get(AI_RUNS, 0)),
    )
    if not st.button(
        t("grill.report.ai_tests", lang), key="grill_ai_tests", icon=":material/science:", disabled=not consent,
    ):
        return
    st.session_state[AI_RUNS] = st.session_state.get(AI_RUNS, 0) + 1  # ask for consent again next time
    try:
        with st.spinner(t("ai.running", lang)):
            found = grill_ai.suggest_test_cases(session, config, consent, lang)
    except AIError as exc:
        _error(f"ai.error.{exc.code}")
    else:
        # One list per Grill session, replaced by the next request.
        st.session_state[AI_TESTS] = {session.id: [case.model_dump(mode="json") for case in found]}
        _save(session)  # keep the ideas with the saved interview
        _notice("grill.report.ai_tests_added" if found else "grill.report.ai_tests_none", count=len(found))
    st.rerun()


def _footer(lang: str, session: GrillSession, actions: set[Action]) -> None:
    cols = st.columns(3)
    if Action.REVIEW in actions:
        cols[0].button(
            t("grill.ui.review", lang), key="grill_review_button", icon=":material/fact_check:",
            width="stretch", on_click=_run, args=(WF.review, session.revision),
        )
    cols[1].button(
        t("grill.ui.close_interview", lang), key="grill_close", icon=":material/bookmark_added:", width="stretch",
        on_click=_on_new_session, help=t("grill.ui.close_help", lang),
    )
    with cols[2].popover(t("grill.ui.cancel", lang), icon=":material/close:", width="stretch"):
        st.caption(t("grill.ui.cancel_confirm", lang))
        st.button(
            t("grill.ui.cancel_yes", lang), key="grill_cancel", on_click=_run, args=(WF.cancel, session.revision),
        )


# --- Analysis panel (right column) ------------------------------------------------------

def _insights_panel(lang: str, session: GrillSession, workspace: Workspace | None) -> None:
    """Analysis / Findings / Report beside the interview, all derived from the session."""
    requirements = insights.session_requirements(session)
    findings = insights.scope_findings(session, workspace)
    conflicts = detect_conflicts(session)
    question = session.current_question if session.step == GrillStep.ASK_QUESTION else None
    focus = insights.focus_requirement(session, question)
    groups = insights.group_findings(findings)
    tab_analysis, tab_findings, tab_report, tab_history = st.tabs([
        t("ui.grill.tab_analysis", lang), t("ui.grill.tab_findings", lang), t("ui.grill.tab_report", lang),
        t("grill.trace.tab", lang),
    ])
    with tab_analysis:
        theme_ui.quality_card(
            lang, list(score_all(requirements, findings).values()), "grill_quality", t("ui.grill.quality_note", lang),
        )
        with theme_ui.card("grill_open_items"):
            theme_ui.section(t("ui.grill.open_items", lang), ":material/report:")
            risks = [f for f in session.findings if f.level != FindingLevel.SUGGESTION]
            theme_ui.badges(
                theme_ui.badge(t("ui.grill.ambiguities_n", lang, count=len(groups.ambiguities)), "warning"),
                theme_ui.badge(t("ui.grill.missing_n", lang, count=len(groups.missing)), "info"),
                theme_ui.badge(t("ui.grill.contradictions_n", lang,
                                 count=len(groups.contradictions) + sum(c.kind.value != "source" for c in conflicts if not c.resolved)),
                               "danger"),
                theme_ui.badge(t("ui.grill.risks_n", lang, count=len(risks)), "neutral"),
            )
        _assumptions_card(lang, session, limit=5)
        _unresolved_card(lang, session, limit=5)
        _related_card(lang, session, focus, findings, conflicts)
    with tab_findings:
        _findings_lists(lang, session, groups, conflicts)
    with tab_report:
        _live_report(lang, session)
    with tab_history:
        _history_panel(lang, session)


def _history_panel(lang: str, session: GrillSession) -> None:
    """Where every decision came from, its state, and every change made to it.

    Drawn as a compact list (the panel is narrow); the downloads hold the full table.
    """
    records = decision_records(session, lang)
    counts = state_counts(records)
    with theme_ui.card("grill_trace"):
        theme_ui.section(t("grill.trace.heading", lang), ":material/account_tree:", t("grill.trace.note", lang))
        theme_ui.badges(*(
            theme_ui.badge(f"{t(f'grill.state.{state.value}', lang)}: {counts[state]}", STATE_TONES[state])
            for state in ClarificationState
        ))
        if not records:
            st.caption(t("grill.trace.none", lang))
        for n, record in enumerate(records):
            changes = len(record.history) - 1
            answer = f"{t('grill.ui.column_answer', lang)}: {record.value}" if record.value else ""
            source = origin_text(record, lang) + (f" — {record.basis}" if record.basis else "")
            theme_ui.list_item(
                f"trace_{n}",
                [
                    theme_ui.badge(t(f"grill.state.{record.state.value}", lang), STATE_TONES[record.state]),
                    theme_ui.badge(t("grill.trace.superseded", lang), "neutral") if record.superseded else "",
                    *(theme_ui.badge(rid, "info") for rid in record.requirement_ids),
                    theme_ui.badge(t("grill.trace.changed_n", lang, count=changes), "accent") if changes > 0 else "",
                ],
                record.question,
                "\n".join(x for x in (answer, f"{t('grill.trace.col_source', lang)}: {source}") if x),
            )
        changed = [r for r in records if len(r.history) > 1]
        if changed:
            options = {r.question_id: r for r in changed}
            picked = st.selectbox(
                t("grill.trace.pick_history", lang), list(options), key=_key(session, "trace_pick"),
                format_func=lambda qid: options[qid].question,
            )
            for n, rev in enumerate(options[picked].history if picked else []):
                theme_ui.list_item(
                    f"trace_rev_{n}",
                    [theme_ui.badge(_time(rev.at), "neutral"),
                     theme_ui.badge(t(f"grill.answer_status.{rev.status.value}", lang), "info")],
                    rev.value or "—",
                )
    with theme_ui.card("grill_audit"):
        theme_ui.section(t("grill.audit.heading", lang, count=len(session.events)), ":material/history:",
                         t("grill.audit.note", lang))
        rows = audit_rows(session, lang)
        time_col, action_col, detail_col = (t(f"grill.audit.col_{c}", lang) for c in ("time", "action", "detail"))
        for n, row in enumerate(rows[:12]):
            theme_ui.list_item(f"audit_{n}", [theme_ui.badge(row[time_col], "neutral"),
                                              theme_ui.badge(row[action_col], "accent")], row[detail_col])
        if len(rows) > 12:
            with st.expander(t("grill.audit.all", lang, count=len(rows))):
                _table(rows)
        if not rows:
            st.caption(t("grill.trace.none", lang))
        st.download_button(
            t("grill.audit.download", lang), audit_json(session, lang), file_name=audit_file_name(session),
            mime="application/json", icon=":material/download:", key="grill_audit_download",
            help=t("grill.audit.download_help", lang),
        )


def _assumptions_card(lang: str, session: GrillSession, limit: int | None = None) -> None:
    assumed = insights.assumed_answers(session)
    draft_assumptions = list(session.draft.assumptions) if session.draft is not None else []
    with theme_ui.card(f"grill_assumptions_{limit or 'all'}"):
        theme_ui.section(t("ui.grill.active_assumptions", lang, count=len(assumed) + len(draft_assumptions)),
                         ":material/help_center:", t("ui.grill.assumptions_note", lang))
        if not assumed and not draft_assumptions:
            st.caption(t("ui.grill.none_yet", lang))
            return
        items = [(render_question(q, lang)[0], value, q.requirement_ids) for q, value in assumed]
        items += [("", value, []) for value in draft_assumptions]
        for n, (prompt, value, ids) in enumerate(items[:limit]):
            theme_ui.list_item(
                f"assumption_{limit or 'all'}_{n}",
                [theme_ui.badge(t("grill.state.assumption", lang), "warning"), *(theme_ui.badge(rid, "info") for rid in ids)],
                value, prompt,
            )
        if limit is not None and len(items) > limit:
            st.caption(t("ui.grill.more_in_report", lang, count=len(items) - limit))


def _unresolved_card(lang: str, session: GrillSession, limit: int | None = None) -> None:
    waiting = insights.unresolved(session)
    states = question_states(session)
    with theme_ui.card(f"grill_unresolved_{limit or 'all'}"):
        theme_ui.section(t("ui.grill.unresolved", lang, count=len(waiting)), ":material/pending_actions:")
        if not waiting:
            st.caption(t("grill.ui.no_issues", lang))
            return
        for n, question in enumerate(waiting[:limit]):
            state = states[question.id]
            theme_ui.list_item(
                f"unresolved_{limit or 'all'}_{n}",
                [
                    theme_ui.badge(t(f"grill.importance.{question.priority}", lang), PRIORITY_TONES[question.priority]),
                    theme_ui.badge(t(f"grill.state.{state.value}", lang), STATE_TONES[state]),
                    *(theme_ui.badge(rid, "info") for rid in question.requirement_ids),
                ],
                render_question(question, lang)[0],
            )
        if limit is not None and len(waiting) > limit:
            st.caption(t("ui.grill.more_in_report", lang, count=len(waiting) - limit))


def _related_card(
    lang: str, session: GrillSession, focus: Requirement | None, findings: list[Finding], conflicts: list[Conflict]
) -> None:
    with theme_ui.card("grill_related"):
        theme_ui.section(t("ui.grill.related", lang), ":material/hub:")
        if focus is None:
            st.caption(t("ui.grill.no_requirement", lang))
            return
        related = insights.related_requirements(session, focus.id, findings, conflicts)
        st.caption(t("ui.grill.related_to", lang, id=focus.id))
        if not related:
            st.caption(t("ui.grill.no_related", lang))
        for requirement in related:
            st.markdown(f"{theme_ui.badge(requirement.id, 'info', ':material/link:')} {_md(requirement.text)}")


def _finding_line(lang: str, finding: Finding, states: dict[str, ClarificationState]) -> None:
    """One open rule finding, with what the interview made of it so far (if anything)."""
    terms = ", ".join(f"“{term}”" for term in finding.matched_terms)
    state = states.get(rule_question_id(finding), ClarificationState.OPEN)
    decided = "" if state == ClarificationState.OPEN else " " + theme_ui.badge(
        t("ui.grill.in_interview", lang, state=t(f"grill.state.{state.value}", lang)), STATE_TONES[state],
    )
    st.markdown(
        theme_ui.badge(finding.requirement_id, "info")
        + " " + theme_ui.badge(t(f"severity.{finding.severity.value}", lang),
                               {"high": "danger", "medium": "warning", "low": "neutral"}[finding.severity.value])
        + f" **{t(f'finding.{finding.type.value}', lang)}**" + (f" — {_md(terms)}" if terms else "") + decided
    )
    st.caption(_md(clarification_question(finding, lang)))


def _findings_lists(lang: str, session: GrillSession, groups: insights.FindingGroups, conflicts: list[Conflict]) -> None:
    st.caption(t("results.rule_disclaimer", lang))
    states = question_states(session)
    for key, items in (("ambiguities", groups.ambiguities), ("missing", groups.missing)):
        with theme_ui.card(f"grill_findings_{key}"):
            theme_ui.section(t(f"ui.grill.{key}", lang, count=len(items)), "")
            if not items:
                st.caption(t("ui.grill.nothing_found", lang))
            for finding in items:
                _finding_line(lang, finding, states)
    with theme_ui.card("grill_findings_contradictions"):
        interview = [c for c in conflicts if c.kind.value != "source"]
        theme_ui.section(t("ui.grill.contradictions", lang, count=len(groups.contradictions) + len(interview)), "")
        if not groups.contradictions and not interview:
            st.caption(t("ui.grill.nothing_found", lang))
        for finding in groups.contradictions:
            _finding_line(lang, finding, states)
        for conflict in interview:
            tone, label = ("success", "ui.grill.conflict_resolved") if conflict.resolved else ("danger", "ui.grill.conflict_open")
            st.markdown(
                theme_ui.badge(t(label, lang), tone)
                + "".join(" " + theme_ui.badge(rid, "info") for rid in conflict.requirement_ids)
                + " " + " ⟷ ".join(f"“{_md(text)}”" for text in conflict.statements)
            )
    with theme_ui.card("grill_findings_risks"):
        risks = [f for f in session.findings if f.level != FindingLevel.SUGGESTION]
        theme_ui.section(t("ui.grill.risks", lang, count=len(risks)), "", t("ui.grill.risks_note", lang))
        if session.reviewed_revision is None:
            st.caption(t("ui.grill.risks_after_review", lang))
        elif not risks:
            st.caption(t("ui.grill.nothing_found", lang))
        for review in risks:
            message, fix = render_finding(review, lang)
            st.markdown(
                theme_ui.badge(t(f"grill.level.{review.level.value}", lang), LEVEL_TONES[review.level])
                + " " + theme_ui.badge(t(f"grill.category.{review.category.value}", lang), "neutral")
                + f" {_md(message)}"
            )
            if fix:
                st.caption(_md(fix))


def _live_report(lang: str, session: GrillSession) -> None:
    """What the final report will say so far: facts, assumptions and open points kept apart."""
    if session.step == GrillStep.FINALIZED:
        st.success(t("ui.grill.report_final", lang), icon=":material/description:")
    else:
        st.caption(t("ui.grill.report_live", lang))
    states = question_states(session)
    confirmed = [(q, session.answers[q.id].value) for q in session.questions if states[q.id] == ClarificationState.CONFIRMED]
    with theme_ui.card("grill_report_confirmed"):
        theme_ui.section(t("ui.grill.confirmed", lang, count=len(confirmed)), ":material/check_circle:")
        if not confirmed:
            st.caption(t("ui.grill.none_yet", lang))
        for question, value in confirmed:
            st.markdown(
                theme_ui.badge(t("grill.state.confirmed", lang), "success")
                + "".join(" " + theme_ui.badge(rid, "info") for rid in question.requirement_ids)
                + f" {_md(value)}"
            )
    _assumptions_card(lang, session)
    _unresolved_card(lang, session)
