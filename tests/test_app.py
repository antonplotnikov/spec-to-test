"""Basic Streamlit UI behaviour using Streamlit's built-in AppTest."""

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, home

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
    assert app.title[0].value == "Home"  # the page title; the brand is in the sidebar
    assert app.sidebar.radio(key="app_mode").value == "home"
    assert app.button(key="analyze").label == "Analyze"
    assert any("Paste requirements" in info.value for info in app.info)


def test_language_switch_translates_ui(app):
    app.selectbox(key="language").select("uk").run()
    assert app.button(key="analyze").label == "Аналізувати"
    app.selectbox(key="language").select("ru").run()
    assert app.button(key="analyze").label == "Анализировать"


def test_empty_input_shows_translated_error(app):
    app.selectbox(key="language").select("ru").run()
    home(app).button(key="analyze").click().run()
    assert app.error[0].value == "Поле пустое. Пожалуйста, введите требования."


def test_analyze_shows_requirements_and_findings(app, example_text):
    home(app).text_area(key="requirements_text").input(example_text).run()
    home(app).button(key="analyze").click().run()
    assert not app.exception
    assert not app.error
    assert app.metric[0].value == "9"
    assert len(table_with(app, "Requirement")) == 9
    assert len(table_with(app, "Issue")) > 0


# --- Stability, repeated analyses and uploads --------------------------------

def test_repeated_analysis_replaces_previous_results(app):
    home(app).text_area(key="requirements_text").input("REQ-1: The system must save drafts.\nREQ-2: The page should load fast.").run()
    home(app).button(key="analyze").click().run()
    assert app.metric[0].value == "2"
    home(app).text_area(key="requirements_text").input("REQ-9: The system must show a list.").run()
    home(app).button(key="analyze").click().run()
    assert app.metric[0].value == "1"
    assert app.metric[1].value == "0"
    assert not app.exception


def test_error_after_success_clears_old_results(app):
    home(app).text_area(key="requirements_text").input("REQ-1: The system must save drafts.").run()
    home(app).button(key="analyze").click().run()
    assert app.metric
    home(app).text_area(key="requirements_text").input("   ").run()
    home(app).button(key="analyze").click().run()
    assert app.error[0].value == "The input is empty. Please enter some requirements."
    assert not app.metric  # stale results are not shown


def test_language_switch_after_analysis_translates_results(app, example_text):
    home(app).text_area(key="requirements_text").input(example_text).run()
    home(app).button(key="analyze").click().run()
    app.selectbox(key="language").select("uk").run()
    assert not app.exception
    assert app.metric[0].label == "Вимоги"
    assert app.tabs[1].label == "Знахідки"
    findings = table_with(app, "Проблема")
    assert "Неоднозначне формулювання" in set(findings["Проблема"])
    assert set(findings["Джерело"]) == {"На основі правил"}


def test_findings_table_uses_original_requirement_ids(app, example_text):
    home(app).text_area(key="requirements_text").input(example_text).run()
    home(app).button(key="analyze").click().run()
    requirements = table_with(app, "Requirement")
    findings = table_with(app, "Issue")
    assert list(requirements["ID"]) == [f"REQ-{n}" for n in range(1, 10)]
    assert set(findings["ID"]) <= set(requirements["ID"])
    ambiguous = findings[findings["Issue"] == "Ambiguous wording"]
    assert set(ambiguous["ID"]) == {"REQ-5", "REQ-6"}


def test_uploaded_markdown_file_is_analyzed(app, example_text):
    home(app).file_uploader[0].upload("spec.md", example_text.encode("utf-8"), "text/markdown").run()
    assert any("uploaded file" in info.value for info in app.info)
    home(app).button(key="analyze").click().run()
    assert not app.error and not app.exception
    assert app.metric[0].value == "9"


def test_uploaded_invalid_pdf_shows_translated_error(app):
    app.selectbox(key="language").select("uk").run()
    home(app).file_uploader[0].upload("spec.pdf", b"not a pdf", "application/pdf").run()
    home(app).button(key="analyze").click().run()
    assert app.error[0].value == "Файл не є коректним PDF."
    assert not app.exception


def test_uploaded_file_takes_precedence_over_text(app):
    home(app).text_area(key="requirements_text").input("REQ-1: The system must save drafts.").run()
    home(app).file_uploader[0].upload("spec.txt", b"REQ-7: The system must show a list.", "text/plain").run()
    home(app).button(key="analyze").click().run()
    assert list(table_with(app, "Requirement")["ID"]) == ["REQ-7"]


def test_unparseable_text_shows_error_not_crash(app):
    home(app).text_area(key="requirements_text").input("# Only a heading\n---").run()
    home(app).button(key="analyze").click().run()
    assert app.error[0].value == "No requirement statements were found in the text."
    assert not app.exception
