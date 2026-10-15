import re

import pytest

from conftest import PROJECT_ROOT
from spec_to_test.i18n import LANGUAGES, TRANSLATIONS, UNIT_FORMS, clarification_question, t, unit_for
from spec_to_test.models import Finding, FindingType, Severity, Source
from spec_to_test.quantities import UNITS


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


@pytest.mark.parametrize("lang", list(LANGUAGES))
@pytest.mark.parametrize("unit", sorted(UNITS))
def test_every_quantity_unit_is_translated(unit, lang):
    assert t(f"unit.{unit}", lang) != f"unit.{unit}"


# Units that read the same after any number in every language.
INVARIANT_UNITS = {"kilobytes", "megabytes", "gigabytes", "percent", "eur"}


def test_every_unit_has_number_forms_or_is_invariant():
    assert set(UNIT_FORMS) | INVARIANT_UNITS == set(UNITS)
    assert not set(UNIT_FORMS) & INVARIANT_UNITS
    assert all(set(forms) == {"uk", "ru"} for forms in UNIT_FORMS.values())


@pytest.mark.parametrize(("unit", "lang", "by_number"), [
    ("weeks", "ru", {"1": "неделя", "2": "недели", "5": "недель", "21": "неделя", "0.5": "недели"}),
    ("weeks", "uk", {"1": "тиждень", "2": "тижні", "5": "тижнів", "21": "тиждень", "0.5": "тижня"}),
    ("years", "ru", {"1": "год", "2": "года", "5": "лет", "21": "год", "11": "лет"}),
    ("years", "uk", {"1": "рік", "2": "роки", "5": "років", "21": "рік", "12": "років"}),
    ("usd", "ru", {"1": "доллар США", "2": "доллара США", "5": "долларов США", "21": "доллар США"}),
    ("usd", "uk", {"1": "долар США", "2": "долари США", "5": "доларів США", "0.5": "долара США"}),
    ("uah", "ru", {"1": "гривна", "2": "гривны", "5": "гривен", "21": "гривна"}),
    ("characters", "uk", {"1": "символ", "2": "символи", "5": "символів", "8 – 64": "символи"}),
    ("items", "ru", {"1": "позиция", "2": "позиции", "5": "позиций", "< 21": "позиция"}),
])
def test_unit_takes_the_form_of_the_number(unit, lang, by_number):
    assert {n: unit_for(unit, n, lang) for n in by_number} == by_number


@pytest.mark.parametrize("lang", ["uk", "ru"])
@pytest.mark.parametrize("unit", sorted(UNIT_FORMS))
@pytest.mark.parametrize(("number", "form"), [("1", 0), ("2", 1), ("5", None), ("21", 0)])
def test_every_declined_unit_follows_the_number(unit, lang, number, form):
    expected = t(f"unit.{unit}", lang) if form is None else UNIT_FORMS[unit][lang][form]
    assert unit_for(unit, number, lang) == expected


@pytest.mark.parametrize("unit", sorted(UNITS))
def test_english_and_invariant_units_never_change(unit):
    for number in ("1", "2", "5", "21", "0.5"):
        assert unit_for(unit, number, "en") == t(f"unit.{unit}", "en")
        if unit in INVARIANT_UNITS:
            assert all(unit_for(unit, number, lang) == t(f"unit.{unit}", lang) for lang in ("uk", "ru"))
