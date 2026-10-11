import re

import pytest

from conftest import PROJECT_ROOT
from spec_to_test.i18n import LANGUAGES, TRANSLATIONS, clarification_question, t
from spec_to_test.models import Finding, FindingType, Severity, Source


def placeholders(text: str) -> set[str]:
    return set(re.findall(r"{(\w+)}", text))


def test_three_languages_with_english_default():
    assert list(LANGUAGES) == ["en", "uk", "ru"]
    assert t("input.analyze_button") == "Analyze"


@pytest.mark.parametrize("key", sorted(TRANSLATIONS))
def test_every_key_is_translated_with_same_placeholders(key):
    entry = TRANSLATIONS[key]
    assert set(entry) == set(LANGUAGES), f"{key} is missing a language"
    assert all(value.strip() for value in entry.values())
    expected = placeholders(entry["en"])
    for lang, value in entry.items():
        assert placeholders(value) == expected, f"{key} [{lang}] placeholders differ"


def test_switching_language_changes_text():
    assert t("input.analyze_button", "en") == "Analyze"
    assert t("input.analyze_button", "uk") == "Аналізувати"
    assert t("input.analyze_button", "ru") == "Анализировать"


def test_placeholders_are_filled():
    assert t("error.file_too_large", "uk", max_mb=2) == "Файл завеликий (максимум 2 МБ)."


def test_unknown_language_falls_back_to_english():
    assert t("input.analyze_button", "de") == "Analyze"


def test_unknown_key_is_returned_as_is():
    assert t("does.not.exist", "ru") == "does.not.exist"


def test_every_error_code_used_by_parser_is_translated():
    source = (PROJECT_ROOT / "src" / "spec_to_test" / "input_parser.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'InputError\(\s*"(\w+)"', source))
    assert codes, "no error codes found"
    for code in codes:
        assert f"error.{code}" in TRANSLATIONS


def test_every_enum_value_has_a_label():
    for kind in FindingType:
        assert f"finding.{kind.value}" in TRANSLATIONS
        assert f"question.{kind.value}" in TRANSLATIONS
    for severity in Severity:
        assert f"severity.{severity.value}" in TRANSLATIONS
    for source in Source:
        assert f"source.{source.value}" in TRANSLATIONS


def test_rule_and_ai_sources_have_distinct_labels():
    for lang in LANGUAGES:
        assert t("source.rule", lang) != t("source.ai", lang)


def test_clarification_question_includes_terms_and_related_ids():
    finding = Finding(
        requirement_id="REQ-1",
        type=FindingType.CONTRADICTION,
        severity=Severity.HIGH,
        matched_terms=["8 characters", "10 characters"],
        related_requirement_ids=["REQ-2"],
    )
    question = clarification_question(finding, "en")
    assert "REQ-2" in question and '"8 characters"' in question
    assert "REQ-2" in clarification_question(finding, "ru")
