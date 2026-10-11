"""Reading user input into Grill drafts without guessing."""

import pytest

from spec_to_test.grill.inputs import mark_source, parse_draft, requirements_draft
from spec_to_test.grill.models import (
    BugReportDraft,
    GrillKind,
    GrillMode,
    GrillStep,
    Priority,
    Provenance,
    Reproducibility,
    TestCaseDraft,
)
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.input_parser import InputError
from spec_to_test.models import Severity, TestType

TEST_CASE_EN = """Login with a valid password
Title: Valid login
Requirement: REQ-1
Type: Positive
Preconditions:
- A registered user exists
- The login page is open
Steps:
1. Enter the email
2) Enter the password
Step 3: Click "Log in"
Expected result: The dashboard opens
"""


def test_requirements_are_kept_verbatim_with_real_ids():
    draft = requirements_draft("REQ-7: The session expires after 30 minutes.\nREQ-8: Users can log out.")
    assert [(r.id, r.text) for r in draft.requirements] == [
        ("REQ-7", "The session expires after 30 minutes."), ("REQ-8", "Users can log out."),
    ]
    assert draft.statements == []


def test_empty_requirements_input_is_rejected():
    with pytest.raises(InputError):
        requirements_draft("   ")


def test_labeled_test_case_is_parsed_into_source_facts():
    parsed = parse_draft(TEST_CASE_EN, TestCaseDraft)
    draft = parsed.draft
    assert draft.title == "Valid login" and draft.requirement_id == "REQ-1"
    assert draft.test_type == TestType.POSITIVE
    assert draft.preconditions == ["A registered user exists", "The login page is open"]
    assert draft.steps == ["Enter the email", "Enter the password", 'Click "Log in"']
    assert draft.expected_result == "The dashboard opens"
    assert set(draft.provenance.values()) == {Provenance.SOURCE}
    # Text without a label is reported, never assigned to a field.
    assert parsed.unparsed == ["Login with a valid password"]
    assert draft.objective == ""


@pytest.mark.parametrize("text", [
    "Назва: Вхід\nТип тесту: Негативний\nКроки:\n- Ввести пароль\nОчікуваний результат: Помилка",
    "**Название:** Вход\n## Тип теста: Негативный\nШаги:\n- Ввести пароль\nОжидаемый результат: Ошибка",
])
def test_ukrainian_and_russian_labels_are_recognized(text):
    draft = parse_draft(text, TestCaseDraft).draft
    assert draft.title in ("Вхід", "Вход")
    assert draft.test_type == TestType.NEGATIVE
    assert draft.steps == ["Ввести пароль"]
    assert draft.expected_result in ("Помилка", "Ошибка")


def test_bug_report_labels_enums_and_unknown_values():
    text = """Title: Save crashes the editor
Environment: unknown
Version: 1.0.0
Steps to reproduce:
1. Open a document
2. Click Save
Actual result: The editor closes
Expected result: The document is saved
Reproducibility: Intermittently
Severity: Висока
Priority: urgent
Attachments: console.log
"""
    parsed = parse_draft(text, BugReportDraft)
    draft = parsed.draft
    assert draft.summary == "Save crashes the editor"
    assert draft.environment == "" and draft.provenance["environment"] == Provenance.UNKNOWN
    assert draft.app_version == "1.0.0"
    assert draft.reproducibility == Reproducibility.INTERMITTENT
    assert draft.severity == Severity.HIGH
    assert draft.evidence == ["console.log"]
    # "urgent" is not a known priority: shown to the user, not mapped by guesswork.
    assert draft.priority is None and "priority" not in draft.provenance
    assert parsed.unparsed == ["Priority: urgent"]


def test_extra_lines_after_an_option_are_not_merged_into_it():
    parsed = parse_draft("Priority: High\nCall me later", BugReportDraft)
    assert parsed.draft.priority == Priority.HIGH
    assert parsed.unparsed == ["Call me later"]


def test_text_without_labels_produces_an_empty_draft():
    parsed = parse_draft("The save button does not work", BugReportDraft)
    assert parsed.draft == BugReportDraft()
    assert parsed.unparsed == ["The save button does not work"]


def test_parsed_draft_review_asks_only_for_what_is_missing():
    parsed = parse_draft(TEST_CASE_EN, TestCaseDraft)
    session = WF.start(GrillKind.TEST_CASE, GrillMode.REVIEW_DRAFT)
    session = WF.submit_input(session, parsed.draft, TEST_CASE_EN)
    assert session.step == GrillStep.ASK_QUESTION
    assert [q.id for q in session.questions] == ["tc.objective", "tc.test_data"]
    assert session.input_text == TEST_CASE_EN


def test_mark_source_only_marks_filled_fields_without_provenance():
    draft = TestCaseDraft(title="T", steps=["S"], provenance={"steps": Provenance.USER_CONFIRMED})
    marked = mark_source(draft)
    assert marked.provenance == {"title": Provenance.SOURCE, "steps": Provenance.USER_CONFIRMED}
    assert draft.provenance == {"steps": Provenance.USER_CONFIRMED}  # input untouched


def test_unknown_labels_are_not_merged_into_the_previous_field():
    parsed = parse_draft("Actual result: The editor closes\nNote to self: check logs\nmore notes\n"
                         "Steps:\n1. Click: Save", BugReportDraft)
    assert parsed.draft.actual_result == "The editor closes"
    assert parsed.unparsed == ["Note to self: check logs", "more notes"]
    assert parsed.draft.steps == ["Click: Save"]  # a numbered step may contain a colon
