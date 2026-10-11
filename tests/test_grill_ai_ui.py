"""Optional AI on the Grill page (AppTest; the model calls are replaced by fakes)."""

import pytest
from test_grill_ui import BUG_DRAFT, REQS, answer_text, click, grill, session_of, start

from spec_to_test.ai_analysis import AIError
from spec_to_test.grill import ai as grill_ai
from spec_to_test.grill.models import FindingLevel, GrillStep, Question, ReviewCategory, ReviewFinding
from spec_to_test.i18n import LANGUAGES, t
from spec_to_test.models import Source
from test_localization import raw_keys, visible_text

TC_DRAFT = """Title: Expired link
Feature: Password reset
Objective: Expired links cannot be used
Preconditions: A reset link was sent
Test type: negative
Steps:
1. Wait 16 minutes
2. Open the link
Expected result: The link is rejected"""


@pytest.fixture
def ai_on(monkeypatch):
    """AI configured; records the calls the page makes to the model layer."""
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    calls: list[tuple[str, bool]] = []
    result: dict = {"questions": [], "findings": [], "error": None}

    def fake_questions(session, config, consent, lang="en"):
        calls.append(("questions", consent))
        if result["error"]:
            raise AIError(result["error"])
        return result["questions"]

    def fake_review(session, config, consent, lang="en"):
        calls.append(("review", consent))
        return result["findings"]

    monkeypatch.setattr(grill_ai, "suggest_questions", fake_questions)
    monkeypatch.setattr(grill_ai, "review_draft", fake_review)
    return calls, result


def ai_question(field="expected_result") -> Question:
    return Question(
        id=f"ai.{field}.1", field=field, prompt_text="Which message is shown when the link has expired?",
        reason_text="Pass and fail must be visible.", origin=Source.AI, essential=False,
    )


def ai_finding() -> ReviewFinding:
    return ReviewFinding(
        level=FindingLevel.WARNING, category=ReviewCategory.CLARITY, field="expected_result",
        message_text="“Rejected” does not say what the user sees.", suggestion_text="Name the message.",
        params={"quote": "rejected"}, origin=Source.AI,
    )


def consent_box(at):
    return next(c for c in at.checkbox if c.key and "_ai_consent_" in c.key)


def give_consent(at):
    consent_box(at).check().run()
    assert not at.exception
    return at


def tc_review(at=None):
    at = start(at or grill(), "review", artifact="test_case", text_key="grill_draft_text", text=TC_DRAFT)
    assert session_of(at).step == GrillStep.REVIEW
    return at


# --- Without AI --------------------------------------------------------------------------------

def test_without_ai_configuration_nothing_ai_is_offered():
    at = start(grill(), "bug_report", mode="review_draft", text_key="grill_draft_text", text=BUG_DRAFT)
    assert any(t("grill.ui.mode_deterministic") in info.value for info in at.info)
    assert not any(b.key in ("grill_ai_questions", "grill_ai_review") for b in at.button)
    assert not any(c.key and "_ai_consent_" in c.key for c in at.checkbox)


# --- Questions -----------------------------------------------------------------------------------

def test_ai_buttons_need_consent_and_consent_resets_after_each_request(ai_on):
    calls, result = ai_on
    result["questions"] = [ai_question()]
    at = start(grill(), "test_case", mode="review_draft", text_key="grill_draft_text", text=TC_DRAFT)
    assert any("claude" in info.value for info in at.info)  # AI available, model named
    assert at.button(key="grill_ai_questions").disabled
    assert at.button(key="grill_ai_review").disabled

    give_consent(at)
    assert not at.button(key="grill_ai_questions").disabled
    assert at.button(key="grill_ai_review").disabled  # needs a review first
    click(at, "grill_ai_questions")
    assert calls == [("questions", True)]

    session = session_of(at)
    assert session.current_question_id == "ai.expected_result.1"
    assert any(t("grill.ui.ai_question") == c.value for c in at.caption)
    assert any(t("grill.ui.ai_questions_added", count=1) == i.value for i in at.info)
    assert not at.button(key="grill_skip").disabled  # AI questions are optional
    box = next(a for a in at.text_area if a.key and "_text_" in a.key)
    assert box.value == "The link is rejected"  # starts from the current value
    assert consent_box(at).value is False  # asked again before the next request


def test_answering_an_ai_question_updates_the_draft(ai_on):
    _, result = ai_on
    result["questions"] = [ai_question()]
    at = start(grill(), "test_case", mode="review_draft", text_key="grill_draft_text", text=TC_DRAFT)
    give_consent(at)
    click(at, "grill_ai_questions")
    answer_text(at, "The page says “This link has expired”")
    session = session_of(at)
    assert session.draft.expected_result == "The page says “This link has expired”"
    assert session.draft.provenance["expected_result"].value == "user_confirmed"


def test_no_new_questions_is_reported_without_changing_the_session(ai_on):
    at = start(grill(), "test_case", mode="review_draft", text_key="grill_draft_text", text=TC_DRAFT)
    before = session_of(at)
    give_consent(at)
    click(at, "grill_ai_questions")
    assert any(t("grill.ui.ai_no_questions") == i.value for i in at.info)
    assert session_of(at).revision == before.revision


def test_ai_errors_are_translated(ai_on):
    _, result = ai_on
    result["error"] = "rate_limit"
    at = start(grill(), "test_case", mode="review_draft", text_key="grill_draft_text", text=TC_DRAFT)
    give_consent(at)
    click(at, "grill_ai_questions")
    assert at.error[0].value == t("ai.error.rate_limit")


# --- Review --------------------------------------------------------------------------------------

def test_ai_review_is_labeled_and_needs_explicit_acceptance(ai_on):
    calls, result = ai_on
    result["findings"] = [ai_finding()]
    at = tc_review()
    rule_warnings = session_of(at).warning_findings  # e.g. no requirement link
    give_consent(at)
    click(at, "grill_ai_review")
    assert calls == [("review", True)]

    session = session_of(at)
    assert [f.origin for f in session.warning_findings] == [Source.RULE] * len(rule_warnings) + [Source.AI]
    assert any(t("grill.ui.ai_findings_added", count=1) == i.value for i in at.info)
    assert any("are not confirmed" in w.value for w in at.warning)
    findings_table = at.table[0].value
    assert t("column.source") in findings_table.columns
    assert t("source.ai") in findings_table[t("column.source")].tolist()
    assert any("“rejected” — " in v for v in findings_table[t("grill.ui.column_issue")].tolist())
    assert at.button(key="grill_request_confirmation").disabled  # AI warning not accepted yet

    next(c for c in at.checkbox if c.key and "_accept_" in c.key).check().run()
    click(at, "grill_request_confirmation")
    assert session_of(at).step == GrillStep.AWAITING_CONFIRMATION


def test_editing_the_draft_discards_the_ai_review(ai_on):
    _, result = ai_on
    result["findings"] = [ai_finding()]
    at = tc_review()
    give_consent(at)
    click(at, "grill_ai_review")
    click(at, "grill_review_button")
    assert not any(f.origin == Source.AI for f in session_of(at).findings)


# --- Localization ---------------------------------------------------------------------------------

@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_ai_screens_are_translated(ai_on, lang):
    _, result = ai_on
    result["questions"] = [ai_question()]
    result["findings"] = [ai_finding()]
    screens = []
    at = grill()
    at.sidebar.selectbox[0].select(lang).run()
    start(at, "requirements", text_key="grill_requirements_text", text=REQS)
    screens.append(at)
    other = grill()
    other.sidebar.selectbox[0].select(lang).run()
    tc_review(other)
    give_consent(other)
    screens.append(other)
    click(other, "grill_ai_review")
    screens.append(other)
    give_consent(other)
    click(other, "grill_ai_questions")
    screens.append(other)
    for screen in screens:
        texts = visible_text(screen) + [str(c.label) for c in screen.checkbox]
        assert not raw_keys(texts), raw_keys(texts)
        if lang != "en":
            joined = "\n".join(texts)
            for english in ("Suggest questions with AI", "Review with AI", "AI assistant", "not a fact"):
                assert english not in joined
