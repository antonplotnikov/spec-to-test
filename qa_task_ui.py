"""QA task mode of the QA Agent page: a task in plain words, one combined result.

The analysis is spec_to_test.qa_agent.tasks (which calls the existing tools);
this module only draws the form and the result. A proposed status change is
applied only from the Apply button, which stays disabled until the user ticks
the confirmation.

With AI configured (sidebar "AI settings"), the user may add the AI review
(spec_to_test.qa_agent.ai_review) to one run by ticking the consent box: the
document's requirements, test cases and changes are sent to that provider. The
box is off by default and is cleared after every run. The AI step only adds
findings to the result; it never proposes or applies a change.

Project memory (spec_to_test.qa_agent.memory) is shown beside a result when it
is relevant to it, and is managed in the "Project memory" panel: rules the
user confirmed and the user's ratings of results. Nothing is saved without an
explicit click.

A run is compared (tasks.compare_problems, as on_change does) with the previous
finished run of this browser session when both checked the same document (same
project and document title, the app's rule for a new version, or the same
content) with the same task. Only that one previous run is kept, in the session
state; nothing about it is saved.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import streamlit as st

from projects_ui import active_project_id
from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import t
from spec_to_test.llm.config import AIConfig
from spec_to_test.llm.providers import ConfiguredProvider
from spec_to_test.models import ChangeImpact, Workspace
from spec_to_test.qa_agent import memory, tasks
from spec_to_test.qa_agent.ai_review import add_ai_step, ai_review, failed_step
from spec_to_test.qa_agent.memory import MemoryEntry, MemoryEntryError, MemoryStore, Rating
from spec_to_test.qa_agent.tasks import AgentResult, Item, ProblemComparison, ProposedAction

TASK = "qa_task_text"
RESULT = "qa_task_result"
PREVIOUS = "qa_task_previous"  # PreviousCheck: the latest finished run, compared with the next one
RERUN = "qa_task_rerun"  # Rerun of the shown result
CONFIRM = "qa_task_confirm"
MESSAGE = "qa_task_message"
RATED = "qa_task_rated"
FEEDBACK_COMMENT = "qa_task_feedback_comment"
RULE_TEXT = "qa_memory_rule_text"
RULE_TOOLS = "qa_memory_rule_tools"
RULE_CONFIRM = "qa_memory_rule_confirm"
PICK = "qa_memory_pick"
AI_CONSENT = "qa_task_ai_consent"
AI_PENDING = "qa_task_ai_pending"
RATING_ICONS = {"useful": "👍", "not_useful": "👎"}


@dataclass(frozen=True)
class PreviousCheck:
    project_id: str
    title: str
    result: AgentResult
    at: str  # time of the run, shown in the comparison


@dataclass(frozen=True)
class Rerun:
    """How the shown result relates to the previous check: compared, or why not."""

    comparison: ProblemComparison | None = None
    at: str = ""
    not_compared: Literal["", "other_document", "other_task"] = ""


def _text(lang: str, item: Item) -> str:
    params: dict[str, Any] = dict(item.params)
    if "ids" in params:
        params["ids"] = tasks.shown_ids(lang, item, item.params["ids"])
    if item.terms:
        params["names"] = ", ".join(t(term, lang) for term in item.terms)
    try:
        return t(item.key, lang, **params)
    except (KeyError, IndexError, ValueError):
        return t(item.key, lang)


def _line(lang: str, item: Item) -> str:
    ids = tasks.shown_ids(lang, item, ", ".join(item.ids))
    head = " · ".join(part for part in (ids, t(item.topic, lang) if item.topic else "") if part)
    text = escape_markdown(_text(lang, item))
    return f"- **{escape_markdown(head)}**: {text}" if head else f"- {text}"


def _lines_with_references(lang: str, items: list[Item], workspace: Workspace) -> str:
    """Each line followed by the text of the requirements and test cases it names and, if known, the next step."""
    return "\n".join(line for item in items
                     for line in (_line(lang, item), *tasks.reference_lines(lang, item, workspace),
                                  *tasks.next_step_lines(lang, item)))


def _same_document(previous: PreviousCheck, project_id: str, workspace: Workspace) -> bool:
    """The same project and document title (change_impact's rule for a new version), or, untitled, the same content."""
    if previous.project_id != project_id:
        return False
    if previous.title or workspace.title:
        return previous.title == workspace.title
    return previous.result.document_hash == workspace.document_hash


def _same_task(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def _remember_check(result: AgentResult, workspace: Workspace) -> None:
    """Compare a finished run with the previous one, then keep it for the next run."""
    state = st.session_state
    state.pop(RERUN, None)
    if result.status not in ("done", "partial"):
        return  # nothing checked: the previous check stays the one to compare with
    project_id = active_project_id()
    previous: PreviousCheck | None = state.get(PREVIOUS)
    if previous is not None:
        if not _same_document(previous, project_id, workspace):
            state[RERUN] = Rerun(not_compared="other_document")
        elif not _same_task(previous.result.task, result.task):
            state[RERUN] = Rerun(not_compared="other_task")
        else:
            state[RERUN] = Rerun(tasks.compare_problems(previous.result, result), previous.at)
    state[PREVIOUS] = PreviousCheck(project_id, workspace.title, result, time.strftime("%H:%M:%S"))


def _on_run(workspace: Workspace, previous_impact: Callable[[Workspace], ChangeImpact | None] | None) -> None:
    result = tasks.run_task(st.session_state.get(TASK, ""), workspace, previous_impact)
    st.session_state[RESULT] = result
    _remember_check(result, workspace)
    # The AI review runs below the form (with a spinner) and only with this run's consent.
    st.session_state[AI_PENDING] = bool(st.session_state.get(AI_CONSENT)) and result.status in ("done", "partial")
    st.session_state[AI_CONSENT] = False  # asked again before the next run
    st.session_state.pop(CONFIRM, None)
    st.session_state.pop(RATED, None)


def _run_ai(lang: str, result: AgentResult, workspace: Workspace, ai_config: AIConfig | None,
            previous_impact: Callable[[Workspace], ChangeImpact | None] | None) -> None:
    """Add the AI step to the stored result; a failure becomes a failed step with its reason."""
    if ai_config is None:  # turned off in the sidebar since the click
        add_ai_step(result, failed_step("not_configured"))
        return
    impact = workspace.change_impact
    if impact is None and previous_impact is not None:
        try:
            impact = previous_impact(workspace)
        except Exception:  # noqa: BLE001 - the review goes ahead without the changes
            impact = None
    with st.spinner(t("qatask.ai.running", lang, model=escape_markdown(ai_config.model))):
        add_ai_step(result, ai_review(workspace, ConfiguredProvider(ai_config), lang, impact))


def _on_apply(workspace: Workspace, persist: Callable[[Workspace], None], action: ProposedAction) -> None:
    result: AgentResult | None = st.session_state.get(RESULT)
    if result is not None:
        result.action = None  # one confirmation applies the change once
    st.session_state.pop(CONFIRM, None)
    try:
        changed = tasks.apply_action(workspace, action)
    except ValueError as error:
        st.session_state[MESSAGE] = ("error", "qatask.action.missing", {"ids": str(error)})
        return
    if not changed:
        st.session_state[MESSAGE] = ("info", "qatask.action.unchanged", {})
        return
    persist(workspace)
    st.session_state[MESSAGE] = ("success", "qatask.action.applied",
                                 {"ids": ", ".join(changed), "status": f"review.{action.status.value}"})


def render_task(
    lang: str,
    workspace: Workspace,
    persist: Callable[[Workspace], None] | None,
    previous_impact: Callable[[Workspace], ChangeImpact | None] | None = None,
    ai_config: AIConfig | None = None,
) -> None:
    st.caption(t("qatask.explainer", lang))
    st.text_area(t("qatask.input", lang), key=TASK, placeholder=t("qatask.placeholder", lang),
                 max_chars=tasks.MAX_TASK_LENGTH, height=90)
    if ai_config is not None:
        st.checkbox(t("qatask.ai.consent", lang, provider=ai_config.provider_name,
                      model=escape_markdown(ai_config.model)), key=AI_CONSENT)
    else:
        st.session_state.pop(AI_CONSENT, None)
        st.caption(t("qatask.ai.off", lang))
    st.button(t("qatask.run", lang), key="qa_task_run", type="primary", icon=":material/play_arrow:",
              on_click=_on_run, args=(workspace, previous_impact))
    st.caption(t("qatask.limits", lang, steps=tasks.MAX_STEPS))

    if message := st.session_state.pop(MESSAGE, None):
        level, key, params = message
        if "status" in params:
            params = {**params, "status": t(params["status"], lang)}
        getattr(st, level)(escape_markdown(t(key, lang, **params)))

    store = memory.open_memory_store(st.session_state)
    project_id = active_project_id()
    result: AgentResult | None = st.session_state.get(RESULT)
    if result is not None and result.document_hash != workspace.document_hash:
        st.session_state.pop(RESULT, None)  # a result for another document (kept as PREVIOUS for the next run)
        st.session_state.pop(RERUN, None)
        result = None
    if result is not None and st.session_state.pop(AI_PENDING, False):
        _run_ai(lang, result, workspace, ai_config, previous_impact)
    if result is not None:
        _result(lang, result, workspace, persist, st.session_state.get(RERUN))
        _related_memory(lang, result, store, project_id)
    _memory_panel(lang, store, project_id)


def _previous_lines(lang: str, comparison: ProblemComparison, items: list[Item]) -> list[str]:
    """Lines of the previous check, each with the title its test cases had then (the ID may now be another one)."""
    lines = []
    for item in items:
        lines.append(_line(lang, item))
        lines += [f"  - {escape_markdown(t('qatask.rerun.previous_test_case', lang, id=i, text=title))}"
                  for i in item.ids if (title := comparison.previous_titles.get(i)) is not None]
    return lines


def _comparison(lang: str, rerun: Rerun) -> None:
    if rerun.comparison is None:
        st.caption(t(f"qatask.rerun.{rerun.not_compared}", lang))
        return
    c = rerun.comparison
    st.subheader(t("qatask.compare.heading", lang), anchor=False)
    summary = t("qatask.rerun.summary", lang, at=rerun.at, resolved=c.resolved_count, open=c.still_open,
                new=c.new_count, before=c.unmatched_before_count, now=c.unmatched_now_count)
    if c.new_count:
        st.warning(summary, icon=":material/compare_arrows:")
    elif c.resolved_count:
        st.success(summary, icon=":material/compare_arrows:")
    else:
        st.info(summary, icon=":material/compare_arrows:")
    lines: list[str] = []
    if c.resolved:
        lines += [f"**{t('qatask.compare.resolved', lang, count=c.resolved_count)}**", "",
                  *_previous_lines(lang, c, c.resolved), ""]
    if c.new:
        lines += [f"**{t('qatask.compare.new', lang, count=c.new_count)}**", "", *(_line(lang, i) for i in c.new)]
    if lines:
        st.markdown("\n".join(lines))
    if c.unmatched_before or c.unmatched_now:
        heading = t("qatask.rerun.unmatched", lang, before=c.unmatched_before_count, now=c.unmatched_now_count)
        with st.expander(heading, icon=":material/help:"):
            st.caption(t("qatask.compare.unmatched_why", lang))
            unmatched = _previous_lines(lang, c, c.unmatched_before)
            for item in c.unmatched_now:
                unmatched.append(_line(lang, item))
                unmatched += [f"  - {escape_markdown(t('qatask.compare.current_test_case', lang, id=i, text=title))}"
                              for i in item.ids if (title := c.current_titles.get(i)) is not None]
            st.markdown("\n".join(unmatched))
    if c.not_compared:
        st.caption(t("qatask.compare.not_compared", lang,
                     names=", ".join(t(f"qatask.tool.{tool}", lang) for tool in c.not_compared)))


def _result(lang: str, result: AgentResult, workspace: Workspace, persist: Callable[[Workspace], None] | None,
            rerun: Rerun | None = None) -> None:
    plan = result.plan
    if result.status == "error" and not result.steps:
        ids = ", ".join(plan.unknown_ids) if plan else ""
        st.error(escape_markdown(t(result.error, lang, max=tasks.MAX_TASK_LENGTH, ids=ids)))
        return
    assert plan is not None
    if plan.unknown_ids:
        st.warning(escape_markdown(t("qatask.unknown_ids", lang, ids=", ".join(plan.unknown_ids))))
    if plan.action_needs_ids:
        st.warning(t("qatask.action_needs_ids", lang))
    if plan.action_too_large:
        st.warning(t("qatask.action_too_large", lang, max=tasks.MAX_ACTION_TEST_CASES))
    if plan.action_conflicts:
        st.warning(escape_markdown(t("qatask.action_conflicts", lang, ids=", ".join(plan.action_conflicts))))
    if plan.unsupported_terms:
        st.info(escape_markdown(t("qatask.unsupported_terms", lang, terms=", ".join(plan.unsupported_terms))))
    if result.status == "unsupported":
        st.warning(t("qatask.unsupported", lang))
        return

    tool_names = [t(f"qatask.tool.{step.tool}", lang) for step in result.steps]
    st.caption(t("qatask.plan", lang, tools=", ".join(tool_names)))
    scope = plan.test_case_ids + plan.requirement_ids
    st.caption(escape_markdown(t("qatask.scope", lang, ids=", ".join(scope))) if scope else t("qatask.scope_all", lang))
    if plan.skipped_tools:
        st.warning(t("qatask.skipped_tools", lang, max=tasks.MAX_STEPS,
                     tools=", ".join(t(f"qatask.tool.{tool}", lang) for tool in plan.skipped_tools)))
    if result.status == "error":
        st.error(t(result.error, lang))
    elif result.status == "partial":
        st.warning(t("qatask.status.partial", lang))

    st.subheader(t("qatask.heading.conclusions", lang), anchor=False)
    conclusions = []
    for step, name in zip(result.steps, tool_names, strict=True):
        if step.status == "error" and step.summary is not None:  # the AI step says why it failed
            conclusions.append(f"- **{name}**: {escape_markdown(_text(lang, step.summary))}")
        elif step.status == "error":
            conclusions.append(f"- {t('qatask.step_failed', lang, tool=name, error=step.error)}")
        elif step.summary is not None:
            conclusions.append(f"- **{name}**: {escape_markdown(_text(lang, step.summary))}")
    st.markdown("\n".join(conclusions))
    if any(step.tool == "ai" and step.status == "ok" for step in result.steps):
        st.info(t("qatask.ai.disclaimer", lang), icon=":material/smart_toy:")
    if rerun is not None:
        _comparison(lang, rerun)

    problems, unknowns = result.problems, result.unknowns
    st.subheader(t("qatask.heading.problems", lang, count=len(problems)), anchor=False)
    if problems:
        st.markdown(_lines_with_references(lang, problems, workspace))
    else:
        st.success(t("qatask.no_problems", lang))
    if unknowns:
        with st.expander(t("qatask.heading.unknowns", lang, count=len(unknowns)), icon=":material/help:"):
            st.markdown(_lines_with_references(lang, unknowns, workspace))

    if result.approval is not None:
        st.subheader(t("qatask.heading.approval", lang), anchor=False)
        st.info(escape_markdown(_text(lang, result.approval)), icon=":material/rule:")

    st.subheader(t("qatask.heading.recommendations", lang), anchor=False)
    recommendations = result.recommendations
    st.markdown("\n".join(_line(lang, item) for item in recommendations) if recommendations
                else t("qatask.no_recommendations", lang))

    if result.action is not None and persist is not None:
        _action(lang, result, workspace, persist)


def _action(lang: str, result: AgentResult, workspace: Workspace, persist: Callable[[Workspace], None]) -> None:
    action = result.action
    assert action is not None
    with st.container(border=True, key="qa_task_action"):
        st.markdown(f"**{t('qatask.heading.action', lang)}**")
        st.markdown(t("qatask.action.describe", lang, ids=escape_markdown(", ".join(action.test_case_ids)),
                      status=t(f"review.{action.status.value}", lang)))
        critic = next((s for s in result.steps if s.tool == "critic"), None)
        if critic is not None and any(item.mentions & set(action.test_case_ids) for item in critic.problems):
            st.warning(t("qatask.action.critic_warning", lang))
        confirmed = st.checkbox(t("qatask.action.confirm", lang), key=CONFIRM)
        st.button(t("qatask.action.apply", lang), key="qa_task_apply", icon=":material/check:",
                  disabled=not confirmed, on_click=_on_apply, args=(workspace, persist, action))


# --- Project memory -------------------------------------------------------------------

def _tools_text(lang: str, tools: list[str]) -> str:
    return ", ".join(t(f"qatask.tool.{tool}", lang) for tool in tools)


def _entry_text(lang: str, entry: MemoryEntry) -> str:
    tools = _tools_text(lang, list(entry.tools))
    if entry.kind == "rule":
        return f"📌 {escape_markdown(entry.text)} _({tools})_"
    comment = f" — {escape_markdown(entry.text)}" if entry.text else ""
    return f"{RATING_ICONS[entry.rating or 'useful']} «{escape_markdown(entry.task)}»{comment} _({tools})_"


def _memory_message(level: str, key: str, **params: str) -> None:
    st.session_state[MESSAGE] = (level, key, params)


def _on_feedback(store: MemoryStore, project_id: str, rating: Rating) -> None:
    result: AgentResult | None = st.session_state.get(RESULT)
    if result is None:
        return
    try:
        store.add(project_id, memory.new_feedback(result, rating, st.session_state.get(FEEDBACK_COMMENT, "")))
    except MemoryEntryError as error:
        _memory_message("error", f"qamemory.error.{error.code}")
        return
    except (OSError, ValueError):
        _memory_message("error", "qamemory.error.save_failed")
        return
    st.session_state[RATED] = True
    st.session_state.pop(FEEDBACK_COMMENT, None)
    _memory_message("success", "qamemory.feedback_saved")


def _related_memory(lang: str, result: AgentResult, store: MemoryStore, project_id: str) -> None:
    """Entries relevant to this result, and the buttons to rate it."""
    if related := memory.relevant(store.entries(project_id), result.plan):
        lines = [f"**{t('qamemory.relevant_heading', lang)}**", ""]
        lines += [f"- {_entry_text(lang, entry)}" for entry in related]
        lines += ["", f"_{t('qamemory.relevant_note', lang)}_"]
        st.info("\n".join(lines), icon=":material/psychology:")
    if st.session_state.get(RATED) or not any(step.status == "ok" for step in result.steps):
        return
    with st.container(border=True, key="qa_task_feedback"):
        st.markdown(f"**{t('qamemory.feedback_heading', lang)}**")
        st.text_input(t("qamemory.feedback_comment", lang), key=FEEDBACK_COMMENT,
                      max_chars=memory.MAX_TEXT_LENGTH)
        c1, c2 = st.columns(2)
        c1.button(t("qamemory.rating.useful", lang), key="qa_feedback_useful", icon=":material/thumb_up:",
                  on_click=_on_feedback, args=(store, project_id, "useful"), width="stretch")
        c2.button(t("qamemory.rating.not_useful", lang), key="qa_feedback_not_useful",
                  icon=":material/thumb_down:", on_click=_on_feedback, args=(store, project_id, "not_useful"),
                  width="stretch")


def _on_add_rule(store: MemoryStore, project_id: str) -> None:
    state = st.session_state
    try:
        entry = memory.new_rule(state.get(RULE_TEXT, ""), list(state.get(RULE_TOOLS) or []),
                                bool(state.get(RULE_CONFIRM)))
        store.add(project_id, entry)
    except MemoryEntryError as error:
        _memory_message("error", f"qamemory.error.{error.code}")
        return
    except (OSError, ValueError):
        _memory_message("error", "qamemory.error.save_failed")
        return
    for key in (RULE_TEXT, RULE_TOOLS, RULE_CONFIRM):
        state.pop(key, None)
    _memory_message("success", "qamemory.rule_saved")


def _on_save_entry(store: MemoryStore, project_id: str, entry: MemoryEntry) -> None:
    state = st.session_state
    try:
        store.update(project_id, memory.edited(
            entry, state.get(f"qa_memory_text_{entry.id}", ""), list(state.get(f"qa_memory_tools_{entry.id}") or []),
            state.get(f"qa_memory_rating_{entry.id}"),
        ))
    except MemoryEntryError as error:
        _memory_message("error", f"qamemory.error.{error.code}")
        return
    except (OSError, ValueError):
        _memory_message("error", "qamemory.error.save_failed")
        return
    _memory_message("success", "qamemory.entry_saved")


def _on_delete_entry(store: MemoryStore, project_id: str, entry_id: str) -> None:
    try:
        store.delete(project_id, entry_id)
    except (OSError, ValueError):
        _memory_message("error", "qamemory.error.save_failed")
        return
    st.session_state.pop(PICK, None)
    st.session_state.pop(f"qa_memory_delete_confirm_{entry_id}", None)
    _memory_message("success", "qamemory.entry_deleted")


def _memory_panel(lang: str, store: MemoryStore, project_id: str) -> None:
    """View, add, correct and delete the project's memory."""
    entries = store.entries(project_id)
    with st.expander(t("qamemory.heading", lang, count=len(entries)), icon=":material/psychology:"):
        st.caption(t("qamemory.explainer", lang))
        if entries:
            st.markdown("\n".join(f"- {_entry_text(lang, entry)}" for entry in entries))
            by_id = {entry.id: entry for entry in entries}
            picked = st.selectbox(t("qamemory.pick", lang), list(by_id), key=PICK, index=None,
                                  format_func=lambda i: f"{by_id[i].text or by_id[i].task}"[:80])
            if picked in by_id:
                _entry_editor(lang, store, project_id, by_id[picked])
        else:
            st.info(t("qamemory.empty", lang))
        st.markdown(f"**{t('qamemory.add_rule', lang)}**")
        st.text_area(t("qamemory.rule_text", lang), key=RULE_TEXT, max_chars=memory.MAX_TEXT_LENGTH, height=70)
        st.multiselect(t("qamemory.tools", lang), list(tasks.TOOLS), key=RULE_TOOLS,
                       format_func=lambda tool: t(f"qatask.tool.{tool}", lang))
        confirmed = st.checkbox(t("qamemory.rule_confirm", lang), key=RULE_CONFIRM)
        st.button(t("qamemory.save_rule", lang), key="qa_memory_add", icon=":material/add:", disabled=not confirmed,
                  on_click=_on_add_rule, args=(store, project_id))


def _entry_editor(lang: str, store: MemoryStore, project_id: str, entry: MemoryEntry) -> None:
    with st.container(border=True, key=f"qa_memory_editor_{entry.id}"):
        if entry.kind == "feedback":
            st.caption(t("qamemory.feedback_for", lang, task=escape_markdown(entry.task)))
            ratings: list[Rating] = ["useful", "not_useful"]
            st.radio(t("qamemory.rating", lang), ratings, index=ratings.index(entry.rating or "useful"),
                     key=f"qa_memory_rating_{entry.id}", horizontal=True,
                     format_func=lambda r: t(f"qamemory.rating.{r}", lang))
        label = "qamemory.rule_text" if entry.kind == "rule" else "qamemory.feedback_comment"
        st.text_area(t(label, lang), value=entry.text, key=f"qa_memory_text_{entry.id}",
                     max_chars=memory.MAX_TEXT_LENGTH, height=70)
        st.multiselect(t("qamemory.tools", lang), list(tasks.TOOLS), default=list(entry.tools),
                       key=f"qa_memory_tools_{entry.id}", format_func=lambda tool: t(f"qatask.tool.{tool}", lang))
        c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="center")
        c1.button(t("qamemory.save", lang), key=f"qa_memory_save_{entry.id}", icon=":material/save:",
                  on_click=_on_save_entry, args=(store, project_id, entry))
        confirm = c3.checkbox(t("qamemory.delete_confirm", lang), key=f"qa_memory_delete_confirm_{entry.id}")
        c2.button(t("qamemory.delete", lang), key=f"qa_memory_delete_{entry.id}", icon=":material/delete:",
                  disabled=not confirm, on_click=_on_delete_entry, args=(store, project_id, entry.id))
