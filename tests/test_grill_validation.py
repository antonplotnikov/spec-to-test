"""Deterministic Grill checks, draft editing and localization of findings."""

import re

import pytest

from conftest import PROJECT_ROOT
from spec_to_test.grill import validation
from spec_to_test.grill.drafts import DraftError, apply_answer, editable_fields, merge_edit, set_field
from spec_to_test.grill.models import (
    Answer,
    AnswerStatus,
    BugReportDraft,
    FindingLevel,
    Priority,
    Provenance,
    Question,
    Reproducibility,
    RequirementsDraft,
    ReviewCategory,
    ReviewFinding,
    Statement,
    TestCaseDraft,
)
from spec_to_test.grill.text import render_finding
from spec_to_test.grill.validation import CHECK_CODES, check_bug_report, check_requirements, check_test_case
from spec_to_test.i18n import LANGUAGES, TRANSLATIONS
from spec_to_test.models import Requirement, Severity, TestType

GRILL_SRC = PROJECT_ROOT / "src" / "spec_to_test" / "grill"


def keyed(findings: list[ReviewFinding]) -> set[tuple[str, str, str]]:
    return {(f.level.value, f.field, f.message_key.removeprefix("grill.check.")) for f in findings}


def complete_test_case(**changes) -> TestCaseDraft:
    fields = dict(
        title="Reset link is sent", objective="Verify the reset email", requirement_id="REQ-1",
        test_type=TestType.POSITIVE, preconditions=["A registered user exists"],
        steps=["Open the reset page", "Submit the email"], expected_result="A reset email is sent",
    )
    return TestCaseDraft(**{**fields, **changes})


def complete_bug(**changes) -> BugReportDraft:
    fields = dict(
        summary="Save button crashes the editor", environment="Chrome 140, macOS 15", app_version="1.0.0",
        steps=["Open a document", "Click Save"], actual_result="The editor closes with an error",
        expected_result="The document is saved", reproducibility=Reproducibility.ALWAYS,
        evidence=["Console log excerpt"], severity=Severity.HIGH, priority=Priority.HIGH,
    )
    return BugReportDraft(**{**fields, **changes})


# --- Test cases -----------------------------------------------------------------------

def test_complete_test_case_has_no_findings():
    assert check_test_case(complete_test_case(), {"REQ-1"}) == []


def test_empty_test_case_reports_required_fields_as_blocking():
    found = keyed(check_test_case(TestCaseDraft()))
    for field in ("title", "test_type", "steps", "expected_result"):
        assert ("blocking", field, "required_missing") in found
    assert ("blocking", "requirement_id", "subject_missing") in found
    assert ("suggestion", "preconditions", "recommended_missing") in found


def test_missing_expected_result_and_preconditions():
    found = keyed(check_test_case(complete_test_case(expected_result="", preconditions=[]), {"REQ-1"}))
    assert found == {
        ("blocking", "expected_result", "required_missing"),
        ("suggestion", "preconditions", "recommended_missing"),
    }


def test_invented_requirement_id_is_blocking():
    found = keyed(check_test_case(complete_test_case(requirement_id="REQ-99"), {"REQ-1"}))
    assert found == {("blocking", "requirement_id", "unknown_requirement")}


def test_requirement_id_without_document_is_unverified():
    found = keyed(check_test_case(complete_test_case(), None))
    assert found == {("warning", "requirement_id", "unverified_requirement")}


def test_feature_without_requirement_link_is_flagged_for_coverage():
    found = keyed(check_test_case(complete_test_case(requirement_id="", feature="Password reset"), {"REQ-1"}))
    assert found == {("warning", "requirement_id", "no_requirement_link")}


@pytest.mark.parametrize("text", ["TBD", "todo", "???", "...", "<enter email>", "N/A"])
def test_placeholders_are_flagged(text):
    found = keyed(check_test_case(complete_test_case(expected_result=text), {"REQ-1"}))
    assert ("warning", "expected_result", "placeholder") in found


def test_real_text_is_not_a_placeholder():
    found = keyed(check_test_case(complete_test_case(expected_result="Error: <b> tags are escaped"), {"REQ-1"}))
    assert not any(code == "placeholder" for _, _, code in found)


def test_duplicate_steps_are_flagged():
    draft = complete_test_case(steps=["Click Save", "click save.", "Close"])
    assert ("warning", "steps", "duplicate") in keyed(check_test_case(draft, {"REQ-1"}))


def test_assumptions_and_ai_values_are_not_treated_as_facts():
    draft = complete_test_case(
        assumptions=["The SMTP server is available"],
        provenance={"steps": Provenance.ASSUMPTION, "expected_result": Provenance.AI_SUGGESTION},
    )
    found = keyed(check_test_case(draft, {"REQ-1"}))
    assert ("warning", "steps", "assumption_field") in found
    assert ("warning", "expected_result", "ai_field") in found
    assert ("warning", "assumptions", "assumptions_listed") in found


# --- Bug reports ----------------------------------------------------------------------

def test_complete_bug_report_has_no_findings():
    assert check_bug_report(complete_bug()) == []


def test_missing_reproduction_steps_and_results_are_blocking():
    found = keyed(check_bug_report(complete_bug(steps=[], actual_result="", expected_result="")))
    assert found == {
        ("blocking", "steps", "required_missing"),
        ("blocking", "actual_result", "required_missing"),
        ("blocking", "expected_result", "required_missing"),
    }


def test_unknown_environment_is_reported_not_invented():
    draft = complete_bug(environment="", provenance={"environment": Provenance.UNKNOWN})
    before = draft.model_dump()
    found = keyed(check_bug_report(draft))
    assert found == {("warning", "environment", "unknown_value")}
    assert draft.model_dump() == before  # checks never fill in values


def test_incomplete_bug_draft_lists_every_gap_without_guessing():
    draft = BugReportDraft(summary="Crash", steps=["Click Save"], actual_result="Crash", expected_result="Saved")
    found = keyed(check_bug_report(draft))
    for field in ("environment", "app_version", "reproducibility", "severity", "priority"):
        assert ("warning", field, "required_missing") in found
    assert ("suggestion", "evidence", "recommended_missing") in found
    assert draft.severity is None and draft.priority is None and draft.evidence == []


def test_actual_equal_to_expected_is_a_contradiction():
    found = keyed(check_bug_report(complete_bug(actual_result="The document is saved.")))
    assert ("blocking", "actual_result", "actual_equals_expected") in found


def test_bug_requirement_link_is_optional_but_must_exist():
    assert check_bug_report(complete_bug(requirement_id=""), {"REQ-1"}) == []
    found = keyed(check_bug_report(complete_bug(requirement_id="REQ-7"), {"REQ-1"}))
    assert found == {("blocking", "requirement_id", "unknown_requirement")}


# --- Requirements ---------------------------------------------------------------------

REQ = Requirement(id="REQ-1", text="The page should load fast.")


def statement_checks(findings: list[ReviewFinding]) -> set[tuple[str, str, str]]:
    """Findings about clarifications only (rule engine findings are tested separately)."""
    return {k for k in keyed(findings) if k[1] == "statements"}


def test_requirements_draft_needs_requirements():
    assert keyed(check_requirements(RequirementsDraft())) == {("blocking", "requirements", "no_requirements")}


def test_statements_must_trace_to_source_requirements():
    draft = RequirementsDraft(
        requirements=[REQ],
        statements=[
            Statement(text="Under 2 seconds", provenance=Provenance.USER_CONFIRMED, requirement_ids=["REQ-1"]),
            Statement(text="Cache pages", provenance=Provenance.USER_CONFIRMED, requirement_ids=["REQ-42"]),
        ],
    )
    assert statement_checks(check_requirements(draft)) == {("blocking", "statements", "statement_unknown_requirement")}


def test_confirmed_facts_and_assumptions_are_kept_apart():
    draft = RequirementsDraft(
        requirements=[REQ],
        statements=[
            Statement(text="Under 2 seconds", provenance=Provenance.USER_CONFIRMED, requirement_ids=["REQ-1"]),
            Statement(text="On a 4G connection", provenance=Provenance.ASSUMPTION, requirement_ids=["REQ-1"]),
            Statement(text="Measured at p95", provenance=Provenance.AI_SUGGESTION, requirement_ids=["REQ-1"]),
        ],
    )
    findings = [f for f in check_requirements(draft) if f.field == "statements"]
    assert statement_checks(findings) == {
        ("warning", "statements", "statement_assumption"),
        ("warning", "statements", "statement_ai"),
    }
    assert {f.params["text"] for f in findings} == {"On a 4G connection", "Measured at p95"}


# --- Draft editing --------------------------------------------------------------------

def test_list_fields_take_one_item_per_line():
    draft = set_field(TestCaseDraft(), "steps", " Open page \n\n Click Save ", Provenance.USER_CONFIRMED)
    assert draft.steps == ["Open page", "Click Save"]


@pytest.mark.parametrize("field,value", [("test_type", "very important"), ("steps", "  \n "), ("provenance", "x")])
def test_invalid_values_and_fields_are_rejected(field, value):
    with pytest.raises(DraftError):
        set_field(TestCaseDraft(), field, value, Provenance.USER_CONFIRMED)


def test_enum_values_are_validated():
    draft = set_field(BugReportDraft(), "severity", "high", Provenance.USER_CONFIRMED)
    assert draft.severity == Severity.HIGH
    with pytest.raises(DraftError):
        set_field(BugReportDraft(), "severity", "blocker", Provenance.USER_CONFIRMED)


def test_unknown_answer_clears_value_and_marks_it():
    question = Question(id="bug.env", field="environment", prompt_key="grill.field.environment")
    draft = apply_answer(complete_bug(), question, Answer(question_id="bug.env", status=AnswerStatus.UNKNOWN))
    assert draft.environment == ""
    assert draft.provenance["environment"] == Provenance.UNKNOWN


def test_clarification_answers_need_a_requirements_draft():
    question = Question(id="q", prompt_text="Why?")
    with pytest.raises(DraftError):
        apply_answer(TestCaseDraft(), question, Answer(question_id="q", status=AnswerStatus.ANSWERED, value="x"))


def test_direct_edit_marks_changed_fields_as_user_confirmed():
    old = complete_test_case(provenance={"title": Provenance.AI_SUGGESTION, "objective": Provenance.SOURCE})
    new = old.model_copy(update={"title": "Better title", "objective": ""})
    merged = merge_edit(old, new)
    assert merged.provenance == {"title": Provenance.USER_CONFIRMED}


def test_protected_fields_are_not_editable():
    assert {"provenance", "draft_type", "requirements", "statements"}.isdisjoint(
        editable_fields(RequirementsDraft()) + editable_fields(TestCaseDraft()) + editable_fields(BugReportDraft())
    )


# --- Localization -------------------------------------------------------------------------

def test_every_check_code_has_message_and_fix():
    for code in CHECK_CODES:
        assert f"grill.check.{code}" in TRANSLATIONS, code
        assert f"grill.fix.{code}" in TRANSLATIONS, code


def test_check_codes_are_used_and_registered():
    source = (GRILL_SRC / "validation.py").read_text(encoding="utf-8")
    registry_end = source.index("_PLACEHOLDER = ")
    body = source[registry_end:]
    unused = {code for code in CHECK_CODES if f'"{code}"' not in body}
    assert not unused, unused  # no dead translations
    translated = {key.removeprefix("grill.check.") for key in TRANSLATIONS if key.startswith("grill.check.")}
    assert translated == set(CHECK_CODES)
    with pytest.raises(ValueError):
        validation._finding(FindingLevel.WARNING, ReviewCategory.CLARITY, "not_registered")


def test_every_error_code_is_translated():
    codes: set[str] = set()
    for path in GRILL_SRC.glob("*.py"):
        codes |= set(re.findall(r'(?:GrillError|DraftError)\(\s*"(\w+)"', path.read_text(encoding="utf-8")))
    assert len(codes) >= 10
    missing = {code for code in codes if f"grill.error.{code}" not in TRANSLATIONS}
    assert not missing, missing


def test_every_grill_enum_and_field_has_a_label():
    for prefix, enum in [
        ("level", FindingLevel), ("category", ReviewCategory), ("provenance", Provenance),
        ("reproducibility", Reproducibility), ("priority", Priority),
    ]:
        for member in enum:
            assert f"grill.{prefix}.{member.value}" in TRANSLATIONS, (prefix, member)
    for draft in (TestCaseDraft(), BugReportDraft(), RequirementsDraft()):
        for field in [*editable_fields(draft), "requirements", "statements"]:
            if field in type(draft).model_fields:
                assert f"grill.field.{field}" in TRANSLATIONS, field


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_findings_render_without_raw_keys(lang):
    draft = BugReportDraft(provenance={"environment": Provenance.UNKNOWN}, assumptions=["x"], steps=["a", "a"])
    findings = check_bug_report(draft, {"REQ-1"}) + check_test_case(complete_test_case(requirement_id="REQ-9"), {"REQ-1"})
    for finding in findings:
        message, suggestion = render_finding(finding, lang)
        assert message and suggestion
        assert "grill." not in message + suggestion
        assert "{" not in message + suggestion
    message, _ = render_finding(findings[0], lang)
    assert lang == "en" or message != render_finding(findings[0], "en")[0]


def test_literal_ai_text_is_rendered_as_is():
    finding = ReviewFinding(
        level=FindingLevel.WARNING, category=ReviewCategory.CLARITY,
        message_text="Step 3 cannot be executed", suggestion_text="Name the button",
    )
    assert render_finding(finding, "uk") == ("Step 3 cannot be executed", "Name the button")


# --- Display and form helpers used by the page -----------------------------------------

def test_form_text_becomes_a_draft_without_touching_provenance():
    from spec_to_test.grill.drafts import draft_from_text

    draft = complete_test_case(provenance={"title": Provenance.SOURCE})
    edited = draft_from_text(draft, {"steps": "Open\n\n Submit ", "test_type": "", "title": " New "})
    assert edited.steps == ["Open", "Submit"] and edited.test_type is None and edited.title == "New"
    assert edited.provenance == {"title": Provenance.SOURCE}  # recorded later by update_draft
    with pytest.raises(DraftError, match="invalid_answer"):
        draft_from_text(draft, {"test_type": "sideways"})
    with pytest.raises(DraftError, match="invalid_field"):
        draft_from_text(draft, {"provenance": "x"})


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_draft_rows_show_every_field_with_its_origin(lang):
    from spec_to_test.grill.text import draft_rows
    from spec_to_test.i18n import t

    draft = complete_bug(environment="", provenance={"environment": Provenance.UNKNOWN, "summary": Provenance.SOURCE})
    rows = {label: (value, origin) for label, value, origin in draft_rows(draft, lang)}
    assert rows[t("grill.field.summary", lang)] == ("Save button crashes the editor", t("grill.provenance.source", lang))
    assert rows[t("grill.field.environment", lang)] == ("", t("grill.provenance.unknown", lang))
    assert rows[t("grill.field.severity", lang)][0] == t("severity.high", lang)
    assert rows[t("grill.field.steps", lang)][0] == "Open a document\nClick Save"
    assert len(rows) == len(editable_fields(draft))


def test_every_workflow_label_is_translated():
    from spec_to_test.grill.models import AnswerStatus, ArtifactType, GrillKind, GrillMode, GrillStep

    for prefix, enum in [("kind", GrillKind), ("mode", GrillMode), ("step", GrillStep),
                         ("artifact", ArtifactType), ("answer_status", AnswerStatus)]:
        for member in enum:
            assert f"grill.{prefix}.{member.value}" in TRANSLATIONS, (prefix, member)
