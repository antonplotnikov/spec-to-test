"""Bug Report Generator: free text → structured product bug report (rule-based, nothing invented)."""

import json

import pytest

from spec_to_test import storage
from spec_to_test.bug_generator.extract import BugInputError, generate_bug_report
from spec_to_test.bug_generator.markdown import bug_report_markdown, bug_reports_markdown
from spec_to_test.bug_generator.models import (
    MAX_DESCRIPTION_CHARS,
    ProductBugReport,
    edited_report,
    missing_information,
    next_report_id,
)
from spec_to_test.bug_generator.store import (
    MAX_REPORTS,
    BugStoreError,
    DiskBugReportStore,
    SessionBugReportStore,
    open_bug_report_store,
)
from spec_to_test.grill.models import Priority
from spec_to_test.models import Severity, Source

EN = (
    "I logged in as admin, opened the Orders page and clicked Export. Then I get a 500 error instead of the "
    "CSV file. Happens every time since release 2.3.1 in Chrome 120 on Windows 11."
)
RU = (
    "Пользователь авторизован как менеджер. Открываю раздел «Отчёты», выбираю период за месяц и нажимаю "
    "«Сформировать». Отчёт формируется больше минуты, затем появляется пустая таблица. Ожидаю таблицу с данными "
    "за выбранный период. Chrome 126, стейдж, сборка 512."
)
UK = "Коли я натискаю «Зберегти» у профілі, з'являється помилка. Очікується, що зміни збережуться. Стейдж, версія 1.4."
LABELED = """## Summary
Login button does nothing

## Steps to reproduce
1. Go to https://shop.example.com/login
2. Enter valid email and password
3. Click Log in

## Expected
User is redirected to the dashboard

## Actual
Nothing happens, console shows TypeError

Environment: unknown
"""


def generate(text: str) -> ProductBugReport:
    return generate_bug_report(text, "BR-001", "2026-10-17T10:00:00+00:00")


def words_of(report: ProductBugReport) -> set[str]:
    """Every word of the generated fields (not of the kept description)."""
    fields = [report.title, report.what, report.where, report.when, report.actual_result, report.expected_result,
              *report.preconditions, *report.steps, *report.environment, *report.unassigned]
    return {w.strip("«»\"'.,;:()—").casefold() for f in fields for w in f.split()} - {"", "—"}


# --- WWW and QA fields from prose ---------------------------------------------------------

def test_english_prose_fills_www_and_qa_fields():
    report = generate(EN)
    assert report.what == "500 error"
    assert report.where == "Orders page"
    assert report.when == "every time; since release 2.3.1"
    assert report.preconditions == ["I logged in as admin"]
    assert report.steps == ["Opened the Orders page", "Clicked Export"]
    assert report.actual_result == "I get a 500 error"
    assert report.expected_result == "The CSV file"
    assert report.environment == ["release 2.3.1", "Chrome 120", "Windows 11"]
    assert report.title == "Clicked Export — 500 error (Orders page)"
    assert report.unassigned == []
    assert report.source == Source.RULE


def test_russian_prose():
    report = generate(RU)
    assert report.preconditions == ["Пользователь авторизован как менеджер"]
    assert report.steps == ["Открываю раздел «Отчёты»", "Выбираю период за месяц", "Нажимаю «Сформировать»"]
    assert report.actual_result == "Отчёт формируется больше минуты. Появляется пустая таблица"
    assert report.expected_result == "Ожидаю таблицу с данными за выбранный период"
    assert report.where == "раздел «Отчёты»"
    assert report.environment == ["Chrome 126", "стейдж", "сборка 512"]


def test_ukrainian_prose_takes_the_step_from_the_trigger():
    report = generate(UK)
    assert report.when == "Коли я натискаю «Зберегти» у профілі"
    assert report.steps == ["Я натискаю «Зберегти» у профілі"]
    assert report.actual_result == "З'являється помилка"
    assert report.expected_result == "Очікується, що зміни збережуться"
    assert report.where == "у профілі"
    assert report.environment == ["Стейдж", "версія 1.4"]
    assert report.title == "Коли я натискаю «Зберегти» у профілі — з'являється помилка"


def test_a_place_before_the_action_is_still_a_step():
    report = generate("На странице оформления заказа нажимаю кнопку «Оплатить», и ничего не происходит. "
                      "Должно открыться окно оплаты.")
    assert report.steps == ["На странице оформления заказа нажимаю кнопку «Оплатить»"]
    assert report.actual_result == "Ничего не происходит"
    assert report.where == "На странице оформления заказа"
    assert report.expected_result == "Должно открыться окно оплаты"


def test_where_and_environment_never_come_from_the_expected_result():
    report = generate("I click Save and nothing happens. It should redirect to the Orders page in Chrome.")
    assert report.where == ""
    assert report.environment == []
    assert report.expected_result == "It should redirect to the Orders page in Chrome"


def test_lists_and_proper_names_with_and_stay_in_one_clause():
    report = generate("Open the Terms and Conditions page, fill name, email and phone and click Send. "
                      "The form shows an error.")
    assert report.steps == ["Open the Terms and Conditions page", "Fill name, email and phone", "Click Send"]
    assert report.actual_result == "The form shows an error"


# --- Labeled text -----------------------------------------------------------------------

def test_labeled_markdown_sections_are_used_as_written():
    report = generate(LABELED)
    assert report.title == "Login button does nothing"
    assert report.steps == ["Go to https://shop.example.com/login", "Enter valid email and password", "Click Log in"]
    assert report.expected_result == "User is redirected to the dashboard"
    assert report.actual_result == "Nothing happens, console shows TypeError"
    assert report.where == "https://shop.example.com/login"
    assert report.environment == []  # "unknown" means not known, not a value


def test_inline_labeled_steps_are_split():
    report = generate("Steps: open settings -> change language -> save\nActual: language is not changed")
    assert report.steps == ["Open settings", "Change language", "Save"]
    assert report.actual_result == "language is not changed"


def test_labels_in_russian_and_ukrainian_and_environment_labels():
    report = generate("Шаги:\n1. Открыть корзину\n2. Нажать «Оформить»\nФактический результат: кнопка неактивна\n"
                      "Ожидаемый результат: открывается оформление\nБраузер: Firefox 125\nОС: Ubuntu 24.04")
    assert report.steps == ["Открыть корзину", "Нажать «Оформить»"]
    assert report.actual_result == "кнопка неактивна"
    assert report.expected_result == "открывается оформление"
    assert report.environment == ["Браузер: Firefox 125", "ОС: Ubuntu 24.04"]
    uk = generate("Кроки: відкрити кошик\nОчікуваний результат: кошик відкрито\nСерйозність: висока")
    assert uk.steps == ["Відкрити кошик"] and uk.expected_result == "кошик відкрито"
    assert uk.severity == Severity.HIGH and uk.severity_source == Source.USER


def test_prose_does_not_override_a_labeled_field():
    report = generate("Steps:\n1. Open the cart\n\nI also clicked Pay twice.\nActual: nothing happens")
    assert report.steps == ["Open the cart"]
    assert "I also clicked Pay twice" in report.unassigned


# --- Nothing is invented ----------------------------------------------------------------

def test_missing_facts_stay_empty_and_are_listed():
    report = generate("The button is slightly misaligned")
    assert report.actual_result == "The button is slightly misaligned"
    assert (report.where, report.when, report.expected_result) == ("", "", "")
    assert report.preconditions == report.steps == report.environment == []
    assert missing_information(report) == [
        "where", "when", "preconditions", "steps", "expected_result", "environment", "evidence",
    ]


@pytest.mark.parametrize("text", [EN, RU, UK, LABELED, "the app crashed when i uploaded a photo on my pixel 7"])
def test_every_generated_word_comes_from_the_description(text):
    report = generate(text)
    source = {w.strip("«»\"'.,;:()—").casefold() for w in text.split()}
    assert words_of(report) <= source


def test_text_without_a_bug_gives_an_empty_report():
    report = generate("Привет! Посмотрите пожалуйста.")
    assert report.title == report.what == report.actual_result == ""
    assert report.severity is None and report.priority is None
    assert report.unassigned == ["Посмотрите пожалуйста"]
    assert {"title", "what", "actual_result", "severity", "priority"} <= set(missing_information(report))


def test_description_is_kept_verbatim():
    assert generate(EN).description == EN


@pytest.mark.parametrize(("text", "code"), [("", "empty"), ("   \n ", "empty"), ("x" * (MAX_DESCRIPTION_CHARS + 1), "too_long")])
def test_unusable_descriptions_are_refused(text, code):
    with pytest.raises(BugInputError) as error:
        generate(text)
    assert error.value.code == code


# --- Severity and priority are preliminary -----------------------------------------------

@pytest.mark.parametrize(
    ("text", "severity", "basis"),
    [
        ("Open the app. It crashes.", Severity.HIGH, ["crashes"]),
        ("I click Export and get a 500 error.", Severity.HIGH, ["500"]),
        ("Click Log in. Nothing happens.", Severity.HIGH, ["Nothing happens", "Log in"]),
        ("Нажимаю «Оплатить», и ничего не происходит.", Severity.HIGH, ["Ничего не происходит", "Оплатить"]),
        ("The footer has a typo.", Severity.LOW, ["typo"]),
        ("Опечатка в заголовке страницы.", Severity.LOW, ["Опечатка"]),
        ("Open the profile. The avatar is not updated.", Severity.MEDIUM, []),
    ],
)
def test_severity_is_suggested_from_the_actual_result(text, severity, basis):
    report = generate(text)
    assert (report.severity, report.severity_source, report.severity_basis) == (severity, Source.RULE, basis)


def test_priority_follows_severity_and_is_lower_when_not_every_time():
    assert generate("Open the app. It crashes.").priority == Priority.HIGH
    sometimes = generate("Open the app. It crashes sometimes.")
    assert (sometimes.severity, sometimes.priority) == (Severity.HIGH, Priority.MEDIUM)
    assert sometimes.priority_basis == ["follows_severity", "lowered_intermittent"]


def test_stated_severity_and_priority_are_kept_with_the_reporters_word():
    report = generate("Actual: total shows 0\nSeverity: Critical\nPriority: Low")
    assert (report.severity, report.severity_source, report.severity_basis) == (Severity.HIGH, Source.USER, ["Critical"])
    assert (report.priority, report.priority_source, report.priority_basis) == (Priority.LOW, Source.USER, ["Low"])


def test_unknown_severity_value_is_not_guessed():
    report = generate("Actual: total shows 0\nSeverity: S2")
    assert report.severity_source == Source.RULE  # the rule suggestion, not "S2" mapped by guesswork
    assert "Severity: S2" in report.unassigned


# --- Missing Information ------------------------------------------------------------------

def test_missing_information_follows_the_fields():
    report = generate(EN)
    assert missing_information(report) == ["evidence"]
    partial = report.model_copy(update={"environment": ["Chrome 120"], "steps": ["Click Export"], "when": "after login"})
    assert missing_information(partial) == ["frequency", "steps_one", "env_version", "evidence"]
    same = report.model_copy(update={"expected_result": "I get a 500 error."})
    assert "actual_equals_expected" in missing_information(same)
    assert "evidence" not in missing_information(generate("Login fails, see the attached screenshot."))


# --- Editing ------------------------------------------------------------------------------

def editor_values(report: ProductBugReport, **changes: str) -> dict[str, str]:
    values = {name: getattr(report, name) for name in ("title", "what", "where", "when", "actual_result",
                                                        "expected_result")}
    values |= {name: "\n".join(getattr(report, name)) for name in ("preconditions", "steps", "environment",
                                                                   "unassigned")}
    return values | changes


def test_saving_unchanged_values_keeps_the_report_as_generated():
    report = generate(EN)
    same = edited_report(report, editor_values(report), report.severity, report.priority, "later")
    assert same == report


def test_edits_are_cleaned_and_markers_are_never_saved_as_facts():
    report = generate(EN)
    values = editor_values(report, where="  Needs clarification ", expected_result="Требует уточнения",
                           steps="1. Open the Orders page\n\n- Click Export\nПотребує уточнення")
    updated = edited_report(report, values, report.severity, report.priority, "2026-10-17T11:00:00+00:00")
    assert updated.where == updated.expected_result == ""
    assert updated.steps == ["Open the Orders page", "Click Export"]
    assert updated.source == Source.USER and updated.updated_at == "2026-10-17T11:00:00+00:00"
    assert updated.created_at == report.created_at
    assert {"where", "expected_result"} <= set(missing_information(updated))


def test_changing_severity_or_priority_marks_it_as_set_by_a_person():
    report = generate(EN)
    updated = edited_report(report, editor_values(report), Severity.MEDIUM, None, "later")
    assert (updated.severity, updated.severity_source, updated.severity_basis) == (Severity.MEDIUM, Source.USER, [])
    assert updated.priority is None and updated.priority_source == Source.USER
    assert "priority" in missing_information(updated)


def test_report_ids():
    assert next_report_id([]) == "BR-001"
    reports = [ProductBugReport(id="BR-001"), ProductBugReport(id="BR-007")]
    assert next_report_id(reports) == "BR-008"
    with pytest.raises(ValueError):
        ProductBugReport(id="../etc")


# --- Markdown -----------------------------------------------------------------------------

def test_markdown_has_every_field_and_marks_missing_ones():
    report = generate("The button is slightly misaligned")
    text = bug_report_markdown(report, "en")
    for heading in ("## Preconditions", "## Steps to Reproduce", "## Actual Result", "## Expected Result",
                    "## Environment", "## Severity / Priority (preliminary)", "## Missing Information",
                    "## Original description"):
        assert heading in text
    assert "- **Where:** *Needs clarification*" in text
    assert "- **Severity:** Low — Suggested by rule from: “misaligned”" in text
    assert "Severity and priority are preliminary recommendations" in text
    assert "- Where: on which page, screen, URL or component does it happen?" in text
    assert "> The button is slightly misaligned" in text


def test_markdown_is_translated_and_numbers_steps():
    text = bug_report_markdown(generate(RU), "ru")
    assert "## Шаги воспроизведения\n\n1. Открываю раздел «Отчёты»\n2. Выбираю период за месяц" in text
    assert "- **Where (где):** раздел «Отчёты»" in text
    assert "Требует уточнения" not in text.split("## Недостающая информация")[0].split("## Предусловия")[1]


def test_markdown_of_several_reports():
    first, second = generate(EN), generate(UK).model_copy(update={"id": "BR-002"})
    text = bug_reports_markdown([first, second])
    assert text.count("\n---\n") == 1 and "# BR-001:" in text and "# BR-002:" in text


# --- Storage ------------------------------------------------------------------------------

def test_session_store_add_update_delete():
    store = SessionBugReportStore()
    report = generate(EN)
    store.save("p1", report)
    store.save("p1", report.model_copy(update={"title": "Changed"}))
    assert [r.title for r in store.reports("p1")] == ["Changed"]
    assert store.reports("p2") == []
    store.delete("p1", report.id)
    assert store.reports("p1") == []
    store.save("p1", report)
    store.delete_project("p1")
    assert store.reports("p1") == []


def test_store_refuses_more_than_the_limit():
    store = SessionBugReportStore()
    store._write("p1", {"format": "spec-to-test/bug-reports", "format_version": 1,
                        "reports": [{"id": f"BR-{i:03d}"} for i in range(1, MAX_REPORTS + 1)]})
    with pytest.raises(BugStoreError):
        store.save("p1", ProductBugReport(id="BR-999"))


def test_disk_store_round_trip_and_project_deletion(tmp_path):
    store = DiskBugReportStore()
    report = generate(RU)
    store.save("default", report)
    store.save("abc123", report)
    assert store.reports("default") == [report]
    assert (storage.data_dir() / "bug_reports.json").exists()
    assert (storage.data_dir() / "projects" / "abc123" / "bug_reports.json").exists()
    storage.delete_project("default")
    storage.delete_project("abc123")
    assert store.reports("default") == store.reports("abc123") == []


def test_disk_store_skips_unreadable_reports():
    path = storage.data_dir() / "bug_reports.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    good = generate(EN).model_dump(mode="json")
    path.write_text(json.dumps({"format": "spec-to-test/bug-reports", "format_version": 1,
                                "reports": [good, {"id": "nope"}, "x", good]}), encoding="utf-8")
    assert [r.id for r in DiskBugReportStore().reports("default")] == ["BR-001"]
    path.write_text("not json", encoding="utf-8")
    assert DiskBugReportStore().reports("default") == []


def test_session_mode_never_writes_to_disk(monkeypatch):
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE")
    state: dict = {}
    store = open_bug_report_store(state)
    assert isinstance(store, SessionBugReportStore) and open_bug_report_store(state) is store
    store.save("default", generate(EN))
    assert not (storage.data_dir() / "bug_reports.json").exists()
    with pytest.raises(ValueError):
        storage.bug_reports_path("../x")
