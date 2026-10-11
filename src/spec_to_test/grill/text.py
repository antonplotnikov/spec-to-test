"""Turn Grill findings and questions into text in the interface language."""

from enum import StrEnum

from spec_to_test.grill.drafts import AnyDraft, editable_fields
from spec_to_test.grill.models import Choice, Priority, Provenance, Question, Reproducibility, ReviewFinding
from spec_to_test.i18n import t
from spec_to_test.models import Severity, TestType

# Translation prefix for each enumerated value type.
_ENUM_LABELS: dict[type[StrEnum], str] = {
    TestType: "test_type",
    Severity: "severity",
    Reproducibility: "grill.reproducibility",
    Priority: "grill.priority",
}


def field_label(field: str, lang: str = "en") -> str:
    return t(f"grill.field.{field}", lang) if field else ""


def render_finding(finding: ReviewFinding, lang: str = "en") -> tuple[str, str]:
    """Return (message, suggested fix). Literal text (e.g. from AI) is kept as is."""
    params = {**finding.params, "field": field_label(finding.field, lang)}
    message = t(finding.message_key, lang, **params) if finding.message_key else finding.message_text
    if finding.suggestion_key:
        suggestion = t(finding.suggestion_key, lang, **params)
    else:
        suggestion = finding.suggestion_text
    return message, suggestion


def render_question(question: Question, lang: str = "en") -> tuple[str, str]:
    """Return (prompt, why it matters)."""
    prompt = t(question.prompt_key, lang, **question.params) if question.prompt_key else question.prompt_text
    reason = t(question.reason_key, lang, **question.params) if question.reason_key else question.reason_text
    return prompt, reason


def render_choice(choice: Choice, lang: str = "en") -> str:
    return t(choice.label_key, lang) if choice.label_key else (choice.label_text or choice.value)


def render_error(code: str, lang: str = "en") -> str:
    return t(f"grill.error.{code}", lang)


def value_text(draft: AnyDraft, field: str, lang: str = "en") -> str:
    """A draft value as display text: lists one item per line, choices translated."""
    value = getattr(draft, field)
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(value)
    for enum, prefix in _ENUM_LABELS.items():
        if isinstance(value, enum):
            return t(f"{prefix}.{value.value}", lang)
    return str(value)


def provenance_label(draft: AnyDraft, field: str, lang: str = "en") -> str:
    source = draft.provenance.get(field)
    return t(f"grill.provenance.{source.value}", lang) if source else ""


def draft_rows(draft: AnyDraft, lang: str = "en") -> list[tuple[str, str, str]]:
    """(field label, value, where the value came from) for every editable field.

    Empty fields are included, so gaps stay visible in the final result.
    """
    rows = []
    for field in editable_fields(draft):
        value = value_text(draft, field, lang)
        origin = provenance_label(draft, field, lang)
        if not value and draft.provenance.get(field) != Provenance.UNKNOWN:
            origin = ""
        rows.append((field_label(field, lang), value, origin))
    return rows
