"""Turn the user's input into a Grill draft, without guessing.

- Requirements are split by the existing input parser and kept verbatim.
- A pasted test case or bug report is read by its labels ("Steps:",
  "Expected result:", "Кроки:", "Ожидаемый результат:", ...). Values found
  this way are marked as coming from the source. Text without a recognized
  label is returned separately so the UI can show it; it is never assigned to
  a field by guesswork.
- "Unknown" (in any supported language) marks the field as unknown.
"""

import re
from enum import StrEnum

from pydantic import BaseModel, Field

from spec_to_test.grill.drafts import AnyDraft, editable_fields, is_list_field
from spec_to_test.grill.models import (
    BugReportDraft,
    Priority,
    Provenance,
    Reproducibility,
    RequirementsDraft,
    TestCaseDraft,
)
from spec_to_test.i18n import LANGUAGES, TRANSLATIONS
from spec_to_test.input_parser import extract_requirements, validate_text
from spec_to_test.models import Severity, TestType

# Extra labels besides the translated field names (all compared case-insensitively).
_SYNONYMS: dict[str, list[str]] = {
    "title": ["name", "test case", "test", "заголовок", "назва тесту", "название теста"],
    "objective": ["goal", "purpose", "aim", "ціль", "задача"],
    "requirement_id": ["requirement", "requirements", "req", "req id", "вимога", "вимоги", "требование", "требования"],
    "feature": ["feature", "functionality", "area", "module", "функціональність", "функциональность", "модуль"],
    "test_type": ["type", "тип"],
    "preconditions": ["precondition", "pre-conditions", "pre-condition", "setup", "передумова", "предусловие"],
    "test_data": ["data", "input", "inputs", "дані", "данные", "вхідні дані", "входные данные"],
    "steps": ["steps to reproduce", "str", "test steps", "кроки відтворення", "шаги воспроизведения"],
    "expected_result": ["expected", "expected results", "expected behavior", "expected behaviour",
                        "очікувано", "ожидаемо", "очікувана поведінка", "ожидаемое поведение"],
    "summary": ["title", "заголовок", "назва", "название", "суть"],
    "environment": ["env", "platform", "browser", "среда", "платформа"],
    "app_version": ["version", "build", "release", "версія", "версия", "збірка", "сборка", "реліз", "релиз"],
    "actual_result": ["actual", "actual results", "actual behavior", "actual behaviour",
                      "фактично", "фактическое поведение", "фактична поведінка"],
    "reproducibility": ["reproducible", "repro", "frequency", "частота"],
    "evidence": ["attachments", "attachment", "screenshots", "screenshot", "logs", "log", "вкладення",
                 "вложения", "скриншоти", "скриншоты", "логи"],
    "severity": ["серьезность", "критичність", "критичность"],
    "priority": [],
}
_UNKNOWN = {"unknown", "not known", "невідомо", "невідоме", "неизвестно", "неизвестное"}
_LABEL_LINE = re.compile(r"^\s*(?:#{1,6}\s*)?\**(?P<label>[^:*#]{1,40}?)\**\s*:\s*\**\s*(?P<rest>.*)$")
_BULLET = re.compile(r"^\s*(?:[-*+•–—·]|\d{1,3}[.)]|step\s*\d+[.:)]?|крок\s*\d+[.:)]?|шаг\s*\d+[.:)]?)\s+", re.I)

_ENUMS: dict[str, tuple[type[StrEnum], str]] = {
    "test_type": (TestType, "test_type"),
    "severity": (Severity, "severity"),
    "reproducibility": (Reproducibility, "grill.reproducibility"),
    "priority": (Priority, "grill.priority"),
}


class ParsedDraft(BaseModel):
    draft: TestCaseDraft | BugReportDraft
    # Lines the parser could not assign to a field (shown to the user, never guessed).
    unparsed: list[str] = Field(default_factory=list)


def requirements_draft(text: str) -> RequirementsDraft:
    """Split a document into verbatim requirements (raises InputError if invalid)."""
    return RequirementsDraft(requirements=extract_requirements(text))


def _key(text: str) -> str:
    return " ".join(text.replace("’", "'").split()).casefold()


def _labels(draft_type: type[TestCaseDraft] | type[BugReportDraft]) -> dict[str, str]:
    """Normalized label -> field name for one draft type."""
    labels: dict[str, str] = {}
    fields = editable_fields(draft_type())
    for field in fields:
        names = [TRANSLATIONS[f"grill.field.{field}"][lang] for lang in LANGUAGES] + [field.replace("_", " ")]
        for name in names + _SYNONYMS.get(field, []):
            labels.setdefault(_key(name), field)
    # A synonym must not steal the label of another field ("title" is the summary of a bug).
    for field in fields:
        for lang in LANGUAGES:
            labels[_key(TRANSLATIONS[f"grill.field.{field}"][lang])] = field
    return {label: field for label, field in labels.items() if field in fields}


def _enum_value(field: str, raw: str) -> str | None:
    enum, label_prefix = _ENUMS[field]
    wanted = _key(raw).rstrip(".")
    for member in enum:
        names = {member.value, member.value.replace("_", " ")}
        names |= {TRANSLATIONS[f"{label_prefix}.{member.value}"][lang] for lang in LANGUAGES}
        if wanted in {_key(name) for name in names}:
            return str(member.value)
    return None


def parse_draft(text: str, draft_type: type[TestCaseDraft] | type[BugReportDraft]) -> ParsedDraft:
    """Read a labeled test case or bug report. Values found become SOURCE facts."""
    labels = _labels(draft_type)
    sections: dict[str, list[str]] = {}
    label_text: dict[str, str] = {}
    unparsed: list[str] = []
    current: str | None = None
    for line in validate_text(text).split("\n"):
        match = _LABEL_LINE.match(line)
        field = labels.get(_key(match.group("label"))) if match else None
        if match and field:
            current = field
            sections.setdefault(field, [])
            label_text[field] = match.group("label").strip()
            if rest := match.group("rest").strip():
                sections[field].append(rest)
        elif match and not _BULLET.match(line):
            # An unknown label ("Note: ...") starts text that belongs to no field.
            current = None
            unparsed.append(line.strip())
        elif line.strip():
            (sections[current] if current else unparsed).append(line.strip())

    empty = draft_type()
    values: dict[str, object] = {}
    provenance: dict[str, Provenance] = {}
    for field, lines in sections.items():
        if not lines:
            continue
        joined = "\n".join(lines)
        if _key(joined).rstrip(".") in _UNKNOWN:
            provenance[field] = Provenance.UNKNOWN
            continue
        if field in _ENUMS:
            # One option per field; further lines are not part of the value.
            unparsed += lines[1:]
            value = _enum_value(field, lines[0])
            if value is None:  # not a known option: keep it visible instead of guessing
                unparsed.append(f"{label_text[field]}: {lines[0]}")
                continue
            values[field] = value
        elif is_list_field(empty, field):
            values[field] = [_BULLET.sub("", item).strip() for item in lines if _BULLET.sub("", item).strip()]
        else:
            values[field] = joined
        provenance[field] = Provenance.SOURCE
    draft = draft_type.model_validate({**values, "provenance": provenance})
    return ParsedDraft(draft=draft, unparsed=unparsed)


def mark_source(draft: AnyDraft) -> AnyDraft:
    """Mark every filled field without provenance as coming from the source."""
    provenance = dict(draft.provenance)
    for field in editable_fields(draft):
        value = getattr(draft, field)
        if field not in provenance and value not in (None, "", []):
            provenance[field] = Provenance.SOURCE
    return draft.model_copy(update={"provenance": provenance}, deep=True)
