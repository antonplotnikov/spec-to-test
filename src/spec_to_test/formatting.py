"""Helpers for showing user text safely in Markdown-rendered places.

Streamlit renders table cells, warnings and st.markdown as Markdown. User
requirements must be shown exactly as written: `**must**` should not turn
bold, and `![x](https://…)` must not load an external image. Escaping keeps
the visible text identical to the source.
"""

import re

# Characters with inline meaning in CommonMark / GitHub-flavored Markdown.
_INLINE_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~$!])")
# Block markers that only matter at the start of a line and before a space:
# "- x", "+ x", "1. x", "2) x"; plus "---" / "===" lines (rules, setext headings).
_BULLET_START = re.compile(r"^(\s*)([-+])(?=\s)", re.MULTILINE)
_ORDERED_START = re.compile(r"^(\s*\d+)([.)])(?=\s|$)", re.MULTILINE)
_RULE_LINE = re.compile(r"^(\s*)(?=[-=]{2,}\s*$)", re.MULTILINE)


def escape_markdown(text: str) -> str:
    """Return text that renders literally in Markdown."""
    escaped = _INLINE_SPECIAL.sub(r"\\\1", text)
    escaped = _BULLET_START.sub(r"\1\\\2", escaped)
    escaped = _RULE_LINE.sub(r"\1\\", escaped)
    return _ORDERED_START.sub(r"\1\\\2", escaped)


def markdown_cell(text: object) -> str:
    """Escape a value for a Markdown table cell (pipes and line breaks included)."""
    value = escape_markdown(str(text)) if isinstance(text, str) else str(text)
    return value.replace("\r\n", "\n").replace("\n", "<br>")
