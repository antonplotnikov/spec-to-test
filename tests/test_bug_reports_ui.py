"""Bug Reports page: generate from free text, review, edit, save, delete and download."""

from test_app_features import button, new_app
from test_projects_ui import create_project

from conftest import goto
from spec_to_test import storage
from spec_to_test.bug_generator.store import DiskBugReportStore
from spec_to_test.models import Severity, Source
from spec_to_test.projects import DEFAULT_PROJECT_ID

BUG = (
    "I logged in as admin, opened the Orders page and clicked Export. Then I get a 500 error instead of the "
    "CSV file. Happens every time since release 2.3.1 in Chrome 120 on Windows 11."
)


def editor(at, kind: str, field: str):
    """The editor widget of `field` (its key ends with the report ID and a reload counter)."""
    return next(w for w in getattr(at, kind) if w.key and w.key.startswith(f"br_{field}_"))


def generate(at, text: str = BUG):
    goto(at, "bug_reports")
    at.text_area(key="bug_report_text").input(text).run()
    button(at, "bug_generate").click().run()
    assert not at.exception, at.exception
    return at


def save(at):
    button(at, "bug_report_save").click().run()
    assert not at.exception, at.exception
    return at


def saved(project_id: str = DEFAULT_PROJECT_ID):
    return DiskBugReportStore().reports(project_id)


def download_labels(at) -> list[str]:
    return [b.label for b in at.get("download_button")]


def test_page_works_without_a_requirements_document():
    at = goto(new_app(), "bug_reports")
    assert not at.exception
    assert at.title[0].value == "Bug Reports"
    assert any("No saved bug reports" in i.value for i in at.info)


def test_generate_shows_a_draft_that_is_not_saved_yet():
    at = generate(new_app())
    assert editor(at, "text_input", "title").value == "Clicked Export — 500 error (Orders page)"
    assert editor(at, "text_area", "steps").value == "Opened the Orders page\nClicked Export"
    assert editor(at, "text_area", "where").value == "Orders page"
    assert editor(at, "selectbox", "severity").value == Severity.HIGH
    assert any("Not saved yet" in i.value for i in at.info)
    assert any("Evidence:" in w.value for w in at.warning)  # Missing Information
    assert saved() == []
    assert "Download BR-001 (Markdown)" not in download_labels(at)


def test_empty_fields_are_marked_needs_clarification():
    at = generate(new_app(), "The button is slightly misaligned")
    expected = editor(at, "text_area", "expected_result")
    assert expected.value == "" and expected.placeholder == "Needs clarification"
    assert "Expected Result: what should happen" in at.warning[0].value


def test_save_edit_and_download():
    at = save(generate(new_app()))
    [report] = saved()
    assert report.id == "BR-001" and report.source == Source.RULE
    assert "Download BR-001 (Markdown)" in download_labels(at)
    assert "Download all (Markdown)" in download_labels(at)
    assert any("BR-001" in str(v) for v in at.table[0].value.to_numpy().ravel())

    editor(at, "text_input", "title").input("Export of orders fails with 500")
    editor(at, "text_area", "expected_result").input("A CSV file with the orders is downloaded")
    editor(at, "selectbox", "severity").set_value(Severity.MEDIUM)
    save(at)
    [report] = saved()
    assert report.title == "Export of orders fails with 500"
    assert report.expected_result == "A CSV file with the orders is downloaded"
    assert (report.severity, report.severity_source) == (Severity.MEDIUM, Source.USER)
    assert report.source == Source.USER
    assert editor(at, "text_input", "title").value == "Export of orders fails with 500"  # editor shows the saved values


def test_a_typed_marker_is_saved_as_empty():
    at = generate(new_app())
    editor(at, "text_area", "where").input("Needs clarification")
    save(at)
    assert saved()[0].where == ""


def test_next_report_gets_the_next_id_and_saved_reports_can_be_reopened():
    at = save(generate(new_app()))
    save(generate(at, "Opening the profile shows a blank screen."))
    assert [r.id for r in saved()] == ["BR-001", "BR-002"]
    at.selectbox(key="bug_report_pick").set_value("BR-001").run()
    button(at, "bug_report_open_button").click().run()
    assert editor(at, "text_input", "title").value == "Clicked Export — 500 error (Orders page)"


def test_delete_needs_confirmation():
    at = save(generate(new_app()))
    assert button(at, "bug_report_delete_BR-001").disabled
    at.checkbox(key="bug_report_confirm_BR-001").check().run()
    button(at, "bug_report_delete_BR-001").click().run()
    assert not at.exception
    assert saved() == []
    assert any("No saved bug reports" in i.value for i in at.info)


def test_discarding_a_draft_saves_nothing():
    at = generate(new_app())
    button(at, "bug_report_discard").click().run()
    assert not any(w.key and w.key.startswith("br_title_") for w in at.text_input)
    assert saved() == []


def test_empty_description_shows_an_error():
    at = goto(new_app(), "bug_reports")
    button(at, "bug_generate").click().run()
    assert not at.exception
    assert at.error[0].value == "Describe the bug first."


def other_project_id() -> str:
    return next(p.id for p in storage.list_projects() if p.id != DEFAULT_PROJECT_ID)


def test_reports_belong_to_the_project():
    at = save(generate(new_app()))
    create_project(at, "Mobile app")
    goto(at, "bug_reports")
    assert any("No saved bug reports" in i.value for i in at.info)
    assert not any(w.key and w.key.startswith("br_title_") for w in at.text_input)
    save(generate(at, "Opening the profile shows a blank screen."))
    assert [r.id for r in saved(other_project_id())] == ["BR-001"]  # numbered per project
    assert [r.title for r in saved()] == ["Clicked Export — 500 error (Orders page)"]


def test_deleting_a_project_deletes_its_bug_reports():
    at = new_app()
    create_project(at, "Throwaway")
    save(generate(at))
    project_id = other_project_id()
    assert len(saved(project_id)) == 1
    goto(at, "settings")
    at.checkbox(key="project_confirm_delete").check().run()
    button(at, "project_delete").click().run()
    assert not at.exception
    assert saved(project_id) == []


def test_page_is_translated():
    at = new_app()
    at.selectbox(key="language").select("ru").run()
    generate(at, "Нажимаю «Сохранить», и ничего не происходит.")
    assert at.title[0].value == "Баг-репорты"
    assert editor(at, "text_area", "expected_result").placeholder == "Требует уточнения"
    assert "Ожидаемый результат: что должно произойти" in at.warning[0].value
