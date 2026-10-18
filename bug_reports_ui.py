"""Bug Reports page: a product bug described in free text becomes a structured report.

The report is built by spec_to_test.bug_generator (rule-based, local; nothing is
sent to an AI provider). "Generate" opens a draft in the editor without saving
it; "Save" writes it to the project's bug reports (this browser session, or the
local data folder in "local" storage mode, like projects). Saved reports can be
opened again, edited, deleted after a confirmation, and downloaded as Markdown
one by one or all together.

When SPEC_TO_TEST_CLAUDE_CODE=1 is set, the page also offers "Generate with Claude
Code": after an explicit consent, the description goes to Claude through the local
Claude Code CLI and the user's own Claude login (spec_to_test.llm.claude_code);
fields the description does not support are removed (spec_to_test.bug_generator.ai).

Empty fields show "Needs clarification" and are saved empty: a marker typed into
a field is never saved as a fact. Missing Information is recomputed from the
fields every time, so it follows the edits.
"""

from typing import Any

import streamlit as st

import claude_usage_ui
import theme_ui
from spec_to_test.bug_generator.ai import checked_description, generate_with_claude
from spec_to_test.bug_generator.extract import BugInputError, generate_bug_report
from spec_to_test.bug_generator.markdown import (
    bug_report_markdown,
    bug_reports_markdown,
    by_generator,
    priority_note,
    severity_note,
)
from spec_to_test.bug_generator.models import (
    LIST_FIELDS,
    MAX_DESCRIPTION_CHARS,
    ProductBugReport,
    edited_report,
    missing_information,
    next_report_id,
)
from spec_to_test.bug_generator.store import BugReportStore, BugStoreError
from spec_to_test.formatting import escape_markdown
from spec_to_test.grill.models import Priority
from spec_to_test.i18n import t
from spec_to_test.llm import claude_code
from spec_to_test.llm.providers import AIError
from spec_to_test.models import Severity, Source
from spec_to_test.projects import now

INPUT = "bug_report_text"
# {"project": id, "report": ProductBugReport, "removed": [field, ...]}: generated, not saved yet.
# "removed": fields whose Claude value the description did not support.
DRAFT = "bug_report_draft"
OPEN = "bug_report_open"  # {"project": id, "id": report id}: the saved report shown in the editor
NONCE = "bug_report_nonce"  # part of the editor's widget keys: a new value loads the report's values again
PICK = "bug_report_pick"
# Claude Code model aliases, cheapest first (they always point to the current model of each family).
MODEL_CHOICES = ("", "haiku", "sonnet", "opus")
PLAN = "bug_cc_plan"  # the plan's limits from the last "Check plan limits" click
SEVERITY_TONES = {"high": "danger", "medium": "warning", "low": "neutral"}


def _reload_editor() -> None:
    st.session_state[NONCE] = st.session_state.get(NONCE, 0) + 1


def _flash(message: str, icon: str = "✅") -> None:
    import pages_ui  # pages_ui imports this module

    pages_ui.flash(message, icon)


def _draft(project_id: str) -> ProductBugReport | None:
    draft = st.session_state.get(DRAFT)
    if isinstance(draft, dict) and draft.get("project") == project_id:
        report = draft.get("report")
        return report if isinstance(report, ProductBugReport) else None
    return None


def _removed(project_id: str, report: ProductBugReport) -> list[str]:
    draft = st.session_state.get(DRAFT)
    if isinstance(draft, dict) and draft.get("project") == project_id and draft.get("report") is report:
        return [str(name) for name in draft.get("removed") or []]
    return []


def _opened(project_id: str, saved: list[ProductBugReport]) -> ProductBugReport | None:
    opened = st.session_state.get(OPEN)
    if isinstance(opened, dict) and opened.get("project") == project_id:
        return next((r for r in saved if r.id == opened.get("id")), None)
    return None


def _open(project_id: str, report_id: str) -> None:
    st.session_state.pop(DRAFT, None)
    st.session_state[OPEN] = {"project": project_id, "id": report_id}
    _reload_editor()


def render_bug_reports(lang: str, project_id: str, project_label: str, store: BugReportStore) -> None:
    saved = store.reports(project_id)
    _describe(lang, project_id, saved)
    report = _draft(project_id) or _opened(project_id, saved)
    if report is not None:
        _editor(lang, project_id, report, store, is_saved=any(r.id == report.id for r in saved))
    _saved_list(lang, project_id, project_label, saved)


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def _describe(lang: str, project_id: str, saved: list[ProductBugReport]) -> None:
    with theme_ui.card("bug_report_input"):
        theme_ui.section(t("bugreport.describe", lang), ":material/edit_note:", t("bugreport.explainer", lang))
        text = st.text_area(
            t("bugreport.input", lang), placeholder=t("bugreport.placeholder", lang), height=180, key=INPUT,
            max_chars=MAX_DESCRIPTION_CHARS,
        )
        if st.button(t("bugreport.generate", lang), type="primary", icon=":material/bug_report:", key="bug_generate"):
            try:
                report = generate_bug_report(text, next_report_id(saved), now())
            except BugInputError as error:
                st.error(t(f"bugreport.error.{error.code}", lang, max_chars=MAX_DESCRIPTION_CHARS))
                return
            st.session_state[DRAFT] = {"project": project_id, "report": report}
            st.session_state.pop(OPEN, None)
            _reload_editor()
            _flash(t("bugreport.generated", lang, id=report.id))
            st.rerun()
        _claude_code(lang, project_id, saved, text)


def _claude_code(lang: str, project_id: str, saved: list[ProductBugReport], text: str) -> None:
    """The opt-in Claude Code generator (shown only when SPEC_TO_TEST_CLAUDE_CODE=1)."""
    settings = claude_code.load_claude_code_settings()
    if not settings.enabled:
        return
    st.divider()
    st.markdown(f"**{t('bugreport.cc.heading', lang)}**")
    st.caption(t("bugreport.cc.explainer", lang))
    if not settings.binary:
        st.warning(t("bugreport.cc.missing_cli", lang), icon="⚠️")
        return
    # Model per browser session: "" = the plan's default (or SPEC_TO_TEST_CLAUDE_CODE_MODEL).
    models = list(dict.fromkeys([settings.model, *MODEL_CHOICES]))
    model = st.selectbox(
        t("bugreport.cc.model", lang), models, key="bug_cc_model", help=t("bugreport.cc.model_help", lang),
        format_func=lambda m: t(f"bugreport.cc.model.{m or 'default'}", lang) if m in ("", *MODEL_CHOICES) else m,
    )
    provider = claude_code.ClaudeCodeProvider(settings.model_copy(update={"model": model or ""}))
    consent = st.checkbox(t("bugreport.cc.consent", lang), key="bug_cc_consent")
    g1, g2 = st.columns([1, 1], vertical_alignment="center")
    generate = g1.button(t("bugreport.cc.generate", lang), icon=":material/auto_awesome:", disabled=not consent,
                         key="bug_cc_generate")
    if g2.button(t("claude_code.usage.check", lang), icon=":material/data_usage:", key="bug_cc_limits",
                 help=t("claude_code.usage.check_help", lang)):
        st.session_state[PLAN] = provider.plan_usage(now())
    if PLAN in st.session_state:
        claude_usage_ui.render_plan_usage(st.session_state[PLAN], lang)
    if not generate:
        return
    try:
        checked_description(text)  # nothing runs for an empty or too long description
    except BugInputError as error:
        st.error(t(f"bugreport.error.{error.code}", lang, max_chars=MAX_DESCRIPTION_CHARS))
        return
    with st.spinner(t("bugreport.cc.running", lang)):
        before = provider.plan_usage(now())
        try:
            result = generate_with_claude(text, next_report_id(saved), provider, now())
        except AIError as error:
            st.error(t(f"claude_code.error.{error.code}", lang), icon="⚠️")
            if provider.last_usage is not None and provider.last_usage.total_tokens:
                st.caption(t("claude_code.usage.failed_tokens", lang,
                             total=claude_usage_ui.number(provider.last_usage.total_tokens, lang)))
            st.caption(t("bugreport.cc.fallback", lang))
            return
        after = provider.plan_usage(now())
    usage = claude_code.GenerationUsage(tokens=provider.last_usage, before=before, after=after)
    report = result.report.model_copy(update={"generation_usage": usage})
    st.session_state[PLAN] = after
    st.session_state[DRAFT] = {"project": project_id, "report": report, "removed": result.removed}
    st.session_state.pop(OPEN, None)
    _reload_editor()
    _flash(t("bugreport.generated", lang, id=report.id))
    st.rerun()


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------

def _missing(lang: str, report: ProductBugReport) -> None:
    codes = missing_information(report)
    theme_ui.section(t("bugreport.field.missing", lang), ":material/help:")
    if not codes:
        st.success(t("bugreport.missing_none", lang), icon="✅")
        return
    st.warning("\n".join(f"- {escape_markdown(t(f'bugreport.missing.{code}', lang))}" for code in codes), icon="❓")


def _level_select(lang: str, kind: str, current: Any, key: str) -> Any:
    options: list[Any] = [None, *(list(Severity) if kind == "severity" else list(Priority))]
    order = {None: 0, "low": 1, "medium": 2, "high": 3}
    options.sort(key=lambda v: order[v.value if v is not None else None])

    def label(value: Any) -> str:
        if value is None:
            return t("bugreport.needs_clarification", lang)
        return t(f"severity.{value.value}" if kind == "severity" else f"grill.priority.{value.value}", lang)

    return st.selectbox(t(f"bugreport.field.{kind}", lang), options, index=options.index(current),
                        format_func=label, key=key)


def _editor(lang: str, project_id: str, report: ProductBugReport, store: BugReportStore, is_saved: bool) -> None:
    nonce = st.session_state.get(NONCE, 0)

    def key(name: str) -> str:
        return f"br_{name}_{report.id}_{nonce}"

    marker = t("bugreport.needs_clarification", lang)
    with theme_ui.card("bug_report_editor"):
        theme_ui.section(t("bugreport.editor", lang, id=report.id), ":material/assignment:")
        note = by_generator("bugreport.edited_note" if report.source == Source.USER else "bugreport.generated_note",
                            report)
        if not is_saved:
            st.info(t("bugreport.unsaved", lang), icon="📝")
            if report.generated_by != "rules":
                st.caption(t(note, lang))
        else:
            st.caption(t(note, lang))
        if report.generation_usage is not None:
            claude_usage_ui.render_generation_usage(report.generation_usage, lang)
        if removed := _removed(project_id, report):
            fields = ", ".join(t(f"bugreport.field.{name}", lang) for name in removed)
            st.warning(t("bugreport.cc.removed", lang, fields=escape_markdown(fields)), icon="✂️")
        _missing(lang, report)
        values: dict[str, str] = {}
        with st.form(key=f"br_form_{report.id}_{nonce}", border=False):
            values["title"] = st.text_input(t("bugreport.field.title", lang), report.title, placeholder=marker,
                                            key=key("title"))
            c1, c2, c3 = st.columns(3)
            for column, name in zip((c1, c2, c3), ("what", "where", "when"), strict=True):
                values[name] = column.text_area(
                    t(f"bugreport.field.{name}", lang), getattr(report, name), placeholder=marker, height=100,
                    help=t(f"bugreport.help.{name}", lang), key=key(name),
                )
            for name in ("preconditions", "steps"):
                values[name] = st.text_area(
                    t(f"bugreport.field.{name}", lang), "\n".join(getattr(report, name)), placeholder=marker,
                    help=t("bugreport.help.list", lang), key=key(name),
                )
            a1, a2 = st.columns(2)
            values["actual_result"] = a1.text_area(t("bugreport.field.actual_result", lang), report.actual_result,
                                                   placeholder=marker, key=key("actual_result"))
            values["expected_result"] = a2.text_area(t("bugreport.field.expected_result", lang),
                                                     report.expected_result, placeholder=marker,
                                                     key=key("expected_result"))
            values["environment"] = st.text_area(
                t("bugreport.field.environment", lang), "\n".join(report.environment), placeholder=marker,
                help=t("bugreport.help.list", lang), key=key("environment"),
            )
            s1, s2 = st.columns(2)
            with s1:
                severity = _level_select(lang, "severity", report.severity, key("severity"))
                if note := severity_note(report, lang):
                    st.caption(escape_markdown(note))
            with s2:
                priority = _level_select(lang, "priority", report.priority, key("priority"))
                if note := priority_note(report, lang):
                    st.caption(escape_markdown(note))
            st.caption(t("bugreport.preliminary", lang))
            if report.unassigned:
                values["unassigned"] = st.text_area(
                    t("bugreport.field.unassigned", lang), "\n".join(report.unassigned),
                    help=t("bugreport.help.unassigned", lang), key=key("unassigned"),
                )
            submitted = st.form_submit_button(t("bugreport.save", lang), type="primary", icon=":material/save:",
                                              key="bug_report_save")
        if report.description:
            with st.expander(t("bugreport.field.description", lang)):
                st.text(report.description)
        if submitted:
            _save(lang, project_id, report, store, values, severity, priority)
        _report_actions(lang, project_id, report, store, is_saved)


def _save(
    lang: str, project_id: str, report: ProductBugReport, store: BugReportStore, values: dict[str, str],
    severity: Severity | None, priority: Priority | None,
) -> None:
    for name in LIST_FIELDS:
        values.setdefault(name, "")
    updated = edited_report(report, values, severity, priority, now())
    try:
        store.save(project_id, updated)
    except BugStoreError as error:
        st.error(t(f"bugreport.error.{error.code}", lang))
        return
    except (OSError, ValueError):
        st.error(t("storage.save_failed", lang))
        return
    _open(project_id, updated.id)
    _flash(t("bugreport.saved", lang, id=updated.id))
    st.rerun()


def _report_actions(lang: str, project_id: str, report: ProductBugReport, store: BugReportStore,
                    is_saved: bool) -> None:
    if not is_saved:
        if st.button(t("bugreport.discard", lang), icon=":material/close:", key="bug_report_discard"):
            st.session_state.pop(DRAFT, None)
            st.rerun()
        st.caption(t("bugreport.download_unsaved", lang))
        return
    d1, d2, d3 = st.columns([2, 1, 2], vertical_alignment="center")
    d1.download_button(
        t("bugreport.download", lang, id=report.id), bug_report_markdown(report, lang).encode("utf-8"),
        file_name=f"{report.id}.md", mime="text/markdown", icon=":material/download:", key="bug_report_download",
    )
    confirmed = d3.checkbox(t("action.confirm_delete", lang, id=report.id), key=f"bug_report_confirm_{report.id}")
    if d2.button(t("action.delete", lang), icon=":material/delete:", disabled=not confirmed,
                 key=f"bug_report_delete_{report.id}"):
        try:
            store.delete(project_id, report.id)
        except (OSError, ValueError):
            st.error(t("storage.save_failed", lang))
            return
        st.session_state.pop(OPEN, None)
        _flash(t("action.deleted", lang, id=report.id), icon="🗑️")
        st.rerun()


# ---------------------------------------------------------------------------
# Saved reports
# ---------------------------------------------------------------------------

def _level_cell(lang: str, report: ProductBugReport, kind: str) -> str:
    value = getattr(report, kind)
    if value is None:
        return t("bugreport.needs_clarification", lang)
    return t(f"severity.{value.value}" if kind == "severity" else f"grill.priority.{value.value}", lang)


def _saved_list(lang: str, project_id: str, project_label: str, saved: list[ProductBugReport]) -> None:
    import pages_ui  # pages_ui imports this module

    with theme_ui.card("bug_report_saved"):
        theme_ui.section(t("bugreport.saved_heading", lang), ":material/folder_open:",
                         t("bugreport.project", lang, name=escape_markdown(project_label)) if project_label else "")
        if not saved:
            st.info(t("bugreport.none_saved", lang), icon="💡")
            return
        pages_ui.show_table([
            {
                t("column.id", lang): r.id,
                t("bugreport.column.title", lang): r.title or t("bugreport.needs_clarification", lang),
                t("bugreport.column.severity", lang): _level_cell(lang, r, "severity"),
                t("bugreport.column.priority", lang): _level_cell(lang, r, "priority"),
                t("bugreport.column.missing", lang): len(missing_information(r)),
                t("bugreport.column.tokens", lang): (
                    claude_usage_ui.number(r.generation_usage.tokens.total_tokens, lang)
                    if r.generation_usage is not None and r.generation_usage.tokens is not None else "—"
                ),
                t("bugreport.column.updated", lang): (r.updated_at or r.created_at)[:16].replace("T", " "),
            }
            for r in saved
        ])
        titles = {r.id: r.title for r in saved}
        o1, o2, o3 = st.columns([3, 1, 2], vertical_alignment="bottom")
        chosen = o1.selectbox(t("bugreport.open", lang), list(titles), key=PICK,
                              format_func=lambda i: f"{i} — {titles[i]}" if titles[i] else i)
        if o2.button(t("bugreport.open", lang), icon=":material/open_in_new:", key="bug_report_open_button"):
            _open(project_id, str(chosen))
            st.rerun()
        o3.download_button(
            t("bugreport.download_all", lang), bug_reports_markdown(saved, lang).encode("utf-8"),
            file_name="bug_reports.md", mime="text/markdown", icon=":material/download:",
            key="bug_report_download_all",
        )
