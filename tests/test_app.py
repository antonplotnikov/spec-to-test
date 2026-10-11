"""Basic Streamlit UI behaviour using Streamlit's built-in AppTest."""

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT

APP_PATH = str(PROJECT_ROOT / "app.py")


def table_with(app: AppTest, column: str):
    """Find a table by one of its column names (tabs render several tables)."""
    return next(table.value for table in app.table if column in table.value.columns)


@pytest.fixture
def app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    return at


def test_app_starts_in_english_with_empty_state(app):
    assert not app.exception
    assert app.title[0].value == "Spec-to-Test"
    assert app.button[0].label == "Analyze"
    assert any("Paste requirements" in info.value for info in app.info)


def test_language_switch_translates_ui(app):
    app.sidebar.selectbox[0].select("uk").run()
    assert app.button[0].label == "Аналізувати"
    app.sidebar.selectbox[0].select("ru").run()
    assert app.button[0].label == "Анализировать"


def test_empty_input_shows_translated_error(app):
    app.sidebar.selectbox[0].select("ru").run()
    app.button[0].click().run()
    assert app.error[0].value == "Поле пустое. Пожалуйста, введите требования."


def test_analyze_shows_requirements_and_findings(app, example_text):
    app.text_area[0].input(example_text).run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert app.metric[0].value == "9"
    assert len(table_with(app, "Requirement")) == 9
    assert len(table_with(app, "Issue")) > 0


# --- Stability, repeated analyses and uploads --------------------------------

def test_repeated_analysis_replaces_previous_results(app):
    app.text_area[0].input("REQ-1: The system must save drafts.\nREQ-2: The page should load fast.").run()
    app.button[0].click().run()
    assert app.metric[0].value == "2"
    app.text_area[0].input("REQ-9: The system must show a list.").run()
    app.button[0].click().run()
    assert app.metric[0].value == "1"
    assert app.metric[1].value == "0"
    assert not app.exception


def test_error_after_success_clears_old_results(app):
    app.text_area[0].input("REQ-1: The system must save drafts.").run()
    app.button[0].click().run()
    assert app.metric
    app.text_area[0].input("   ").run()
    app.button[0].click().run()
    assert app.error[0].value == "The input is empty. Please enter some requirements."
    assert not app.metric  # stale results are not shown


def test_language_switch_after_analysis_translates_results(app, example_text):
    app.text_area[0].input(example_text).run()
    app.button[0].click().run()
    app.sidebar.selectbox[0].select("uk").run()
    assert not app.exception
    assert app.metric[0].label == "Вимоги"
    assert app.tabs[1].label == "Знахідки"
    findings = table_with(app, "Проблема")
    assert "Неоднозначне формулювання" in set(findings["Проблема"])
    assert set(findings["Джерело"]) == {"На основі правил"}


def test_findings_table_uses_original_requirement_ids(app, example_text):
    app.text_area[0].input(example_text).run()
    app.button[0].click().run()
    requirements = table_with(app, "Requirement")
    findings = table_with(app, "Issue")
    assert list(requirements["ID"]) == [f"REQ-{n}" for n in range(1, 10)]
    assert set(findings["ID"]) <= set(requirements["ID"])
    ambiguous = findings[findings["Issue"] == "Ambiguous wording"]
    assert set(ambiguous["ID"]) == {"REQ-5", "REQ-6"}


def test_uploaded_markdown_file_is_analyzed(app, example_text):
    app.file_uploader[0].upload("spec.md", example_text.encode("utf-8"), "text/markdown").run()
    assert any("uploaded file" in info.value for info in app.info)
    app.button[0].click().run()
    assert not app.error and not app.exception
    assert app.metric[0].value == "9"


def test_uploaded_invalid_pdf_shows_translated_error(app):
    app.sidebar.selectbox[0].select("uk").run()
    app.file_uploader[0].upload("spec.pdf", b"not a pdf", "application/pdf").run()
    app.button[0].click().run()
    assert app.error[0].value == "Файл не є коректним PDF."
    assert not app.exception


def test_uploaded_file_takes_precedence_over_text(app):
    app.text_area[0].input("REQ-1: The system must save drafts.").run()
    app.file_uploader[0].upload("spec.txt", b"REQ-7: The system must show a list.", "text/plain").run()
    app.button[0].click().run()
    assert list(table_with(app, "Requirement")["ID"]) == ["REQ-7"]


def test_unparseable_text_shows_error_not_crash(app):
    app.text_area[0].input("# Only a heading\n---").run()
    app.button[0].click().run()
    assert app.error[0].value == "No requirement statements were found in the text."
    assert not app.exception
