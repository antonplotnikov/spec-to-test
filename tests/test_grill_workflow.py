"""Grill workflow: transitions, answers, navigation, review and confirmation."""

import pytest

from spec_to_test.grill.drafts import field_is_empty
from spec_to_test.grill.models import (
    AnswerStatus,
    ArtifactType,
    BugReportDraft,
    Choice,
    FindingLevel,
    GrillKind,
    GrillMode,
    GrillSession,
    GrillStep,
    Provenance,
    Question,
    RequirementsDraft,
    TestCaseDraft,
)
from spec_to_test.grill.workflow import ALLOWED, Action, GrillError, GrillWorkflow, allowed_actions
from spec_to_test.models import Requirement, TestType

REQS = [Requirement(id="REQ-1", text="The user must be able to reset the password via email.")]
CORE_FIELDS = [("title", True), ("test_type", True), ("steps", True), ("expected_result", True), ("objective", False)]


def tc_planner(session: GrillSession) -> list[Question]:
    """Ask for every empty core field; ask for test data only for boundary tests."""
    draft = session.draft
    assert isinstance(draft, TestCaseDraft)
    questions = []
    for field, essential in CORE_FIELDS:
        if not field_is_empty(draft, field):
            continue
        if field == "test_type":
            choices = [Choice(value=v.value, label_key=f"test_type.{v.value}") for v in TestType]
            questions.append(
                Question(id="tc.test_type", field=field, prompt_key="grill.field.test_type",
                         choices=choices, allow_free_text=False)
            )
        else:
            questions.append(
                Question(id=f"tc.{field}", field=field, prompt_key=f"grill.field.{field}", essential=essential)
            )
    if draft.test_type == TestType.BOUNDARY and field_is_empty(draft, "test_data"):
        questions.append(Question(id="tc.test_data", field="test_data", prompt_key="grill.field.test_data"))
    return questions


WF = GrillWorkflow(planner=tc_planner)


def started(draft: TestCaseDraft | None = None) -> GrillSession:
    session = WF.start(GrillKind.TEST_CASE, context_requirements=REQS)
    return WF.submit_input(session, draft or TestCaseDraft(requirement_id="REQ-1"))


def answer_all(session: GrillSession) -> GrillSession:
    values = {"title": "Reset link is sent", "test_type": "positive", "steps": "Open reset page\nSubmit email",
              "expected_result": "A reset email is sent"}
    while session.step == GrillStep.ASK_QUESTION:
        question = session.current_question
        assert question is not None
        if question.essential:
            session = WF.answer(session, values[question.field])
        else:
            session = WF.skip(session)
    return session


# --- Happy path and confirmation ------------------------------------------------

def test_interview_happy_path_requires_explicit_confirmation():
    session = started()
    assert session.step == GrillStep.ASK_QUESTION
    assert session.current_question_id == "tc.title"
    session = answer_all(session)
    assert session.step == GrillStep.SHOW_DRAFT
    draft = session.draft
    assert isinstance(draft, TestCaseDraft)
    assert draft.steps == ["Open reset page", "Submit email"]
    assert draft.test_type == TestType.POSITIVE
    assert draft.provenance["title"] == Provenance.USER_CONFIRMED

    session = WF.review(session)
    assert session.step == GrillStep.REVIEW
    assert not session.blocking_findings and not session.warning_findings
    session = WF.request_confirmation(session)
    assert session.step == GrillStep.AWAITING_CONFIRMATION  # not finalized yet
    session = WF.confirm(session)
    assert session.step == GrillStep.FINALIZED


@pytest.mark.parametrize("step_to", ["ask", "draft", "review"])
def test_confirm_is_rejected_before_confirmation_step(step_to):
    session = started()
    if step_to != "ask":
        session = answer_all(session)
    if step_to == "review":
        session = WF.review(session)
    with pytest.raises(GrillError) as error:
        WF.confirm(session)
    assert error.value.code == "invalid_transition"


def test_finalized_session_without_current_review_is_invalid():
    session = WF.review(answer_all(started()))
    data = session.model_dump() | {"step": "finalized", "reviewed_revision": None}
    with pytest.raises(ValueError):
        GrillSession.model_validate(data)


def test_terminal_sessions_accept_no_actions():
    finalized = WF.confirm(WF.request_confirmation(WF.review(answer_all(started()))))
    cancelled = WF.cancel(started())
    for session in (finalized, cancelled):
        assert allowed_actions(session) == set()
        with pytest.raises(GrillError):
            WF.cancel(session)
        with pytest.raises(GrillError):
            WF.review(session)


@pytest.mark.parametrize(
    "action",
    [
        lambda s: WF.answer(s, "x"),
        lambda s: WF.skip(s),
        lambda s: WF.back(s),
        lambda s: WF.review(s),
        lambda s: WF.request_confirmation(s),
        lambda s: WF.proceed_to_draft(s),
    ],
)
def test_actions_before_input_are_rejected(action):
    session = WF.start(GrillKind.TEST_CASE)
    with pytest.raises(GrillError) as error:
        action(session)
    assert error.value.code == "invalid_transition"


def test_input_cannot_be_submitted_twice():
    with pytest.raises(GrillError):
        WF.submit_input(started(), TestCaseDraft())


def test_cancel_works_from_every_active_step():
    session = started()
    steps = [session]
    session = answer_all(session)
    steps.append(session)
    session = WF.review(session)
    steps.append(session)
    steps.append(WF.request_confirmation(session))
    steps.append(WF.start(GrillKind.TEST_CASE))
    assert {s.step for s in steps} == ALLOWED[Action.CANCEL]
    for s in steps:
        assert WF.cancel(s).step == GrillStep.CANCELLED


def test_stale_revision_is_rejected():
    session = started()
    newer = WF.answer(session, "Title", expected_revision=session.revision)
    with pytest.raises(GrillError) as error:
        WF.answer(newer, "Other", expected_revision=session.revision)
    assert error.value.code == "stale_session"


# --- Answers, navigation and relevance -------------------------------------------

def test_back_and_change_answer_without_repeating_questions():
    session = WF.answer(started(), "First title")
    assert session.current_question_id == "tc.test_type"
    session = WF.back(session)
    assert session.current_question_id == "tc.title"
    session = WF.answer(session, "Second title")
    assert session.draft.title == "Second title"
    assert session.answers["tc.title"].revision == 2
    assert session.current_question_id == "tc.test_type"  # next open question, not title again
    assert session.history.count("tc.title") == 1


def test_unchanged_answer_moves_on_without_changing_the_draft():
    session = WF.answer(started(), "Title")
    revision = session.draft_revision
    session = WF.answer(WF.back(session), "Title")
    assert session.draft_revision == revision
    assert session.answers["tc.title"].revision == 1


def test_back_on_first_question_is_rejected():
    with pytest.raises(GrillError) as error:
        WF.back(started())
    assert error.value.code == "no_previous_question"


def test_back_from_draft_returns_to_last_question():
    session = answer_all(started())
    session = WF.back(session)
    assert session.step == GrillStep.ASK_QUESTION
    assert session.current_question_id == session.history[-1]


def test_edit_answer_from_draft_and_review():
    session = WF.review(answer_all(started()))
    session = WF.edit_answer(session, "tc.steps")
    assert session.step == GrillStep.ASK_QUESTION and session.current_question_id == "tc.steps"
    session = WF.answer(session, "Open reset page\nSubmit email\nOpen inbox")
    assert session.step == GrillStep.SHOW_DRAFT
    assert len(session.draft.steps) == 3
    with pytest.raises(GrillError):
        WF.edit_answer(session, "does-not-exist")


def test_essential_questions_cannot_be_skipped_but_optional_ones_can():
    session = started()
    with pytest.raises(GrillError) as error:
        WF.skip(session)
    assert error.value.code == "essential_question"
    session = answer_all(session)
    assert session.answers["tc.objective"].status == AnswerStatus.SKIPPED
    assert session.draft.objective == ""


def test_empty_and_invalid_choice_answers_are_rejected():
    session = started()
    with pytest.raises(GrillError) as error:
        WF.answer(session, "   ")
    assert error.value.code == "empty_answer"
    session = WF.answer(session, "Title")
    with pytest.raises(GrillError) as error:
        WF.answer(session, "very important")
    assert error.value.code == "invalid_choice"


def test_unknown_answer_is_recorded_not_guessed():
    session = WF.answer(started(), "Title")
    session = WF.answer(session, "positive")
    session = WF.answer(session, "", AnswerStatus.UNKNOWN)
    assert session.draft.steps == []
    assert session.draft.provenance["steps"] == Provenance.UNKNOWN
    session = WF.review(WF.proceed_to_draft(session))
    blocking = [(f.field, f.category.value) for f in session.blocking_findings]
    assert ("steps", "unknown_value") in blocking


def test_irrelevant_open_questions_are_dropped_after_reanalysis():
    session = WF.answer(started(), "Title")
    session = WF.answer(session, "boundary")
    assert "tc.test_data" in {q.id for q in session.questions}
    session = WF.edit_answer(session, "tc.test_type")
    session = WF.answer(session, "positive")
    assert "tc.test_data" not in {q.id for q in session.questions}
    assert "tc.title" in {q.id for q in session.questions}  # answered questions are kept


def test_complete_draft_needs_no_questions():
    draft = TestCaseDraft(
        requirement_id="REQ-1", title="T", objective="O", test_type=TestType.NEGATIVE,
        steps=["Do it"], expected_result="It works",
    )
    session = WF.submit_input(WF.start(GrillKind.TEST_CASE, GrillMode.REVIEW_DRAFT, context_requirements=REQS), draft)
    assert session.step == GrillStep.SHOW_DRAFT
    assert session.questions == []


def test_review_draft_mode_asks_only_about_gaps():
    draft = TestCaseDraft(requirement_id="REQ-1", title="T", test_type=TestType.POSITIVE, steps=["Do it"])
    session = WF.submit_input(WF.start(GrillKind.TEST_CASE, GrillMode.REVIEW_DRAFT, context_requirements=REQS), draft)
    assert [q.id for q in session.questions] == ["tc.expected_result", "tc.objective"]


# --- Incomplete drafts, review and acceptance ---------------------------------------

def test_incomplete_draft_cannot_be_confirmed():
    session = WF.review(WF.proceed_to_draft(WF.answer(started(), "Title")))
    assert session.blocking_findings
    with pytest.raises(GrillError) as error:
        WF.request_confirmation(session, accept_unresolved=True)
    assert error.value.code == "blocking_findings"
    session = WF.continue_interview(WF.resume(session))
    assert session.step == GrillStep.ASK_QUESTION


def test_assumptions_must_be_accepted_explicitly():
    session = started()
    session = WF.answer(session, "Title")
    session = WF.answer(session, "positive")
    session = WF.answer(session, "Log in as admin", AnswerStatus.ASSUMED)
    session = WF.answer(session, "Dashboard opens")
    session = WF.review(WF.skip(session))
    assert session.draft.provenance["steps"] == Provenance.ASSUMPTION
    assert any(f.category.value == "assumption" for f in session.warning_findings)
    with pytest.raises(GrillError) as error:
        WF.request_confirmation(session)
    assert error.value.code == "unresolved_not_accepted"
    session = WF.request_confirmation(session, accept_unresolved=True)
    assert session.accepted_unresolved


def test_edit_after_review_requires_a_new_review():
    session = WF.review(answer_all(started()))
    edited = session.draft.model_copy(update={"expected_result": "A reset email arrives within 1 minute"})
    session = WF.update_draft(session, edited)
    assert session.step == GrillStep.SHOW_DRAFT
    assert session.draft.provenance["expected_result"] == Provenance.USER_CONFIRMED
    assert not session.review_is_current
    with pytest.raises(GrillError):
        WF.request_confirmation(session)  # must review first (not allowed from SHOW_DRAFT)
    session = WF.request_confirmation(WF.review(session))
    assert session.step == GrillStep.AWAITING_CONFIRMATION


def test_unchanged_edit_keeps_the_review_current():
    session = WF.review(answer_all(started()))
    session = WF.update_draft(session, session.draft.model_copy(deep=True))
    assert session.review_is_current


def test_declining_confirmation_returns_to_the_draft():
    session = WF.request_confirmation(WF.review(answer_all(started())))
    session = WF.resume(session)
    assert session.step == GrillStep.SHOW_DRAFT
    assert not session.accepted_unresolved


def test_draft_type_must_match_the_workflow():
    with pytest.raises(GrillError) as error:
        WF.submit_input(WF.start(GrillKind.TEST_CASE), BugReportDraft())
    assert error.value.code == "draft_type_mismatch"
    session = answer_all(started())
    with pytest.raises(GrillError):
        WF.update_draft(session, BugReportDraft())


# --- QA Review and requirements -------------------------------------------------------

def test_qa_review_goes_straight_to_findings():
    with pytest.raises(GrillError) as error:
        GrillWorkflow.start(GrillKind.REVIEW)
    assert error.value.code == "missing_artifact"
    session = GrillWorkflow.start(GrillKind.REVIEW, GrillMode.INTERVIEW, ArtifactType.BUG_REPORT)
    assert session.mode == GrillMode.REVIEW_DRAFT
    session = WF.submit_input(session, BugReportDraft(summary="Crash on save"), "raw draft text")
    assert session.step == GrillStep.REVIEW
    assert session.input_text == "raw draft text"
    assert {f.field for f in session.blocking_findings} >= {"steps", "actual_result", "expected_result"}


def clarify_planner(session: GrillSession) -> list[Question]:
    return [
        Question(id="req.REQ-1.ambiguous", prompt_text="What does 'fast' mean?", requirement_ids=["REQ-1"]),
        Question(id="req.REQ-1.errors", prompt_text="What if the email is unknown?", requirement_ids=["REQ-1"],
                 essential=False),
    ]


def requirements_session() -> GrillSession:
    wf = GrillWorkflow(planner=clarify_planner)
    session = wf.start(GrillKind.REQUIREMENTS)
    return wf.submit_input(session, RequirementsDraft(requirements=REQS))


def test_requirement_answers_become_traceable_statements():
    wf = GrillWorkflow(planner=clarify_planner)
    session = wf.answer(requirements_session(), "Under 2 seconds")
    session = wf.answer(session, "Show the same message as for known emails", AnswerStatus.ASSUMED)
    statements = session.draft.statements
    assert [(s.provenance, s.requirement_ids, s.origin) for s in statements] == [
        (Provenance.USER_CONFIRMED, ["REQ-1"], "req.REQ-1.ambiguous"),
        (Provenance.ASSUMPTION, ["REQ-1"], "req.REQ-1.errors"),
    ]
    assert session.draft.requirements == REQS  # source kept verbatim

    session = wf.answer(wf.edit_answer(session, "req.REQ-1.ambiguous"), "Under 1 second")
    assert [s.text for s in session.draft.statements if s.origin == "req.REQ-1.ambiguous"] == ["Under 1 second"]


def test_unknown_requirement_answer_stays_an_open_question():
    wf = GrillWorkflow(planner=clarify_planner)
    session = wf.answer(requirements_session(), "", AnswerStatus.UNKNOWN)
    session = wf.review(wf.skip(session))
    assert session.draft.statements == []
    codes = {f.message_key for f in session.warning_findings}
    assert "grill.check.question_unknown" in codes


def test_source_requirements_cannot_be_rewritten():
    wf = GrillWorkflow(planner=clarify_planner)
    session = wf.proceed_to_draft(requirements_session())
    rewritten = session.draft.model_copy(
        update={"requirements": [Requirement(id="REQ-1", text="The password is reset within 1 minute.")]}
    )
    with pytest.raises(GrillError) as error:
        wf.update_draft(session, rewritten)
    assert error.value.code == "source_changed"


# --- Isolation ------------------------------------------------------------------------

def test_actions_never_modify_the_input_session():
    session = started()
    snapshot = session.model_dump()
    WF.answer(session, "Title")
    WF.cancel(session)
    assert session.model_dump() == snapshot


def test_sessions_are_independent():
    first, second = started(), started()
    assert first.id != second.id
    first = WF.answer(first, "Only in the first session")
    assert second.draft.title == ""
    assert "tc.title" not in second.answers


def test_findings_are_ordered_by_level():
    session = WF.review(WF.proceed_to_draft(started()))
    levels = [f.level for f in session.findings]
    order = [FindingLevel.BLOCKING, FindingLevel.WARNING, FindingLevel.SUGGESTION]
    assert levels == sorted(levels, key=order.index)
