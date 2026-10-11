"""Regression tests: user text must be shown literally, never rendered as Markdown."""

import pytest

from spec_to_test.formatting import escape_markdown, markdown_cell


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("show *all* items", r"show \*all\* items"),
        ("[help](http://x)", r"\[help\](http://x)"),
        ("![img](http://x/a.png)", r"\!\[img\](http://x/a.png)"),
        ("a_b_c", r"a\_b\_c"),
        ("`code`", r"\`code\`"),
        ("<b>bold</b>", r"\<b\>bold\</b\>"),
        ("# heading", r"\# heading"),
        ("- item", r"\- item"),
        ("1. item", r"1\. item"),
        ("price $5", r"price \$5"),
        ("11.1%", "11.1%"),
        ("-2 degrees", "-2 degrees"),
        ("2) item", r"2\) item"),
        ("---", r"\---"),
        ("Title\n===", "Title\n\\==="),
        ("REQ-1: plain text, 8 characters.", "REQ-1: plain text, 8 characters."),
        ("Пароль — щонайменше 8 символів", "Пароль — щонайменше 8 символів"),
    ],
)
def test_escape_markdown(raw, escaped):
    assert escape_markdown(raw) == escaped


def test_ids_and_badges_are_unchanged():
    for value in ["REQ-001", "FR-AUTH-01", "TC-012, TC-013", "✅ Covered", "⚠️ Needs clarification"]:
        assert escape_markdown(value) == value


def test_markdown_cell_handles_pipes_and_newlines():
    assert markdown_cell("a | b\nc") == r"a \| b<br>c"
    assert markdown_cell(42) == "42"
