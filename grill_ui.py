"""Grill Mode page for the Streamlit app.

Rendering only: every decision is made by `spec_to_test.grill` (workflow,
planner, validation). The session lives in this browser session's
`st.session_state`, so users never share state, and it survives ordinary
reruns. Buttons use callbacks that pass the revision the page was rendered
with, so a double click or an outdated page is rejected instead of applied.

AI is optional. It is offered only when configured, and every request needs
a fresh consent tick; the model is called from `spec_to_test.grill.ai`, and
its output enters the session only through the workflow's AI transitions.
"""

from collections.abc import Callable
from typing import Any

import streamlit as st

from spec_to_test.ai_analysis import AIConfig, AIError
from spec_to_test.formatting import escape_markdown
from spec_to_test.grill import ai as grill_ai
from spec_to_test.grill.drafts import DraftError, draft_from_text, editable_fields, is_list_field
from spec_to_test.grill.inputs import parse_draft, requirements_draft
from spec_to_test.grill.models import (
    DRAFT_TYPES,
    AnswerStatus,
    ArtifactType,
    BugReportDraft,
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
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW
from spec_to_test.grill.text import (
    draft_rows,
    field_label,
    provenance_label,
    render_choice,
    render_finding,
    render_question,
    value_text,
)
from spec_to_test.grill.validation import is_placeholder
from spec_to_test.grill.workflow import Action, GrillError, allowed_actions
from spec_to_test.i18n import t
from spec_to_test.input_parser import InputError
from spec_to_test.models import Requirement, Severity, Source, TestType, Workspace

WF = DETERMINISTIC_WORKFLOW
STATE = "grill_session"
ERROR = "grill_error"  # (translation key, params), shown once on the next run
UNPARSED = "grill_unparsed"
NOTICE = "grill_notice"  # (translation key, params), shown once on the next run
AI_RUNS = "grill_ai_runs"  # part of the consent checkbox key, so consent resets after every request
OTHER = "__other__"

LEVEL_ICONS = {FindingLevel.BLOCKING: "⛔", FindingLevel.WARNING: "⚠️", FindingLevel.SUGGESTION: "💡"}
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

def _save(session: GrillSession) -> None:
    st.session_state[STATE] = session.model_dump(mode="json")


def _current() -> GrillSession | None:
    return load_session(st.session_state.get(STATE))


def _error(key: str, **params: Any) -> None:
    st.session_state[ERROR] = (key, params)


def _notice(key: str, **params: Any) -> None:
    st.session_state[NOTICE] = (key, params)


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

def _on_start(kind: str, mode: str, artifact: str, use_analyzed: bool, context: list[Requirement]) -> None:
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
    )
    _save(WF.submit_input(session, draft, text))
    st.session_state[UNPARSED] = unparsed


def _on_new_session() -> None:
    st.session_state.pop(STATE, None)
    st.session_state.pop(UNPARSED, None)


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


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def render_grill(lang: str, workspace: Workspace | None, ai_config: AIConfig | None = None) -> None:
    st.subheader(t("grill.ui.heading", lang))
    st.caption(t("grill.ui.intro", lang))
    if ai_config is None:
        st.info(t("grill.ui.mode_deterministic", lang), icon=":material/rule:")
    else:
        st.info(t("grill.ui.mode_ai_available", lang, model=_md(ai_config.model)), icon=":material/rule:")

    raw = st.session_state.get(STATE)
    session = load_session(raw)
    if raw is not None and session is None:  # stale or broken state: start over, say so
        _on_new_session()
        _error("grill.ui.restore_failed")
    if error := st.session_state.pop(ERROR, None):
        key, params = error
        st.error(t(key, lang, **params), icon=":material/error:")
    if notice := st.session_state.pop(NOTICE, None):
        key, params = notice
        st.info(t(key, lang, **params), icon=":material/smart_toy:")

    if session is None:
        _start_screen(lang, workspace)
    else:
        _session_screen(lang, session, ai_config)


def _start_screen(lang: str, workspace: Workspace | None) -> None:
    context = list(workspace.requirements) if workspace else []
    with st.container(border=True, key="grill_panel"):
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

        st.button(
            t("grill.ui.start", lang), type="primary", icon=":material/play_arrow:", key="grill_start",
            on_click=_on_start, args=(kind.value, mode.value, artifact.value, use_analyzed, context),
        )


def _session_screen(lang: str, session: GrillSession, ai_config: AIConfig | None = None) -> None:
    title = t(f"grill.kind.{session.kind.value}", lang)
    if session.kind == GrillKind.REVIEW:
        title += f" · {t(f'grill.artifact.{session.artifact.value}', lang)}"
    st.markdown(f"#### {_md(title)} · {_md(t(f'grill.step.{session.step.value}', lang))}")

    done, total = session.progress
    if total:
        st.progress(done / total, text=t("grill.ui.progress", lang, done=done, total=total))
    if (unparsed := st.session_state.get(UNPARSED)) and not session.is_terminal:
        st.warning(t("grill.ui.unparsed", lang), icon=":material/help:")
        st.code("\n".join(unparsed), language=None)  # shown literally, never interpreted

    actions = allowed_actions(session)
    step = session.step
    if step == GrillStep.ASK_QUESTION:
        _question_panel(lang, session, actions)
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
    elif step == GrillStep.CANCELLED:
        st.info(t("grill.ui.cancelled", lang), icon=":material/cancel:")

    if session.is_terminal:
        st.button(t("grill.ui.new_session", lang), type="primary", key="grill_new", on_click=_on_new_session)
        return
    if ai_config is not None and Action.ADD_QUESTIONS in actions:
        _ai_panel(lang, session, ai_config)
    _answers_panel(lang, session, actions)
    _footer(lang, session, actions)


# --- Interview ----------------------------------------------------------------

def _question_panel(lang: str, session: GrillSession, actions: set[Action]) -> None:
    question = session.current_question
    assert question is not None  # guaranteed in ASK_QUESTION
    rev = session.revision
    prompt, reason = render_question(question, lang)
    with st.container(border=True, key="grill_question"):
        st.markdown(f"**{_md(prompt)}**")
        if reason:
            st.caption(_md(t("grill.ui.why", lang, reason=reason)))
        if question.origin == Source.AI:
            st.caption(t("grill.ui.ai_question", lang))
        _linked_requirements(lang, session, question)
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
                t("grill.ui.answer_label", lang), key=text_key, help=list_hint,
                value=previous_value if previous_value not in {c.value for c in question.choices} else "",
            )

        history = session.history
        position = history.index(question.id) if question.id in history else 0
        row1 = st.columns(3)
        row1[0].button(
            t("grill.ui.answer", lang), type="primary", key="grill_answer", width="stretch",
            on_click=_on_answer, args=(rev, AnswerStatus.ANSWERED.value, choice_key, text_key),
        )
        row1[1].button(
            t("grill.ui.assume", lang), key="grill_assume", width="stretch",
            on_click=_on_answer, args=(rev, AnswerStatus.ASSUMED.value, choice_key, text_key),
        )
        row1[2].button(
            t("grill.ui.unknown", lang), key="grill_unknown", width="stretch",
            on_click=_on_answer, args=(rev, AnswerStatus.UNKNOWN.value, choice_key, text_key),
        )
        row2 = st.columns(3)
        row2[0].button(
            t("grill.ui.skip", lang), key="grill_skip", width="stretch", disabled=question.essential,
            on_click=_run, args=(WF.skip, rev),
        )
        row2[1].button(
            t("grill.ui.back", lang), key="grill_back", icon=":material/arrow_back:", width="stretch",
            disabled=position == 0 or Action.BACK not in actions, on_click=_run, args=(WF.back, rev),
        )
        row2[2].button(
            t("grill.ui.to_draft", lang), key="grill_to_draft", width="stretch",
            on_click=_run, args=(WF.proceed_to_draft, rev),
        )


def _linked_requirements(lang: str, session: GrillSession, question: Question) -> None:
    texts = {r.id: r.text for r in session.context_requirements}
    if isinstance(session.draft, RequirementsDraft):
        texts |= {r.id: r.text for r in session.draft.requirements}
    for req_id in question.requirement_ids:
        if req_id in texts:
            st.caption(_md(t("grill.ui.linked", lang, id=req_id, text=texts[req_id])))


def _answers_panel(lang: str, session: GrillSession, actions: set[Action]) -> None:
    handled = [q for q in session.questions if q.id in session.answers]
    if not handled:
        return
    with st.expander(t("grill.ui.answers_heading", lang), icon=":material/history:"):
        rows = []
        for question in session.questions:
            answer = session.answers.get(question.id)
            rows.append({
                t("grill.ui.column_question", lang): render_question(question, lang)[0],
                t("grill.ui.column_answer", lang): answer.value if answer else "",
                t("grill.ui.column_status", lang): t(f"grill.answer_status.{answer.status.value}", lang)
                if answer else t("grill.ui.pending", lang),
            })
        _table(rows)
        if Action.EDIT_ANSWER in actions:
            select_key = _key(session, "edit", session.revision)
            prompts = {q.id: render_question(q, lang)[0] for q in handled}
            st.selectbox(t("grill.ui.column_question", lang), list(prompts), key=select_key, format_func=prompts.__getitem__)
            st.button(
                t("grill.ui.edit_answer", lang), key="grill_edit_answer", icon=":material/edit:",
                on_click=_on_edit_answer, args=(session.revision, select_key),
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
                raw[field] = st.text_area(label, value="\n".join(value), key=key, help=t("grill.ui.one_per_line", lang))
            elif field in SHORT_TEXT_FIELDS:
                raw[field] = st.text_input(label, value=value, key=key)
            else:
                raw[field] = st.text_area(label, value=value, key=key, height=100)
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


# --- Optional AI ------------------------------------------------------------------------

def _ai_panel(lang: str, session: GrillSession, config: AIConfig) -> None:
    """Ask the model for questions or a review; each request needs a fresh consent."""
    with st.expander(t("grill.ui.ai_heading", lang), icon=":material/smart_toy:"):
        st.caption(t("grill.ui.ai_explainer", lang))
        what = "requirements" if isinstance(session.draft, RequirementsDraft) else "draft"
        consent = st.checkbox(
            t(f"grill.ui.ai_consent_{what}", lang, provider=config.provider, model=_md(config.model)),
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


def _footer(lang: str, session: GrillSession, actions: set[Action]) -> None:
    cols = st.columns(2)
    if Action.REVIEW in actions:
        cols[0].button(
            t("grill.ui.review", lang), key="grill_review_button", icon=":material/fact_check:",
            width="stretch", on_click=_run, args=(WF.review, session.revision),
        )
    with cols[1].popover(t("grill.ui.cancel", lang), icon=":material/close:", width="stretch"):
        st.caption(t("grill.ui.cancel_confirm", lang))
        st.button(
            t("grill.ui.cancel_yes", lang), key="grill_cancel", on_click=_run, args=(WF.cancel, session.revision),
        )
