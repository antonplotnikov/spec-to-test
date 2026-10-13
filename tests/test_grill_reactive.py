"""Reactive Grill queue: finding status changes, answers that settle other questions,
retired questions with their history, and backward-compatible persistence."""

import dataclasses
import json

import pytest

from spec_to_test.grill import ai as grill_ai
from spec_to_test.grill.models import (
    AnswerStatus,
    AuditAction,
    GrillKind,
    GrillSession,
    GrillStep,
    Question,
    RequirementsDraft,
    RetireReason,
    TestCaseDraft,
    load_session,
)
from spec_to_test.grill.persistence import SavedInterview, export_json, from_data
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW, names_failure
from spec_to_test.grill.trace import audit_rows, event_text
from spec_to_test.grill.workflow import GrillError
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import Source

WF = dataclasses.replace(DETERMINISTIC_WORKFLOW, clock=lambda: "2026-10-13T10:00:00+00:00")
DOC = """REQ-1: After too many failed login attempts, the account is locked.
REQ-2: The page should load fast.
REQ-3: The password must be at least 8 characters.
REQ-4: The password must be at least 10 characters.
REQ-5: The user enters an email address."""
CONTRADICTION = "rule.contradiction.REQ-3+REQ-4"
VAGUE_1 = "rule.ambiguous_wording.REQ-1"
BOUNDARY_1 = "rule.missing_boundary.REQ-1"
VAGUE_2 = "rule.ambiguous_wording.REQ-2"
ERRORS_5 = "rule.missing_error_handling.REQ-5"
RESULT_5 = "rule.missing_expected_result.REQ-5"


def begin(settled: list[str] | None = None) -> GrillSession:
    session = WF.start(GrillKind.REQUIREMENTS, settled_question_ids=settled)
    return WF.submit_input(session, RequirementsDraft(requirements=extract_requirements(DOC)))


def answer_until(session: GrillSession, question_id: str, value: str = "", status=AnswerStatus.ANSWERED) -> GrillSession:
    """Answer everything as unknown until `question_id` is current, then answer it."""
    for _ in range(20):
        if session.current_question_id == question_id:
            return WF.answer(session, value, status)
        session = WF.answer(session, "", AnswerStatus.UNKNOWN)
    raise AssertionError(f"{question_id} was never asked")


def ids(questions: list[Question]) -> list[str]:
    return [q.id for q in questions]


def actions(session: GrillSession) -> list[AuditAction]:
    return [e.action for e in session.events]


# --- Finding status changes in the document -------------------------------------------

def test_a_finding_resolved_in_the_document_leaves_the_queue_with_its_history():
    session = begin()
    assert VAGUE_2 in ids(session.pending_questions)
    synced = WF.sync_settled(session, [VAGUE_2])
    assert VAGUE_2 not in ids(synced.questions)
    retired = synced.retired_question(VAGUE_2)
    assert retired is not None and retired.reason == RetireReason.SETTLED
    assert retired.question == session.question(VAGUE_2)  # same ID, text and links
    assert actions(synced)[-2:] == [AuditAction.FINDINGS_SYNCED, AuditAction.QUESTION_RETIRED]
    assert synced.events[-2].detail == f"resolved: {VAGUE_2}"
    assert synced.settled_question_ids == [VAGUE_2] and synced.revision == session.revision + 1


def test_a_reopened_finding_comes_back_under_the_same_id():
    session = begin(settled=[VAGUE_2])
    assert VAGUE_2 not in ids(session.questions)
    reopened = WF.sync_settled(session, [])
    assert VAGUE_2 in ids(reopened.pending_questions) and not reopened.retired
    assert actions(reopened)[-2:] == [AuditAction.FINDINGS_SYNCED, AuditAction.QUESTION_RESTORED]
    assert reopened.events[-2].detail == f"reopened: {VAGUE_2}"
    # Resolved again, then reopened again: one question, a full trail.
    again = WF.sync_settled(WF.sync_settled(reopened, [VAGUE_2]), [])
    assert ids(again.questions).count(VAGUE_2) == 1
    assert actions(again).count(AuditAction.QUESTION_RESTORED) == 2


def test_nothing_changed_means_no_new_revision():
    session = begin(settled=[VAGUE_2])
    assert WF.sync_settled(session, [VAGUE_2]) is session
    assert WF.sync_settled(session, [VAGUE_2, VAGUE_2]) is session


def test_the_question_on_screen_is_replaced_only_when_it_was_retired():
    session = begin()
    current = session.current_question_id
    assert current == CONTRADICTION  # decisions first
    unaffected = WF.sync_settled(session, [VAGUE_2])
    assert unaffected.current_question_id == current and unaffected.step == GrillStep.ASK_QUESTION
    replaced = WF.sync_settled(session, [CONTRADICTION])
    assert replaced.current_question_id != CONTRADICTION and replaced.step == GrillStep.ASK_QUESTION
    assert replaced.current_question_id in ids(replaced.pending_questions)


def test_answered_questions_stay_answered_when_their_finding_is_resolved_or_reopened():
    session = answer_until(begin(), CONTRADICTION, "REQ-4: The password must be at least 10 characters.")
    synced = WF.sync_settled(session, [CONTRADICTION])
    assert synced.answers[CONTRADICTION] == session.answers[CONTRADICTION]
    assert CONTRADICTION in ids(synced.questions) and synced.retired_question(CONTRADICTION) is None
    back = WF.sync_settled(synced, [])
    assert back.answers == session.answers and back.progress == session.progress


def test_a_finished_interview_asks_a_reopened_question_at_once():
    session = WF.proceed_to_draft(begin(settled=[VAGUE_2]))
    session = WF.continue_interview(session)
    while session.step == GrillStep.ASK_QUESTION:
        session = WF.answer(session, "", AnswerStatus.UNKNOWN)
    assert session.step == GrillStep.SHOW_DRAFT
    reopened = WF.sync_settled(session, [])
    assert reopened.step == GrillStep.ASK_QUESTION and reopened.current_question_id == VAGUE_2


def test_a_shown_review_is_redone_and_a_pending_confirmation_withdrawn():
    session = begin(settled=[VAGUE_2])
    while session.step == GrillStep.ASK_QUESTION:
        session = WF.answer(session, "", AnswerStatus.UNKNOWN)
    reviewed = WF.review(session)
    waiting = WF.request_confirmation(reviewed, accept_unresolved=True)
    for before in (reviewed, waiting):
        after = WF.sync_settled(before, [])
        assert after.step == GrillStep.REVIEW and after.review_is_current and not after.accepted_unresolved
        assert actions(after)[-1] == AuditAction.REVIEWED
        assert VAGUE_2 in ids(after.pending_questions)


def test_finished_and_non_requirement_sessions_are_left_alone():
    cancelled = WF.cancel(begin())
    assert WF.sync_settled(cancelled, [VAGUE_2]) is cancelled
    test_case = WF.submit_input(WF.start(GrillKind.TEST_CASE), TestCaseDraft())
    assert WF.sync_settled(test_case, [VAGUE_2]) is test_case


def test_stale_pages_cannot_sync():
    session = begin()
    with pytest.raises(GrillError, match="stale_session"):
        WF.sync_settled(session, [VAGUE_2], expected_revision=session.revision - 1)


def test_progress_never_goes_down_when_findings_change():
    session = answer_until(begin(), CONTRADICTION, "REQ-3: The password must be at least 8 characters.")
    handled = session.progress[0]
    for settled in ([VAGUE_2], [VAGUE_2, ERRORS_5], [], [ERRORS_5]):
        session = WF.sync_settled(session, settled)
        assert session.progress[0] == handled


# --- One answer settles another question ------------------------------------------------

def test_a_number_in_one_answer_settles_the_boundary_question():
    session = answer_until(begin(), VAGUE_1, "The account is locked after 5 failed attempts.")
    retired = session.retired_question(BOUNDARY_1)
    assert retired is not None and retired.reason == RetireReason.ANSWERED_ELSEWHERE
    assert retired.covered_by == VAGUE_1
    assert BOUNDARY_1 not in ids(session.questions)
    text = event_text(next(e for e in session.events if e.question_id == BOUNDARY_1), session)
    assert "already answered by" in text
    # The answer is changed to "unknown": the boundary question applies again.
    session = WF.edit_answer(session, VAGUE_1)
    session = WF.answer(session, "", AnswerStatus.UNKNOWN)
    assert BOUNDARY_1 in ids(session.pending_questions) and session.retired_question(BOUNDARY_1) is None


def test_a_named_failure_settles_the_error_handling_question():
    session = answer_until(begin(), RESULT_5, "Invalid addresses are rejected with an error under the field.")
    assert session.retired_question(ERRORS_5).covered_by == RESULT_5
    negated = answer_until(begin(), RESULT_5, "The address is saved; no error is shown.")
    assert ERRORS_5 in ids(negated.questions)


@pytest.mark.parametrize(("text", "expected"), [
    ("Не более 20 МБ; файл большего размера отклоняется с ошибкой.", True),
    ("Показується помилка.", True),
    ("Ошибка не показывается.", True),  # the negation follows; still names the failure path
    ("No error is shown.", False),
    ("Не показывается ошибка.", False),
])
def test_failure_detection_is_negation_aware(text, expected):
    assert names_failure(text) is expected


def test_assumptions_cover_but_unknowns_and_conflicts_do_not():
    assumed = answer_until(begin(), VAGUE_1, "Probably 5 failed attempts.", AnswerStatus.ASSUMED)
    assert assumed.retired_question(BOUNDARY_1) is not None
    unknown = answer_until(begin(), VAGUE_1, status=AnswerStatus.UNKNOWN)
    assert BOUNDARY_1 in ids(unknown.questions)


def test_a_filled_draft_field_retires_its_open_question():
    session = WF.submit_input(WF.start(GrillKind.TEST_CASE), TestCaseDraft())
    session = WF.proceed_to_draft(session)
    assert "tc.title" in ids(session.pending_questions)
    edited = WF.update_draft(session, session.draft.model_copy(update={"title": "Login with a locked account"}))
    assert "tc.title" not in ids(edited.questions)
    assert edited.retired_question("tc.title").reason == RetireReason.OBSOLETE


# --- AI questions -------------------------------------------------------------------------

def ai_reply(*questions: dict) -> grill_ai.AIInterviewQuestions:
    return grill_ai.AIInterviewQuestions.model_validate({"questions": [
        {"field": "", "reason": "r", "importance": "medium", **q} for q in questions
    ]})


def test_ai_questions_that_repeat_a_known_contradiction_or_a_false_dilemma_are_dropped():
    session = begin()
    reply = ai_reply(
        {"requirement_ids": ["REQ-3", "REQ-4"], "question": "Which minimum length is right: 8 or 10 characters?"},
        {"requirement_ids": ["REQ-1"], "question": "Is the lock 2 minutes or 120 seconds long?"},
        {"requirement_ids": ["REQ-1"], "question": "How is a locked account unlocked?"},
    )
    assert [q.prompt_text for q in grill_ai.to_questions(reply, session)] == ["How is a locked account unlocked?"]
    resolved = WF.sync_settled(session, [CONTRADICTION])
    assert grill_ai.to_questions(ai_reply(reply.questions[0].model_dump()), resolved) == []


def test_a_retired_question_is_not_asked_again_by_the_model():
    session = WF.sync_settled(begin(), [VAGUE_2])
    prompt = "What measurable criteria replace: \"fast\"?"
    assert grill_ai.to_questions(ai_reply({"requirement_ids": ["REQ-2"], "question": prompt}), session) == []
    message = grill_ai.build_message(session)
    assert "fast" in message.split('"already_asked"')[1].split('"interview"')[0]


def test_an_ai_question_id_that_was_retired_is_not_added_twice():
    session = begin()
    ai_question = Question(id="ai.req.abc", prompt_text="How is a locked account unlocked?",
                           requirement_ids=["REQ-1"], origin=Source.AI, essential=False)
    session = WF.merge_questions(session, [ai_question])
    session = answer_until(session, VAGUE_1, "Locked after 5 failed attempts.")
    # The model's question was taken out of the queue (as another answer would do).
    out_of_queue = session.retired[0].model_copy(update={"question": ai_question})
    retired = GrillSession.model_validate({
        **session.model_dump(),
        "questions": [q.model_dump() for q in session.questions if q.id != ai_question.id],
        "retired": [*(r.model_dump() for r in session.retired), out_of_queue.model_dump()],
    })
    with pytest.raises(GrillError, match="no_new_questions"):
        WF.merge_questions(retired, [ai_question])


# --- Persistence and audit ------------------------------------------------------------------

def test_version_2_sessions_load_and_keep_working():
    session = answer_until(begin(), VAGUE_1, "Locked after 5 failed attempts.")
    data = session.model_dump(mode="json")
    data.pop("retired")
    data["schema_version"] = 2
    loaded = load_session(data)
    assert loaded is not None and loaded.schema_version == 3 and loaded.retired == []
    assert loaded.answers == session.answers and loaded.history == session.history
    # The next change records retirements as usual.
    assert WF.sync_settled(loaded, [VAGUE_2]).retired_question(VAGUE_2) is not None


def test_retired_questions_survive_export_and_import():
    session = WF.sync_settled(answer_until(begin(), VAGUE_1, "Locked after 5 failed attempts."), [VAGUE_2])
    record = SavedInterview(project_id="p", document_hash="d", session=session)
    loaded = from_data(json.loads(export_json(record)))
    assert loaded.session.retired == session.retired and loaded.session.events == session.events


def test_inconsistent_retired_lists_are_refused():
    session = WF.sync_settled(begin(), [VAGUE_2])
    data = session.model_dump(mode="json")
    data["retired"].append(data["retired"][0])
    assert load_session(data) is None
    data = session.model_dump(mode="json")
    data["questions"].append(data["retired"][0]["question"])
    assert load_session(data) is None


@pytest.mark.parametrize("lang", ["en", "ru", "uk"])
def test_new_audit_events_are_readable_in_every_language(lang):
    session = WF.sync_settled(WF.sync_settled(begin(), [VAGUE_2]), [])
    session = answer_until(session, VAGUE_1, "Locked after 5 failed attempts.")
    rows = audit_rows(session, lang)
    texts = [str(value) for row in rows for value in row.values()]
    assert not any("grill.audit" in text or "grill.retire_reason" in text for text in texts)
    synced = [e for e in session.events if e.action == AuditAction.FINDINGS_SYNCED]
    assert len(synced) == 2 and all(VAGUE_2 in event_text(e, session, lang) for e in synced)
