"""Localization checks across every feature in English, Ukrainian and Russian."""

import re

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT
from spec_to_test import ai_analysis
from spec_to_test.i18n import LANGUAGES, TRANSLATIONS, t
from spec_to_test.models import AISuggestion, AISuggestionType

APP_PATH = str(PROJECT_ROOT / "app.py")

# Keys whose text is legitimately identical in all languages (names, IDs, formats).
SAME_IN_ALL_LANGUAGES = {
    "app.title", "column.id", "tc.title_positive", "tc.value_expectation",
    "unit.megabytes", "ai.configured", "export.mapping_body",
}
KEY_PREFIXES = sorted({key.split(".")[0] for key in TRANSLATIONS}, key=len, reverse=True)
RAW_KEY = re.compile(rf"(?<![\w/-])(?:{'|'.join(KEY_PREFIXES)})\.[a-z_]+(?:\.[a-z_]+)?(?![\w.])")
FILE_NAMES = re.compile(r"\.(?:txt|md|toml|json|csv|py|env)\b")

SUGGESTION = AISuggestion(
    id="AI-001",
    type=AISuggestionType.MISSING_SCENARIO,
    requirement_ids=["REQ-3"],
    description="No behavior for an expired link.",
    quote="expires after 30 minutes",
    quote_verified=True,
    question="What happens when an expired link is opened?",
)


def test_translations_are_not_english_copies():
    copies = {
        key
        for key, entry in TRANSLATIONS.items()
        if key not in SAME_IN_ALL_LANGUAGES and (entry["uk"] == entry["en"] or entry["ru"] == entry["en"])
    }
    assert not copies, f"untranslated keys: {sorted(copies)}"


def test_ukrainian_and_russian_differ_where_expected():
    # Catch copy-paste between UK and RU for sentences (labels may coincide, e.g. "Дашборд").
    same = {k for k, e in TRANSLATIONS.items() if e["uk"] == e["ru"] and len(e["en"]) > 40}
    assert not same - SAME_IN_ALL_LANGUAGES, sorted(same)


def visible_text(at: AppTest) -> list[str]:
    texts: list[str] = []
    for kind in ("markdown", "caption", "info", "warning", "error", "success", "title", "subheader", "toast"):
        texts += [str(el.value) for el in getattr(at, kind)]
    for kind in ("button", "checkbox", "text_input", "text_area", "metric", "expander", "tabs"):
        texts += [str(el.label) for el in getattr(at, kind)]
    texts += [str(el.label) for el in at.get("download_button")]
    for kind in ("selectbox", "multiselect"):
        for el in getattr(at, kind):
            texts += [str(el.label), *map(str, el.options)]
    for table in at.table:
        frame = table.value
        texts += [str(c) for c in frame.columns]
        texts += [str(v) for v in frame.to_numpy().ravel()]
    texts += [str(el.value) for el in at.sidebar.caption] + [str(el.value) for el in at.sidebar.info]
    return texts


def raw_keys(texts: list[str]) -> set[str]:
    found = set()
    for text in texts:
        for match in RAW_KEY.finditer(text):
            if not FILE_NAMES.match(text, match.start() + match.group(0).find(".")):
                found.add(match.group(0))
    return found


@pytest.fixture
def full_app(example_text, monkeypatch):
    """App with every feature populated: findings, tests, bugs, design, AI results."""
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    monkeypatch.setattr(ai_analysis, "run_ai_analysis", lambda *args, **kwargs: [SUGGESTION])
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
    next(b for b in at.button if b.key == "bug_generate").click().run()
    next(c for c in at.checkbox if c.key == "ai_consent").check().run()
    next(b for b in at.button if b.key == "ai_run").click().run()
    next(s for s in at.selectbox if s.key == "design_req").select("REQ-8").run()
    assert not at.exception
    return at


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_every_feature_is_translated(full_app, lang):
    at = full_app
    at.sidebar.selectbox[0].select(lang).run()
    assert not at.exception
    texts = visible_text(at)
    assert not raw_keys(texts), raw_keys(texts)
    joined = "\n".join(texts)
    for key in ("tab.dashboard", "tab.rtm", "tab.tests", "tab.design", "tab.defects", "tab.ai", "tab.export"):
        assert t(key, lang) in joined
    assert t("ai.disclaimer", lang, model="claude-opus-5-5") in joined
    assert t("design.dt", lang) in joined
    assert t("export.markdown", lang) in joined


def test_non_english_ui_has_no_english_feature_labels(full_app):
    at = full_app
    at.sidebar.selectbox[0].select("ru").run()
    joined = "\n".join(visible_text(at))
    for english in ("Dashboard", "Test cases", "Bug reports", "Coverage", "Export only Approved"):
        assert english not in joined


def test_generated_content_uses_the_language_at_generation_time(example_text):
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.sidebar.selectbox[0].select("uk").run()
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
    titles = [str(v) for table in at.table if "Тип тесту" in table.value.columns for v in table.value["Назва"]]
    assert any("граничні значення" in title for title in titles)


def test_raw_key_detector_catches_leaks_but_not_file_names():
    assert raw_keys(["Missing: tab.rtm", "ai.error.unknown_code"]) == {"tab.rtm", "ai.error.unknown_code"}
    assert raw_keys(["pip install -r requirements-ai.txt", "see docs/EXPORTS.md", "REQ-1.2"]) == set()
