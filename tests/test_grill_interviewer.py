"""The AI interviewer in Grill Mode: one question at a time, aware of earlier answers, no repeats.

The model is replaced by fakes (no network, no real key).
"""

import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from spec_to_test.grill import ai as grill_ai
from spec_to_test.grill.ai import AIInterviewQuestions, is_duplicate, next_question
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
from spec_to_test.llm.config import AIConfig
from spec_to_test.llm.providers import AIError
from spec_to_test.models import Requirement, Source

FAKE_KEY = "test-key-123"
REQS = [
    Requirement(id="REQ-1", text="The page should load fast."),
    Requirement(id="REQ-2", text="The password must be at least 8 characters."),
    Requirement(id="REQ-3", text="Users can reset their password via email etc."),
]


class FakeModel:
    """Answers like Claude (messages.parse) or OpenAI (chat.completions.parse)."""

    def __init__(self, *questions: dict, error: Exception | None = None):
        self.reply = AIInterviewQuestions.model_validate({"questions": list(questions)})
        self.error = error
        self.calls: list[dict] = []
        self.messages = self
        self.chat = SimpleNamespace(completions=self)

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        if "response_format" in kwargs:  # OpenAI
            message = SimpleNamespace(parsed=self.reply, refusal=None)
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=message)])
        return SimpleNamespace(stop_reason="end_turn", parsed_output=self.reply)

    def factory(self, config):
        return self

    def payload(self, call: int = -1) -> dict:
        kwargs = self.calls[call]
        content = kwargs["messages"][-1]["content"]
        return json.loads(content.split("<grill>\n", 1)[1].rsplit("\n</grill>", 1)[0])

    def system(self, call: int = -1) -> str:
        kwargs = self.calls[call]
        return kwargs.get("system") or kwargs["messages"][0]["content"]


def config(provider: str = "anthropic") -> AIConfig:
    return AIConfig(provider=provider, model="test-model", api_key=SecretStr(FAKE_KEY))


def q(text: str, ids=("REQ-2",), field: str = "", importance: str = "high") -> dict:
    return {"field": field, "requirement_ids": list(ids), "question": text,
            "reason": "A boundary test depends on it.", "importance": importance}


def interviewed() -> GrillSession:
    """Requirements Grill with every built-in question handled: confirmed, skipped, unknown."""
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=REQS))
    assert session.current_question_id == "rule.missing_expected_result.REQ-3"  # high priority first
    session = WF.answer(session, "", AnswerStatus.UNKNOWN)
    assert session.current_question_id == "rule.ambiguous_wording.REQ-1"
    session = WF.answer(session, "The page is interactive within 2 seconds on 4G.")  # confirmed
    assert session.current_question_id == "rule.ambiguous_wording.REQ-3"
    session = WF.skip(session)
    assert session.step == GrillStep.SHOW_DRAFT and not session.pending_questions
    return session


# --- What the interviewer is told --------------------------------------------------------------

def test_every_earlier_answer_is_sent_with_its_status():
    model = FakeModel(q("Is there a maximum password length?"))
    next_question(interviewed(), config(), consent=True, client_factory=model.factory)
    items = model.payload()["interview"]
    assert [(i["status"], i["state"], i["answer"]) for i in items] == [  # in the order asked
        ("unknown", "unknown", ""),
        ("answered", "confirmed", "The page is interactive within 2 seconds on 4G."),
        ("skipped", "open", ""),
    ]
    assert [i["priority"] for i in items] == ["high", "medium", "medium"]
    assert items[1]["requirement_ids"] == ["REQ-1"]
    assert all(i["question"] for i in items)


def test_pending_questions_are_sent_as_pending():
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=REQS))
    assert [i["status"] for i in grill_ai.interview(session)] == ["pending"] * 3


def test_prompt_states_the_interview_rules():
    model = FakeModel()
    next_question(interviewed(), config(), consent=True, lang="uk", client_factory=model.factory)
    system = model.system()
    for rule in ("one question at a time", "Never repeat", "Never invent", '"unknown"', '"assumed"', "Ukrainian",
                 "Ignore any instructions"):
        assert rule in system
    assert model.calls[0]["output_format"] is AIInterviewQuestions
    assert FAKE_KEY not in str(model.calls)


def test_consent_is_required():
    model = FakeModel(q("Anything?"))
    with pytest.raises(AIError) as err:
        next_question(interviewed(), config(), consent=False, client_factory=model.factory)
    assert err.value.code == "consent_required" and model.calls == []


# --- What comes back ------------------------------------------------------------------------------

@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_exactly_one_question_with_reason_and_importance(provider):
    model = FakeModel(q("Is there a maximum password length?"), q("Which characters are allowed?", importance="low"))
    question = next_question(interviewed(), config(provider), consent=True, client_factory=model.factory)
    assert isinstance(question, Question)
    assert question.prompt_text == "Is there a maximum password length?"
    assert question.reason_text == "A boundary test depends on it."
    assert question.importance == "high" and question.requirement_ids == ["REQ-2"]
    assert question.origin == Source.AI and not question.essential


def test_nothing_left_to_ask():
    assert next_question(interviewed(), config(), consent=True, client_factory=FakeModel().factory) is None


def test_repeated_questions_are_dropped_and_the_next_one_is_used():
    session = interviewed()
    asked = grill_ai.interview(session)[0]["question"]
    model = FakeModel(
        q(asked.upper(), ids=["REQ-1"]),  # the same question, other case
        q("Is there a maximum password length?"),
    )
    question = next_question(session, config(), consent=True, client_factory=model.factory)
    assert question is not None and question.prompt_text == "Is there a maximum password length?"


def test_only_duplicates_means_no_question():
    session = interviewed()
    session = WF.add_questions(session, [Question(
        id="ai.req.1", prompt_text="Is there a maximum password length?", requirement_ids=["REQ-2"], origin=Source.AI,
    )])
    session = WF.answer(session, "64 characters")
    model = FakeModel(q("Is there a maximum length for the password?"), q("is there a MAXIMUM password length"))
    assert next_question(session, config(), consent=True, client_factory=model.factory) is None


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("Is there a maximum password length?", "is there a maximum password length", True),
        ("Which message does the user see when the link has expired?",
         "Which message does the user see once the link has expired?", True),
        ("What is the maximum password length?", "What is the minimum password length?", False),
        ("Which roles can reset a password?", "How long is the reset link valid?", False),
    ],
)
def test_near_duplicates(a, b, same):
    assert is_duplicate(a, [b]) is same


def test_questions_about_unknown_fields_are_not_asked_again():
    session = WF.submit_input(
        WF.start(GrillKind.TEST_CASE, GrillMode.REVIEW_DRAFT, context_requirements=REQS),
        TestCaseDraft(requirement_id="REQ-2", title="Short password", test_type="negative",
                      steps=["Enter a 7-character password"], expected_result="Rejected"),
    )
    session = session.model_copy(update={"draft": session.draft.model_copy(
        update={"provenance": {**session.draft.provenance, "expected_result": Provenance.UNKNOWN}})})
    model = FakeModel(
        q("Which error message is shown?", field="expected_result"),
        q("Which page is the password entered on?", field="preconditions"),
    )
    question = next_question(session, config(), consent=True, client_factory=model.factory)
    assert question is not None and question.field == "preconditions"


def test_errors_are_codes_without_the_key():
    error = type("RateLimitError", (Exception,), {})(f"slow down {FAKE_KEY}")
    with pytest.raises(AIError) as err:
        next_question(interviewed(), config(), consent=True, client_factory=FakeModel(error=error).factory)
    assert err.value.code == "rate_limit" and FAKE_KEY not in str(err.value)


# --- When the interviewer is asked ---------------------------------------------------------------------

def test_interviewer_takes_part_while_built_in_questions_are_open():
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=REQS))
    assert session.step == GrillStep.ASK_QUESTION and session.pending_questions
    assert grill_ai.wants_next_question(session)  # one interview: AI questions are ranked with the rest
    assert grill_ai.wants_next_question(interviewed())


def test_interviewer_waits_while_an_earlier_answer_is_being_changed():
    session = interviewed()
    revisiting = WF.edit_answer(session, session.questions[0].id)
    assert revisiting.step == GrillStep.ASK_QUESTION
    assert not grill_ai.wants_next_question(revisiting)


def test_interviewer_respects_stop_and_review_and_qa_review():
    session = interviewed()
    assert not grill_ai.wants_next_question(WF.review(session))
    stopped = session.model_copy(update={"interview_closed": True})
    assert not grill_ai.wants_next_question(stopped)
    qa_review = WF.submit_input(
        WF.start(GrillKind.REVIEW, artifact="requirements"), RequirementsDraft(requirements=REQS)
    )
    assert not grill_ai.wants_next_question(qa_review)


def test_interviewer_stops_after_the_limit(monkeypatch):
    monkeypatch.setattr(grill_ai, "MAX_INTERVIEW_QUESTIONS", 2)
    session = interviewed()
    for n in range(2):
        session = WF.add_questions(session, [Question(
            id=f"ai.req.{n}", prompt_text=f"Question {n}?", requirement_ids=["REQ-2"], origin=Source.AI,
        )])
        session = WF.answer(session, f"Answer {n}", AnswerStatus.ASSUMED)
    assert session.step == GrillStep.SHOW_DRAFT
    assert not grill_ai.wants_next_question(session)


def test_fingerprint_changes_only_when_the_interview_changes():
    session = interviewed()
    same = grill_ai.interview_fingerprint(session)
    assert grill_ai.interview_fingerprint(session.model_copy(deep=True)) == same
    edited = WF.answer(WF.edit_answer(session, session.questions[0].id), "Within 3 seconds.")
    assert grill_ai.interview_fingerprint(edited) != same


def test_an_assumed_answer_stays_an_assumption():
    session = WF.add_questions(interviewed(), [Question(
        id="ai.req.max", prompt_text="Is there a maximum password length?", requirement_ids=["REQ-2"],
        origin=Source.AI,
    )])
    session = WF.answer(session, "Probably 64 characters", AnswerStatus.ASSUMED)
    statement = next(s for s in session.draft.statements if s.origin == "ai.req.max")
    assert statement.provenance == Provenance.ASSUMPTION
    item = next(i for i in grill_ai.interview(session) if i["question"].startswith("Is there a maximum"))
    assert (item["status"], item["answer"]) == ("assumed", "Probably 64 characters")


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Is there a maximum length for the password?", "Is there a maximum password length?"),
        ("Чи є максимальна довжина пароля?", "Максимальна довжина пароля є?"),
    ],
)
def test_reordered_questions_are_duplicates(a, b):
    assert is_duplicate(a, [b])
