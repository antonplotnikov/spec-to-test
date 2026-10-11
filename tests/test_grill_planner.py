"""Deterministic Grill MVP: question banks for every workflow, end to end without AI."""

import socket

import pytest

from spec_to_test.grill.models import (
    AnswerStatus,
    ArtifactType,
    BugReportDraft,
    GrillKind,
    GrillMode,
    GrillSession,
    GrillStep,
    Priority,
    Provenance,
    Question,
    Reproducibility,
    RequirementsDraft,
    TestCaseDraft,
)
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.grill.planner import plan_questions
from spec_to_test.grill.text import render_choice, render_question
from spec_to_test.grill.workflow import GrillError
from spec_to_test.i18n import LANGUAGES
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import Requirement, Severity, Source, TestType

DOC = """REQ-1: The password must be at least 8 characters.
REQ-2: The password must be at least 10 characters.
REQ-3: The page should load fast.
REQ-4: The user enters the email in the login form."""
REQS = extract_requirements(DOC)
CLEAR = [Requirement(id="REQ-9", text="The system must send a confirmation email after registration.")]


def ids(session: GrillSession) -> list[str]:
    return [q.id for q in session.questions]


def requirements_session(requirements: list[Requirement] = REQS) -> GrillSession:
    return WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=requirements))


def tc_session(draft: TestCaseDraft | None = None, context: list[Requirement] | None = REQS,
                      mode: GrillMode = GrillMode.INTERVIEW) -> GrillSession:
    session = WF.start(GrillKind.TEST_CASE, mode, context_requirements=context)
    return WF.submit_input(session, draft or TestCaseDraft())


def bug_session(draft: BugReportDraft | None = None, context: list[Requirement] | None = None) -> GrillSession:
    session = WF.start(GrillKind.BUG_REPORT, context_requirements=context)
    return WF.submit_input(session, draft or BugReportDraft())


def run(session: GrillSession, answers: dict[str, str]) -> GrillSession:
    """Answer known questions, skip optional ones, mark the rest unknown."""
    while session.step == GrillStep.ASK_QUESTION:
        question = session.current_question
        assert question is not None
        if question.id in answers:
            session = WF.answer(session, answers[question.id])
        elif not question.essential:
            session = WF.skip(session)
        else:
            session = WF.answer(session, "", AnswerStatus.UNKNOWN)
    return session


# --- Requirements Grill ----------------------------------------------------------------

def test_requirement_questions_come_from_rule_findings_with_real_ids():
    session = requirements_session()
    assert ids(session) == [
        "rule.contradiction.REQ-1+REQ-2",
        "rule.ambiguous_wording.REQ-3",
        "rule.missing_expected_result.REQ-4",
        "rule.missing_error_handling.REQ-4",
    ]
    known = {r.id for r in REQS}
    for question in session.questions:
        assert question.requirement_ids and set(question.requirement_ids) <= known
        assert question.origin == Source.RULE
        assert question.reason_key  # every question explains why it matters
    # The existing clarification questions are reused, not duplicated.
    assert session.questions[1].prompt_key == "question.ambiguous_wording"
    assert '"fast"' in render_question(session.questions[1])[0]


def test_contradiction_is_asked_once_with_both_rules_verbatim():
    session = requirements_session()
    question = session.current_question
    assert question is not None and question.id.startswith("rule.contradiction.")
    assert question.essential and question.allow_free_text
    assert [c.value for c in question.choices] == [
        "REQ-1: The password must be at least 8 characters.",
        "REQ-2: The password must be at least 10 characters.",
    ]


def test_essential_findings_cannot_be_skipped_but_others_can():
    session = requirements_session()
    with pytest.raises(GrillError, match="essential_question"):
        WF.skip(session)
    session = WF.answer(session, session.current_question.choices[0].value)
    assert session.current_question_id == "rule.ambiguous_wording.REQ-3"
    session = WF.skip(session)
    assert session.current_question_id == "rule.missing_expected_result.REQ-4"


def test_answers_become_traceable_statements_and_resolve_findings():
    session = requirements_session()
    session = run(session, {
        "rule.contradiction.REQ-1+REQ-2": "REQ-1: The password must be at least 8 characters.",
        "rule.ambiguous_wording.REQ-3": "The page loads within 2 seconds on desktop.",
    })
    assert session.step == GrillStep.SHOW_DRAFT
    statements = {s.origin: s for s in session.draft.statements}
    assert statements["rule.contradiction.REQ-1+REQ-2"].requirement_ids == ["REQ-1", "REQ-2"]
    assert statements["rule.ambiguous_wording.REQ-3"].provenance == Provenance.USER_CONFIRMED
    # The source text is untouched; clarifications sit next to it.
    assert session.draft.requirements == REQS
    session = WF.review(session)
    codes = {f.message_key.removeprefix("grill.check.") for f in session.findings}
    assert "req_contradiction" not in codes and "req_ambiguous_wording" not in codes
    # Unknown and skipped questions stay visible, each reported once.
    assert sorted(codes) == ["req_missing_error_handling", "req_missing_expected_result"]


def test_assumed_answer_is_kept_as_an_assumption_not_a_fact():
    session = requirements_session()
    session = WF.answer(session, "REQ-2: The password must be at least 10 characters.", AnswerStatus.ASSUMED)
    session = WF.review(WF.proceed_to_draft(session))
    statement = session.draft.statements[0]
    assert statement.provenance == Provenance.ASSUMPTION
    codes = {f.message_key.removeprefix("grill.check.") for f in session.warning_findings}
    assert "statement_assumption" in codes and "req_contradiction" not in codes


def test_answered_questions_are_never_asked_again():
    session = requirements_session()
    first = session.current_question_id
    value = "REQ-1: The password must be at least 8 characters."
    session = run(WF.answer(session, value), {})
    assert session.step == GrillStep.SHOW_DRAFT
    assert first not in [q.id for q in session.pending_questions]
    assert session.history.count(first) == 1
    # The user can still revisit it on purpose; re-planning does not ask anything else again.
    edited = WF.edit_answer(session, first)
    assert edited.current_question_id == first
    assert WF.answer(edited, value).step == GrillStep.SHOW_DRAFT


def test_clear_requirements_go_straight_to_the_draft():
    session = requirements_session(CLEAR)
    assert session.questions == [] and session.step == GrillStep.SHOW_DRAFT
    session = WF.review(session)
    assert session.findings == []


# --- Test Case Grill -----------------------------------------------------------------

def test_requirement_link_is_chosen_from_the_document_only():
    session = tc_session()
    question = session.current_question
    assert question.id == "tc.requirement_id"
    assert [c.value for c in question.choices] == [r.id for r in REQS]
    assert not question.allow_free_text and not question.essential
    with pytest.raises(GrillError, match="invalid_choice"):
        WF.answer(session, "REQ-404")


def test_feature_is_asked_only_when_there_is_no_requirement_to_link():
    linked = WF.answer(tc_session(), "REQ-1")
    assert "tc.feature" not in ids(linked)
    skipped = WF.skip(tc_session())
    assert skipped.current_question_id == "tc.feature"
    assert skipped.current_question.essential


def test_without_a_document_the_requirement_id_is_free_text_and_optional():
    session = tc_session(context=None)
    question = session.current_question
    assert question.prompt_key == "grill.q.tc.requirement_id_free"
    assert question.allow_free_text and not question.choices and not question.essential


def test_test_data_question_depends_on_the_test_type():
    session = WF.answer(WF.answer(tc_session(), "REQ-1"), "Short password is rejected")
    assert "tc.test_data" not in ids(session)  # the type is not known yet
    session = WF.skip(session)  # objective
    assert session.current_question_id == "tc.test_type"
    negative = WF.answer(session, TestType.NEGATIVE.value)
    by_id = {q.id: q for q in negative.questions}
    assert by_id["tc.test_data"].prompt_key == "grill.q.tc.test_data_negative"
    assert by_id["tc.expected_result"].prompt_key == "grill.q.tc.expected_result_negative"
    positive = WF.answer(session, TestType.POSITIVE.value)
    assert not {q.id: q for q in positive.questions}["tc.test_data"].essential


def test_boundary_test_data_hint_comes_from_the_linked_requirement():
    draft = TestCaseDraft(requirement_id="REQ-1", title="Password length", test_type=TestType.BOUNDARY)
    session = tc_session(draft, mode=GrillMode.REVIEW_DRAFT)
    question = session.question("tc.test_data")
    assert question.essential and question.requirement_ids == ["REQ-1"]
    _, reason = render_question(question)
    assert "at least 8 characters" in reason and "7, 8, 9" in reason
    # Without a linked requirement, no values are suggested.
    unlinked = tc_session(draft.model_copy(update={"requirement_id": ""}, deep=True), context=None)
    assert "params" not in unlinked.question("tc.test_data").model_dump(exclude_defaults=True)


def test_full_test_case_interview_reaches_a_reviewed_confirmable_draft():
    session = run(tc_session(), {
        "tc.requirement_id": "REQ-1",
        "tc.title": "Password shorter than 8 characters is rejected",
        "tc.objective": "Verify the minimum password length",
        "tc.test_type": "negative",
        "tc.preconditions": "The registration page is open",
        "tc.test_data": "Password: abc1234",
        "tc.steps": "Enter the password\nClick Register",
        "tc.expected_result": "An error message says the password is too short",
    })
    assert session.step == GrillStep.SHOW_DRAFT
    assert session.unresolved_questions == []
    draft = session.draft
    assert all(p == Provenance.USER_CONFIRMED for p in draft.provenance.values())
    session = WF.review(session)
    assert session.findings == []
    session = WF.confirm(WF.request_confirmation(session))
    assert session.step == GrillStep.FINALIZED


def test_draft_review_asks_only_for_missing_or_placeholder_fields():
    draft = TestCaseDraft(
        requirement_id="REQ-1", title="Minimum length", objective="Check the limit", test_type=TestType.POSITIVE,
        preconditions=["Registration page is open"], test_data=["Password: abcdefgh"],
        steps=["TBD"], expected_result="",
        provenance={f: Provenance.SOURCE for f in ("requirement_id", "title", "objective", "test_type",
                                                   "preconditions", "test_data", "steps")},
    )
    session = tc_session(draft, mode=GrillMode.REVIEW_DRAFT)
    assert ids(session) == ["tc.steps", "tc.expected_result"]
    # A complete draft needs no questions.
    complete = draft.model_copy(update={"steps": ["Enter the password"], "expected_result": "The account is created"})
    assert tc_session(complete, mode=GrillMode.REVIEW_DRAFT).step == GrillStep.SHOW_DRAFT


def test_fields_marked_unknown_are_not_asked_again():
    draft = TestCaseDraft(requirement_id="REQ-1", provenance={"preconditions": Provenance.UNKNOWN})
    assert "tc.preconditions" not in ids(tc_session(draft))


def test_vague_expected_result_gets_an_optional_follow_up():
    draft = TestCaseDraft(requirement_id="REQ-1", title="T", objective="O", test_type=TestType.POSITIVE,
                          preconditions=["P"], test_data=["D"], steps=["S"], expected_result="It works correctly")
    session = tc_session(draft, mode=GrillMode.REVIEW_DRAFT)
    question = session.current_question
    assert question.id == "tc.expected_result.vague" and not question.essential
    assert "“correctly”" in render_question(question)[0]
    session = WF.answer(session, "The account page shows the user name")
    assert session.draft.expected_result == "The account page shows the user name"
    assert session.step == GrillStep.SHOW_DRAFT


# --- Bug Report Grill -----------------------------------------------------------------

def test_bug_interview_asks_core_facts_first_and_offers_choices_for_ratings():
    session = bug_session()
    assert ids(session) == [
        "bug.summary", "bug.environment", "bug.app_version", "bug.preconditions", "bug.steps",
        "bug.actual_result", "bug.expected_result", "bug.reproducibility", "bug.evidence",
        "bug.severity", "bug.priority",
    ]
    by_id = {q.id: q for q in session.questions}
    assert [c.value for c in by_id["bug.severity"].choices] == [s.value for s in Severity]
    assert [c.value for c in by_id["bug.priority"].choices] == [p.value for p in Priority]
    assert [c.value for c in by_id["bug.reproducibility"].choices] == [r.value for r in Reproducibility]
    assert not any(by_id[f].allow_free_text for f in ("bug.severity", "bug.priority", "bug.reproducibility"))
    assert not by_id["bug.evidence"].essential and not by_id["bug.preconditions"].essential


def test_bug_requirement_link_is_offered_only_with_a_document():
    assert "bug.requirement_id" not in ids(bug_session())
    question = bug_session(context=REQS).question("bug.requirement_id")
    assert question is not None and not question.essential and not question.allow_free_text


def test_unknown_bug_facts_stay_unknown_and_nothing_is_invented():
    session = run(bug_session(), {
        "bug.summary": "Save button closes the editor",
        "bug.steps": "Open a document\nClick Save",
        "bug.actual_result": "The editor closes",
        "bug.expected_result": "The document is saved",
        "bug.reproducibility": "always",
    })
    draft = session.draft
    for field in ("environment", "app_version", "severity", "priority"):
        assert draft.provenance[field] == Provenance.UNKNOWN
        assert getattr(draft, field) in ("", None)
    assert draft.evidence == [] and "evidence" not in draft.provenance  # skipped, not made up
    session = WF.review(session)
    unknown = {f.field for f in session.warning_findings if f.message_key == "grill.check.unknown_value"}
    assert unknown == {"environment", "app_version", "severity", "priority"}
    assert not session.blocking_findings
    with pytest.raises(GrillError, match="unresolved_not_accepted"):
        WF.request_confirmation(session)
    assert WF.request_confirmation(session, accept_unresolved=True).step == GrillStep.AWAITING_CONFIRMATION


def test_incomplete_bug_draft_review_asks_only_for_gaps():
    draft = BugReportDraft(summary="Crash on save", steps=["Click Save"], actual_result="Crash",
                           expected_result="Saved", environment="Chrome 140", app_version="1.0.0",
                           reproducibility=Reproducibility.ALWAYS, severity=Severity.HIGH, priority=Priority.HIGH)
    session = WF.submit_input(WF.start(GrillKind.BUG_REPORT, GrillMode.REVIEW_DRAFT), draft)
    assert ids(session) == ["bug.preconditions", "bug.evidence"]


# --- QA Review and general behavior ----------------------------------------------------

def test_qa_review_asks_no_questions_and_reviews_immediately():
    session = WF.start(GrillKind.REVIEW, artifact=ArtifactType.BUG_REPORT)
    session = WF.submit_input(session, BugReportDraft(summary="Crash"))
    assert session.step == GrillStep.REVIEW and session.questions == []
    assert session.blocking_findings


def test_planner_returns_nothing_without_a_draft():
    assert plan_questions(WF.start(GrillKind.TEST_CASE)) == []


def test_deterministic_grill_needs_no_network(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    session = run(requirements_session(), {})
    session = WF.review(session)
    assert session.step == GrillStep.REVIEW


def all_questions() -> list[Question]:
    sessions = [
        requirements_session(),
        tc_session(), tc_session(context=None), WF.skip(tc_session()),
        tc_session(TestCaseDraft(requirement_id="REQ-1", test_type=TestType.BOUNDARY)),
        tc_session(TestCaseDraft(requirement_id="X", test_type=TestType.BOUNDARY), context=None),
        tc_session(TestCaseDraft(requirement_id="REQ-1", test_type=TestType.NEGATIVE)),
        tc_session(TestCaseDraft(requirement_id="REQ-1", test_type=TestType.EQUIVALENCE,
                                        expected_result="Works fast")),
        bug_session(context=REQS), bug_session(BugReportDraft(expected_result="Loads quickly")),
    ]
    return [q for s in sessions for q in s.questions]


def test_question_catalog_covers_every_kind():
    found = {q.prompt_key for q in all_questions()}
    assert len(found) >= 30


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_every_question_renders_in_every_language(lang):
    for question in all_questions():
        prompt, reason = render_question(question, lang)
        assert prompt and reason, question.id
        assert "grill." not in prompt + reason and "question." not in prompt + reason
        assert "{" not in prompt + reason
        if lang != "en" and question.prompt_key:
            assert prompt != render_question(question, "en")[0], question.id
        for choice in question.choices:
            assert render_choice(choice, lang) and "grill." not in render_choice(choice, lang)
