"""How much a Claude Code generation used: tokens and the Claude plan's limits (rendering only).

Data comes from spec_to_test.llm.claude_code: tokens from the request's result
event, limits (percent used, reset time) from the local `/usage` command before
and after the request. The percentages belong to the whole account, so other
Claude sessions running at the same time are counted too; the page says so.
"""

from datetime import datetime

import streamlit as st

from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import t
from spec_to_test.llm.claude_code import GenerationUsage, LimitChange, PlanLimit, PlanUsage, TokenUsage


def number(value: int, lang: str) -> str:
    text = f"{value:,}"
    return text if lang == "en" else text.replace(",", " ")


def reset_time(value: str) -> str:
    """The reset moment in this computer's time zone ("21:40" today, else "23.10 07:00")."""
    try:
        moment = datetime.fromisoformat(value).astimezone()
    except ValueError:
        return ""
    return moment.strftime("%H:%M" if moment.date() == datetime.now().astimezone().date() else "%d.%m %H:%M")


def limit_label(limit: PlanLimit, lang: str) -> str:
    if limit.kind == "session":
        return t("claude_code.usage.limit.session", lang)
    if limit.kind == "weekly_all":
        return t("claude_code.usage.limit.weekly", lang)
    if limit.kind == "weekly_scoped" and limit.scope:
        return t("claude_code.usage.limit.weekly_scoped", lang, scope=limit.scope)
    return limit.scope or limit.kind


def _percent(value: float) -> str:
    return f"{value:.0f}" if value == int(value) else f"{value:.1f}"


def change_line(change: LimitChange, lang: str) -> str:
    limit = change.limit
    reset = reset_time(limit.resets_at)
    tail = t("claude_code.usage.resets", lang, time=reset) if reset else ""
    if change.delta is None:
        return t("claude_code.usage.now", lang, label=limit_label(limit, lang), after=_percent(limit.percent)) + tail
    delta = t("claude_code.usage.delta_small", lang) if change.delta < 1 else f"+{_percent(change.delta)}%"
    before = _percent(change.before or 0)
    return f"{limit_label(limit, lang)}: {before}% → {_percent(limit.percent)}% ({delta}){tail}"


def tokens_line(tokens: TokenUsage, lang: str) -> str:
    line = t("claude_code.usage.tokens", lang, total=number(tokens.total_tokens, lang),
             input=number(tokens.input_tokens, lang), output=number(tokens.output_tokens, lang),
             cache=number(tokens.cache_read_tokens + tokens.cache_creation_tokens, lang))
    if tokens.models:
        line += f" · {', '.join(tokens.models)}"
    if tokens.duration_ms:
        line += f" · {tokens.duration_ms / 1000:.1f} s"
    return line


def render_generation_usage(usage: GenerationUsage, lang: str) -> None:
    """Tokens and limit changes of one generation, under the editor heading."""
    lines = []
    if usage.tokens is not None:
        lines.append(tokens_line(usage.tokens, lang))
    changes = usage.changes()
    lines += [change_line(change, lang) for change in changes]
    if not changes:
        lines.append(t("claude_code.usage.unavailable", lang))
    body = "\n".join(f"- {escape_markdown(line)}" for line in lines)
    st.info(f"**{t('claude_code.usage.heading', lang)}**\n\n{body}", icon="📊")
    notes = []
    if usage.tokens is not None and usage.tokens.cost_usd_estimate:
        notes.append(t("claude_code.usage.cost", lang, cost=f"{usage.tokens.cost_usd_estimate:.4f}"))
    if changes:
        notes.append(t("claude_code.usage.shared", lang))
    if notes:
        st.caption(" ".join(notes))


def render_plan_usage(plan: PlanUsage | None, lang: str) -> None:
    """The plan's limits right now (the "Check plan limits" button)."""
    if plan is None or not plan.limits:
        st.caption(t("claude_code.usage.unavailable", lang))
        return
    checked = reset_time(plan.checked_at) if plan.checked_at else ""
    lines = [change_line(LimitChange(limit=limit), lang) for limit in plan.limits]
    st.caption(t("claude_code.usage.current", lang, time=checked) + "  \n"
               + "  \n".join(escape_markdown(line) for line in lines))
