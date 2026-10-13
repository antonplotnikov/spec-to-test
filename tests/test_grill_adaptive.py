"""Unified, adaptive Grill interview: one priority-ranked queue for built-in and AI questions,
follow-ups raised by answers, and the checks that keep AI questions new and traceable."""

import pytest

from spec_to_test.grill import ai as grill_ai
from spec_to_test.grill.ai import AIInterviewQuestions, to_questions
from spec_to_test.grill.models import (
    AnswerStatus,
    GrillKind,
    GrillMode,
    GrillSession,
    GrillStep,
    Provenance,
    Question,
    RequirementsDraft,
    TestCaseDraft,
)
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.grill.validation import deterministic_review
from spec_to_test.grill.workflow import GrillError
from spec_to_test.models import Requirement, Source

REQS = [
    Requirement(id="REQ-1", text="The password must be at least 8 characters."),
    Requirement(id="REQ-2", text="Users can upload a profile photo."),
    Requirement(id="REQ-3", text="The page should load fast."),
]


def session() -> GrillSession:
    return WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=REQS))


def ai(qid: str, text: str, ids=("REQ-2",), importance: str = "medium", field: str = "") -> Question:
    return Question(id=qid, field=field, prompt_text=text, requirement_ids=list(ids), origin=Source.AI,
                    importance=importance)


# --- One queue, highest priority first --------------------------------------------------------------

def test_every_built_in_question_has_a_priority():
    s = session()
    assert {q.id: q.priority for q in s.questions} == {
        "rule.missing_expected_result.REQ-2": "high",
        "rule.missing_error_handling.REQ-2": "medium",
        "rule.ambiguous_wording.REQ-3": "medium",
    }
    assert s.current_question_id == "rule.missing_expected_result.REQ-2"


def test_queue_is_re_ranked_after_each_answer():
    s = WF.answer(session(), "The photo appears on the profile page.")
    assert s.current_question_id == "rule.missing_error_handling.REQ-2"  # medium, in queue order
    # A high-priority AI question asked for in the meantime jumps ahead of the remaining medium ones.
    s = WF.merge_questions(s, [ai("ai.req.size", "Which file formats are accepted?", importance="high")])
    assert s.current_question_id == "ai.req.size"
    s = WF.answer(s, "JPEG and PNG")
    assert s.current_question_id == "rule.missing_error_handling.REQ-2"


def test_low_priority_ai_question_waits_for_the_built_in_ones():
    s = WF.merge_questions(session(), [ai("ai.req.alt", "Is alternative text required for the photo?", importance="low")])
    assert s.current_question_id == "rule.missing_expected_result.REQ-2"
    s = WF.answer(s, "The photo appears on the profile page.")
    s = WF.skip(s)
    s = WF.skip(s)
    assert s.current_question_id == "ai.req.alt"


def test_merge_does_not_move_a_question_being_revised():
    s = WF.answer(session(), "The photo appears on the profile page.")
    revising = WF.edit_answer(s, "rule.missing_expected_result.REQ-2")
    merged = WF.merge_questions(revising, [ai("ai.req.size", "Which file formats are accepted?", importance="high")])
    assert merged.current_question_id == "rule.missing_expected_result.REQ-2"
    assert "ai.req.size" in [q.id for q in merged.pending_questions]


def test_merge_rules():
    s = session()
    with pytest.raises(GrillError, match="no_new_questions"):
        WF.merge_questions(s, [])
    with pytest.raises(GrillError, match="invalid_question"):
        WF.merge_questions(s, [ai("x", "Rule?").model_copy(update={"origin": Source.RULE})])
    with pytest.raises(GrillError, match="interview_closed"):
        WF.merge_questions(WF.proceed_to_draft(s), [ai("ai.req.a", "Which formats?")])
    once = WF.merge_questions(s, [ai("ai.req.a", "Which formats?", importance="high")])
    assert not once.question("ai.req.a").essential  # AI questions can always be skipped
    with pytest.raises(GrillError, match="no_new_questions"):
        WF.merge_questions(once, [ai("ai.req.a", "Which formats?")])  # same ID: nothing new
    reviewed = WF.review(s)
    with pytest.raises(GrillError, match="invalid_transition"):
        WF.merge_questions(reviewed, [ai("ai.req.b", "Which sizes?")])


def test_merge_at_the_end_reopens_the_interview():
    s = session()
    s = WF.answer(s, "The photo appears on the profile page.")
    s = WF.skip(WF.skip(s))
    assert s.step == GrillStep.SHOW_DRAFT
    s = WF.merge_questions(s, [ai("ai.req.a", "Which formats are accepted?")])
    assert s.step == GrillStep.ASK_QUESTION and s.current_question_id == "ai.req.a"


def test_older_sessions_without_priorities_still_rank():
    legacy = Question(id="q", prompt_text="Old?", essential=True)
    optional = Question(id="o", prompt_text="Older?", essential=False)
    assert (legacy.priority, optional.priority) == ("high", "medium")


def test_test_case_interview_asks_required_fields_before_optional_ones():
    s = WF.submit_input(WF.start(GrillKind.TEST_CASE, context_requirements=REQS), TestCaseDraft())
    order = []
    while s.step == GrillStep.ASK_QUESTION and len(order) < 10:
        question = s.current_question
        order.append((question.id, question.priority))
        if question.id == "tc.requirement_id":
            s = WF.answer(s, "REQ-1")
        elif question.id == "tc.test_type":
            s = WF.answer(s, "positive")
        elif question.essential:
            s = WF.answer(s, "Some value")
        else:
            s = WF.skip(s)
    ranks = [{"high": 0, "medium": 1, "low": 2}[p] for _, p in order]
    assert ranks == sorted(ranks)  # never a lower priority before a higher one that was open
    assert order[0][0] == "tc.requirement_id"


# --- Adaptive follow-ups ---------------------------------------------------------------------------------------

def test_vague_answer_gets_a_follow_up_right_away():
    s = session()
    s = WF.answer(s, "The photo appears on the profile page.")
    s = WF.skip(s)  # error handling
    s = WF.answer(s, "It should be fast enough for users")  # REQ-3 clarification, still vague
    assert s.current_question_id == "followup.vague.rule.ambiguous_wording.REQ-3"
    assert s.current_question.requirement_ids == ["REQ-3"] and s.current_question.priority == "medium"
    assert s.current_question.params["answer"] == "It should be fast enough for users"


def test_new_input_limit_asks_what_happens_beyond_it():
    s = WF.answer(session(), "Photos up to 5 MB are shown on the profile page.")
    assert s.current_question_id == "followup.limit.rule.missing_expected_result.REQ-2"
    assert s.current_question.params["phrase"] == "up to 5 MB"


def test_no_limit_follow_up_when_the_behavior_is_known_or_the_limit_is_a_target():
    s = WF.answer(session(), "Photos up to 5 MB are accepted; larger files are rejected with an error.")
    assert not any(q.id.startswith("followup.limit") for q in s.questions)
    timing = WF.skip(WF.answer(session(), "The photo appears on the profile page."))
    timing = WF.answer(timing, "The page loads within 2 seconds.")
    assert not any(q.id.startswith("followup.limit") for q in timing.questions)


def test_follow_ups_disappear_when_the_answer_is_changed():
    s = WF.answer(session(), "Photos up to 5 MB are shown on the profile page.")
    assert "followup.limit.rule.missing_expected_result.REQ-2" in [q.id for q in s.pending_questions]
    s = WF.edit_answer(s, "rule.missing_expected_result.REQ-2")
    s = WF.answer(s, "The photo appears on the profile page.")
    assert not any(q.id.startswith("followup.") for q in s.questions)


def test_follow_ups_are_one_level_deep_and_skipping_dismisses_them():
    s = session()
    s = WF.answer(s, "The photo appears on the profile page.")
    s = WF.skip(s)
    s = WF.answer(s, "It should be fast enough")
    s = WF.answer(s, "Usually quick")  # the follow-up answer is vague too: no follow-up of a follow-up
    assert not any(q.id.startswith("followup.vague.followup") for q in s.questions)
    s = WF.edit_answer(s, "followup.vague.rule.ambiguous_wording.REQ-3")
    s = WF.skip(s)
    codes = {f.message_key for f in deterministic_review(s)}
    assert "grill.check.question_open" not in codes  # a skipped follow-up is dismissed


# --- AI questions: new, relevant and traceable ------------------------------------------------------------------

def reply(*items: dict) -> AIInterviewQuestions:
    return AIInterviewQuestions.model_validate({"questions": list(items)})


def q(text: str, field: str = "", ids=("REQ-2",)) -> dict:
    return {"field": field, "requirement_ids": list(ids), "question": text, "reason": "It matters.",
            "importance": "medium"}


def test_ai_question_repeating_a_planned_question_is_dropped():
    s = session()
    planned = "What should happen when the upload fails?"
    s = WF.merge_questions(s, [ai("ai.req.fail", planned)])
    assert to_questions(reply(q("what should happen when the upload FAILS")), s) == []


def test_ai_question_presuming_a_number_is_dropped():
    s = session()
    result = to_questions(reply(
        q("Should photos be limited to 10 MB?"),  # 10 appears nowhere: a presumed answer
        q("Does REQ-2 apply to both mobile and desktop uploads?"),  # a real ID is not a number
    ), s)
    assert [x.prompt_text for x in result] == ["Does REQ-2 apply to both mobile and desktop uploads?"]


def test_ai_question_may_use_numbers_the_author_gave():
    s = WF.answer(session(), "Photos up to 5 MB are shown on the profile page.")
    [question] = to_questions(reply(q("Is the 5 MB limit per photo or per upload?")), s)
    assert question.prompt_text.startswith("Is the 5 MB")


def test_ai_question_about_a_confirmed_field_is_dropped():
    draft = TestCaseDraft(requirement_id="REQ-1", title="Short password", test_type="negative",
                          steps=["Enter 7 characters", "Submit"], expected_result="The password is rejected")
    s = WF.submit_input(WF.start(GrillKind.TEST_CASE, GrillMode.REVIEW_DRAFT, context_requirements=REQS), draft)
    s = s.model_copy(update={"draft": s.draft.model_copy(
        update={"provenance": {**s.draft.provenance, "expected_result": Provenance.USER_CONFIRMED}})})
    result = to_questions(reply(
        q("Which message is shown?", field="expected_result", ids=[]),
        q("Which page is the password entered on?", field="preconditions", ids=[]),
        q("What happens in step 2 if the form is submitted twice?", field="steps", ids=[]),  # step numbers are fine
    ), s)
    assert [x.field for x in result] == ["preconditions", "steps"]


def test_overlong_ai_question_is_dropped():
    assert to_questions(reply(q("Which " + "very " * 100 + "long question?")), session()) == []


def test_answers_and_states_are_sent_to_the_interviewer():
    s = WF.answer(session(), "Photos up to 5 MB are shown on the profile page.")
    items = grill_ai.interview(s)
    first = next(i for i in items if i["status"] == "answered")
    assert first["state"] == "confirmed" and first["priority"] == "high"
    assert any(i["status"] == "pending" and i["question"] for i in items)  # the planned queue is visible


def test_assumed_answer_state():
    s = WF.answer(session(), "Probably shown on the profile", AnswerStatus.ASSUMED)
    assert grill_ai.interview(s)[0]["state"] == "assumption"


def test_a_new_contradiction_is_asked_before_other_questions_of_its_priority():
    photo = [Requirement(id="REQ-3", text="Users can upload a profile photo of at most 5 MB.")]
    s = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=photo))
    s = WF.merge_questions(s, [ai("ai.req.formats", "Which file formats are accepted?", ids=["REQ-3"], importance="high")])
    assert s.current_question_id == "rule.missing_expected_result.REQ-3"
    s = WF.answer(s, "Photos of at most 10 MB appear on the profile page.")
    assert s.current_question_id.startswith("conflict.")  # before the equally urgent AI question
    assert "ai.req.formats" in [q.id for q in s.pending_questions]


def photo_conflict() -> GrillSession:
    photo = [Requirement(id="REQ-3", text="Users can upload a profile photo of at most 5 MB.")]
    s = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=photo))
    return WF.answer(s, "Photos of at most 10 MB appear on the profile page.")


def test_no_follow_up_builds_on_an_overruled_answer():
    s = photo_conflict()
    assert not any(q.id.startswith("followup.limit") for q in s.questions)  # disputed: no follow-up yet
    overruled = WF.answer(s, "REQ-3: Users can upload a profile photo of at most 5 MB.")
    assert not any(q.id.startswith("followup.limit") for q in overruled.questions)
    kept = WF.answer(s, "Photos of at most 10 MB appear on the profile page.")  # the author keeps it
    assert any(q.id.startswith("followup.limit") for q in kept.questions)


def test_ai_question_may_not_build_on_a_disputed_value():
    s = photo_conflict()
    assert to_questions(reply(q("Should 10 MB apply to every photo?", ids=["REQ-3"])), s) == []
    kept = WF.answer(s, "Photos of at most 10 MB appear on the profile page.")
    assert len(to_questions(reply(q("Should 10 MB apply to every photo?", ids=["REQ-3"])), kept)) == 1
