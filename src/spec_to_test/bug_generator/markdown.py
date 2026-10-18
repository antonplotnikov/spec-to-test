"""Markdown export of product bug reports.

Every field is written, empty ones as "Needs clarification", so the reader sees
what the reporter did not say. Severity and priority are labeled preliminary,
with what they were based on. The reporter's description is quoted at the end.
"""

from spec_to_test.bug_generator.models import ProductBugReport, missing_information
from spec_to_test.i18n import t
from spec_to_test.models import Source


def _marker(lang: str) -> str:
    return f"*{t('bugreport.needs_clarification', lang)}*"


def _text(value: str, lang: str) -> str:
    return value.strip() or _marker(lang)


def _inline(value: str, lang: str) -> str:
    return " ".join(value.split()) or _marker(lang)


def _bullets(items: list[str], lang: str, numbered: bool = False) -> str:
    if not items:
        return _marker(lang)
    return "\n".join(f"{i}. {item}" if numbered else f"- {item}" for i, item in enumerate(items, start=1))


def _quoted(terms: list[str]) -> str:
    return ", ".join(f"“{term}”" for term in terms)


def severity_note(report: ProductBugReport, lang: str) -> str:
    """Why the severity is what it is (empty when there is none)."""
    if report.severity is None:
        return ""
    if report.severity_source == Source.USER:
        if report.severity_basis:
            return t("bugreport.basis.user", lang, terms=_quoted(report.severity_basis))
        return t("bugreport.basis.edited", lang)
    if report.severity_source == Source.AI:
        return t("bugreport.basis.ai", lang, terms=_quoted(report.severity_basis))
    if report.severity_basis:
        return t("bugreport.basis.rule", lang, terms=_quoted(report.severity_basis))
    return t("bugreport.basis.functional", lang)


def priority_note(report: ProductBugReport, lang: str) -> str:
    if report.priority is None:
        return ""
    if report.priority_source == Source.USER:
        if report.priority_basis:
            return t("bugreport.basis.user", lang, terms=_quoted(report.priority_basis))
        return t("bugreport.basis.edited", lang)
    if report.priority_source == Source.AI:
        return t("bugreport.basis.ai", lang, terms=_quoted(report.priority_basis))
    reasons = "; ".join(t(f"bugreport.priority_basis.{code}", lang) for code in report.priority_basis)
    return t("bugreport.priority_basis.rule", lang, reasons=reasons) if reasons else ""


def _level(report: ProductBugReport, lang: str, kind: str) -> str:
    value = getattr(report, kind)
    if value is None:
        return _marker(lang)
    label = t(f"severity.{value.value}" if kind == "severity" else f"grill.priority.{value.value}", lang)
    note = severity_note(report, lang) if kind == "severity" else priority_note(report, lang)
    return f"{label} — {note}" if note else label


def by_generator(key: str, report: ProductBugReport) -> str:
    """The translation key for what generated the report (rules have the plain key)."""
    return key if report.generated_by == "rules" else f"{key}.{report.generated_by}"


def bug_report_markdown(report: ProductBugReport, lang: str = "en") -> str:
    def field(name: str) -> str:
        return t(f"bugreport.field.{name}", lang)

    missing = missing_information(report)
    lines = [
        f"# {report.id}: {_inline(report.title, lang)}",
        "",
        f"> {t(by_generator('bugreport.md.note', report), lang)}"
        + (f" {t('bugreport.md.edited', lang)}" if report.source == Source.USER else ""),
        "",
        f"- **{field('what')}:** {_inline(report.what, lang)}",
        f"- **{field('where')}:** {_inline(report.where, lang)}",
        f"- **{field('when')}:** {_inline(report.when, lang)}",
        "",
        f"## {field('preconditions')}", "", _bullets(report.preconditions, lang), "",
        f"## {field('steps')}", "", _bullets(report.steps, lang, numbered=True), "",
        f"## {field('actual_result')}", "", _text(report.actual_result, lang), "",
        f"## {field('expected_result')}", "", _text(report.expected_result, lang), "",
        f"## {field('environment')}", "", _bullets(report.environment, lang), "",
        f"## {t('bugreport.md.severity_priority', lang)}", "",
        f"- **{t('bugreport.md.severity', lang)}:** {_level(report, lang, 'severity')}",
        f"- **{t('bugreport.md.priority', lang)}:** {_level(report, lang, 'priority')}",
        "", f"_{t('bugreport.preliminary', lang)}_", "",
        f"## {field('missing')}", "",
        "\n".join(f"- {t(f'bugreport.missing.{code}', lang)}" for code in missing) or t("bugreport.missing_none", lang),
    ]
    if report.unassigned:
        lines += ["", f"## {field('unassigned')}", "", _bullets(report.unassigned, lang)]
    if report.description.strip():
        quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in report.description.splitlines())
        lines += ["", f"## {field('description')}", "", quoted]
    return "\n".join(lines).rstrip() + "\n"


def bug_reports_markdown(reports: list[ProductBugReport], lang: str = "en") -> str:
    return "\n---\n\n".join(bug_report_markdown(report, lang) for report in reports)
