"""AI interviewer and final report on the Grill page (AppTest; model calls are fakes)."""

import pytest
from test_grill_ui import REQS, answer_text, choose, click, grill, session_of, start

from spec_to_test.grill import ai as grill_ai
from spec_to_test.grill.models import GrillStep, Question
from spec_to_test.grill.report import Basis, SuggestedTestCase
from spec_to_test.i18n import LANGUAGES, t
from spec_to_test.llm.providers import AIError
from spec_to_test.models import Source, TestType
from test_localization import raw_keys, visible_text

INTERVIEWER = "_ai_interviewer"


@pytest.fixture
def model(monkeypatch):
    """AI configured; the interviewer's replies are queued in `replies` (a Question, None or an AIError)."""
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    state: dict = {"replies": [], "calls": [], "tests": [], "test_calls": 0}

    def fake_next(session, config, consent, lang="en"):
        state["calls"].append(session)
        assert consent
        reply = state["replies"].pop(0) if state["replies"] else None
        if isinstance(reply, AIError):
            raise reply
        return reply

    def fake_tests(session, config, consent, lang="en"):
        assert consent
        state["test_calls"] += 1
        return state["tests"]

    monkeypatch.setattr(grill_ai, "next_question", fake_next)
    monkeypatch.setattr(grill_ai, "suggest_test_cases", fake_tests)
    return state


def ai_question(n: int = 1, importance: str = "high") -> Question:
    return Question(
        id=f"ai.req.{n}", prompt_text=f"Is there a maximum password length? ({n})", requirement_ids=["REQ-1"],
        reason_text="A boundary test depends on it.", origin=Source.AI, essential=False, importance=importance,
    )


def interviewer(at):
    return next(c for c in at.checkbox if c.key and INTERVIEWER in c.key)


def started(lang: str = "en"):
    at = grill()
    if lang != "en":
        at.selectbox(key="language").select(lang).run()
    return start(at, "requirements", text_key="grill_requirements_text", text=REQS)


def built_in_questions_done(at):
    choose(at, "REQ-1: The password must be at least 8 characters.")
    return click(at, "grill_unknown")


# --- Interviewer ---------------------------------------------------------------------------------------

def test_no_interviewer_without_ai():
    at = started()
    assert not any(c.key and INTERVIEWER in c.key for c in at.checkbox)


def test_no_interviewer_in_qa_review(model):
    at = start(grill(), "review", artifact="requirements", text_key="grill_requirements_text", text=REQS)
    assert not any(c.key and INTERVIEWER in c.key for c in at.checkbox)


def test_one_interview_ranks_ai_and_built_in_questions_together(model):
    model["replies"] = [ai_question(1), ai_question(2, importance="low")]
    at = started()
    interviewer(at).check().run()
    assert len(model["calls"]) == 1  # consulted at once, also while built-in questions are open
    session = session_of(at)
    # Equal priority keeps queue order: the built-in contradiction (high) is still asked first.
    assert session.current_question_id.startswith("rule.contradiction.")
    assert "ai.req.1" in [q.id for q in session.pending_questions]

    choose(at, "REQ-1: The password must be at least 8 characters.")
    assert len(model["calls"]) == 2
    session = session_of(at)
    assert session.current_question_id == "ai.req.1"  # high outranks the medium ambiguity question
    assert any(t("grill.ui.importance", level=t("grill.importance.high")) in m.value for m in at.markdown)  # badge
    assert any("A boundary test depends on it." in c.value for c in at.caption)
    assert not at.button(key="grill_skip").disabled  # AI questions can always be skipped

    answer_text(at, "64 characters")
    assert len(model["calls"]) == 3
    assert model["calls"][2].answers["ai.req.1"].value == "64 characters"  # it sees the earlier answer
    assert session_of(at).current_question_id == "rule.ambiguous_wording.REQ-3"  # medium before low
    assert not any(t("grill.ui.ai_interview_done") == i.value for i in at.info)  # no noise mid-interview

    click(at, "grill_unknown")
    assert session_of(at).current_question_id == "ai.req.2"  # the low-priority AI question comes last
    next(a for a in at.text_area if a.key and "_text_" in a.key).input("Probably 128")
    click(at, "grill_assume")
    assert session_of(at).answers["ai.req.2"].status.value == "assumed"
    assert session_of(at).step == GrillStep.SHOW_DRAFT
    calls = len(model["calls"])
    assert any(t("grill.ui.ai_interview_done") == i.value for i in at.info)

    at.run()
    at.run()
    assert len(model["calls"]) == calls  # asked once per interview state, not on every rerun


def test_failure_falls_back_and_recovers_on_the_next_answer(model):
    model["replies"] = [AIError("connection"), ai_question(1)]
    at = started()
    interviewer(at).check().run()
    assert len(model["calls"]) == 1
    assert at.error[0].value == t("ai.error.connection")
    assert any(t("grill.ui.ai_fallback") == i.value for i in at.info)
    assert session_of(at).current_question_id.startswith("rule.contradiction.")  # built-in flow goes on

    at.run()
    assert len(model["calls"]) == 1  # a failure is not retried in a loop
    choose(at, "REQ-1: The password must be at least 8 characters.")
    assert len(model["calls"]) == 2 and session_of(at).current_question_id == "ai.req.1"


def test_explicit_retry_after_a_failure_at_the_end(model):
    model["replies"] = [None, None, AIError("rate_limit"), ai_question(1)]
    at = started()
    interviewer(at).check().run()
    built_in_questions_done(at)
    assert len(model["calls"]) == 3 and session_of(at).step == GrillStep.SHOW_DRAFT
    assert at.error[0].value == t("ai.error.rate_limit")
    at.run()
    assert len(model["calls"]) == 3
    click(at, "grill_ai_next")
    assert len(model["calls"]) == 4 and session_of(at).current_question_id == "ai.req.1"


def test_unticked_interviewer_never_calls_the_model(model):
    model["replies"] = [ai_question(1)]
    at = built_in_questions_done(started())
    assert session_of(at).step == GrillStep.SHOW_DRAFT
    assert model["calls"] == []


def test_interviewer_consent_is_per_grill_session(model):
    at = started()
    interviewer(at).check().run()
    built_in_questions_done(at)
    click(at, "grill_cancel")
    click(at, "grill_new")
    at = start(at, "requirements", text_key="grill_requirements_text", text=REQS)
    assert interviewer(at).value is False


# --- Final report -------------------------------------------------------------------------------------------

def finalized(at):
    click(at, "grill_review_button")
    if accept := [c for c in at.checkbox if c.key and "_accept_" in c.key]:
        accept[0].check().run()
    click(at, "grill_request_confirmation")
    click(at, "grill_confirm_button")
    assert session_of(at).step == GrillStep.FINALIZED
    return at


def test_final_report_without_ai():
    at = finalized(built_in_questions_done(started()))
    headings = [m.value for m in at.markdown]
    for key in ("grill.report.title", "grill.report.confirmed", "grill.report.assumptions",
                "grill.report.unknowns", "grill.report.tests"):
        assert any(t(key) in h for h in headings), key
    assert not any(b.key == "grill_ai_tests" for b in at.button)
    [download] = at.get("download_button")  # one download: result + final report
    assert download.key == "grill_download"


def ai_test_case() -> SuggestedTestCase:
    return SuggestedTestCase(
        title="Eight characters are accepted", requirement_ids=["REQ-1"], test_type=TestType.BOUNDARY,
        steps=["Enter 8 characters", "Submit"], expected_result="Accepted", basis=Basis.REQUIREMENT,
        basis_quote="at least 8 characters", origin=Source.AI,
    )


def test_ai_test_ideas_need_consent_and_are_labeled(model):
    model["tests"] = [ai_test_case()]
    at = finalized(built_in_questions_done(started()))
    assert at.button(key="grill_ai_tests").disabled
    next(c for c in at.checkbox if c.key and "_ai_tests_consent_" in c.key).check().run()
    click(at, "grill_ai_tests")
    assert model["test_calls"] == 1
    assert any(t("grill.report.ai_tests_added", count=1) == i.value for i in at.info)
    tables = [table.value for table in at.table]
    assert any("Eight characters are accepted" in frame.to_string() for frame in tables)
    assert any(t("source.ai") in frame.to_string() for frame in tables)
    consent = next(c for c in at.checkbox if c.key and "_ai_tests_consent_" in c.key)
    assert consent.value is False  # asked again before the next request


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_interviewer_and_report_are_translated(model, lang):
    model["replies"] = [ai_question(1), None]
    at = started(lang)
    interviewer(at).check().run()
    built_in_questions_done(at)
    screens = [visible_text(at)]
    answer_text(at, "64")
    screens.append(visible_text(at))
    finalized(at)
    screens.append(visible_text(at))
    for texts in screens:
        assert not raw_keys(texts), raw_keys(texts)


def test_interview_completes_and_finalizes_when_every_ai_call_fails(model):
    model["replies"] = [AIError("connection")] * 10
    at = started()
    interviewer(at).check().run()
    built_in_questions_done(at)
    assert session_of(at).step == GrillStep.SHOW_DRAFT
    assert len(model["calls"]) == 3  # once per answer state, never in a loop
    at = finalized(at)
    assert any(t("grill.report.title") in m.value for m in at.markdown)
