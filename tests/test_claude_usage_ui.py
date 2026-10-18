"""Formatting of Claude Code usage (claude_usage_ui)."""

from datetime import UTC, datetime, timedelta

import claude_usage_ui as ui
from spec_to_test.llm.claude_code import LimitChange, PlanLimit, TokenUsage


def test_numbers_by_language():
    assert ui.number(1234567, "en") == "1,234,567"
    assert ui.number(1234567, "ru") == "1 234 567"


def test_reset_time_is_local_and_short_for_today():
    soon = datetime.now(UTC) + timedelta(minutes=5)
    later = datetime.now(UTC) + timedelta(days=3)
    assert ui.reset_time(soon.isoformat()) == soon.astimezone().strftime("%H:%M")
    assert ui.reset_time(later.isoformat()) == later.astimezone().strftime("%d.%m %H:%M")
    assert ui.reset_time("not a date") == ""


def test_limit_labels():
    assert ui.limit_label(PlanLimit(kind="session"), "en") == "Session limit"
    assert ui.limit_label(PlanLimit(kind="weekly_all"), "uk") == "Тижневий ліміт (усі моделі)"
    assert ui.limit_label(PlanLimit(kind="weekly_scoped", scope="Opus"), "ru") == "Недельный лимит (Opus)"
    assert ui.limit_label(PlanLimit(kind="new_meter"), "en") == "new_meter"


def test_change_lines():
    limit = PlanLimit(kind="session", percent=38.5, resets_at="")
    assert ui.change_line(LimitChange(limit=limit, before=36), "en") == "Session limit: 36% → 38.5% (+2.5%)"
    assert ui.change_line(LimitChange(limit=limit, before=38.5), "en") == "Session limit: 38.5% → 38.5% (less than 1%)"
    assert ui.change_line(LimitChange(limit=limit), "ru") == "Лимит сессии: использовано 38.5%"


def test_tokens_line():
    tokens = TokenUsage(input_tokens=1800, output_tokens=545, cache_read_tokens=100, models=["claude-sonnet-5-5"],
                        duration_ms=12300)
    assert ui.tokens_line(tokens, "en") == (
        "2,445 tokens: 1,800 input, 545 output, 100 cache · claude-sonnet-5-5 · 12.3 s")
