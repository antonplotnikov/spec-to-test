"""Audit log, decision traceability and schema migration of Grill sessions."""

import json
from dataclasses import replace

from spec_to_test.grill.models import (
    SCHEMA_VERSION,
    AnswerStatus,
    AuditAction,
    ClarificationState,
    GrillKind,
    GrillMode,
    GrillStep,
    Question,
    RequirementsDraft,
    TestCaseDraft,
    load_session,
    migrate_session_data,
)
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW
from spec_to_test.grill.trace import (
    answer_history,
    audit_data,
    audit_json,
    audit_rows,
    decision_records,
    state_counts,
    trace_markdown,
)
from spec_to_test.i18n import t
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import Requirement, Source

TICKS = iter(f"2026-10-13T10:{n // 60:02d}:{n % 60:02d}+00:00" for n in range(10_000))
WF = replace(DETERMINISTIC_WORKFLOW, clock=lambda: next(TICKS))
REQS = extract_requirements("""REQ-1: The password must be at least 8 characters.
REQ-2: The password must be at least 10 characters.
REQ-3: The page should load fast.""")
CONTRADICTION = "rule.contradiction.REQ-1+REQ-2"
VAGUE = "rule.ambiguous_wording.REQ-3"


def requirements_session():
    return WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=REQS))


def actions(session) -> list[AuditAction]:
    return [e.action for e in session.events]


# --- Audit log ---------------------------------------------------------------------------

def test_every_answer_and_change_is_logged_with_the_previous_value():
    session = requirements_session()
    assert actions(session) == [AuditAction.STARTED] and session.created_at and session.updated_at
    session = WF.answer(session, "REQ-1: The password must be at least 8 characters.")
    session = WF.answer(session, "Within 2 seconds", AnswerStatus.ASSUMED)
    session = WF.edit_answer(session, VAGUE)
    session = WF.answer(session, "Within 2 seconds")  # now confirmed
    answers = [e for e in session.events if e.question_id == VAGUE]
    assert [e.action for e in answers] == [AuditAction.ANSWERED, AuditAction.ANSWER_CHANGED]
    changed = answers[-1]
    assert (changed.previous_status, changed.previous_value) == (AnswerStatus.ASSUMED, "Within 2 seconds")
    assert (changed.status, changed.value, changed.answer_revision) == (AnswerStatus.ANSWERED, "Within 2 seconds", 2)
    assert all(e.at for e in session.events)
    assert [e.at for e in session.events] == sorted(e.at for e in session.events)  # appended in order


def test_an_unchanged_answer_is_not_logged_again():
    session = WF.answer(requirements_session(), "REQ-1: The password must be at least 8 characters.")
    before = len(session.events)
    again = WF.answer(WF.edit_answer(session, CONTRADICTION), "REQ-1: The password must be at least 8 characters.")
    assert len(again.events) == before


def test_review_confirmation_cancel_and_draft_edits_are_logged():
    draft = TestCaseDraft(requirement_id="REQ-1", title="Short", test_type="negative", steps=["Enter 7"],
                          expected_result="Rejected")
    session = WF.submit_input(WF.start(GrillKind.TEST_CASE, GrillMode.REVIEW_DRAFT, context_requirements=REQS), draft)
    session = WF.proceed_to_draft(session) if session.step == GrillStep.ASK_QUESTION else session
    session = WF.update_draft(session, draft.model_copy(update={"title": "Seven characters are rejected"}))
    edit = session.events[-1]
    assert edit.action == AuditAction.DRAFT_EDITED and edit.fields == ["title"] and edit.origin == Source.USER
    session = WF.review(session)
    assert session.events[-1].action == AuditAction.REVIEWED and "blocking=" in session.events[-1].detail
    assert actions(WF.cancel(session))[-1] == AuditAction.CANCELLED


def test_ai_questions_are_logged_with_their_model():
    question = Question(id="ai.req.1", prompt_text="Is there a maximum length?", requirement_ids=["REQ-1"],
                        origin=Source.AI, ai_model="claude-opus-5-5")
    session = WF.add_questions(requirements_session(), [question])
    added = session.events[-1]
    assert (added.action, added.question_id, added.origin, added.detail) == (
        AuditAction.QUESTION_ADDED, "ai.req.1", Source.AI, "claude-opus-5-5")


def test_the_input_session_is_never_changed():
    session = requirements_session()
    snapshot = session.model_dump()
    WF.answer(session, "REQ-1: The password must be at least 8 characters.")
    assert session.model_dump() == snapshot


# --- Decision trace ------------------------------------------------------------------------

def test_each_decision_has_its_source_state_and_history():
    session = requirements_session()
    session = WF.answer(session, "REQ-2: The password must be at least 10 characters.")  # confirmed
    session = WF.answer(session, "Within 2 seconds", AnswerStatus.ASSUMED)
    records = {r.question_id: r for r in decision_records(session)}
    contradiction = records[CONTRADICTION]
    assert contradiction.origin == "contradiction" and contradiction.state == ClarificationState.CONFIRMED
    assert contradiction.requirement_ids == ["REQ-1", "REQ-2"] and "REQ-1, REQ-2" in contradiction.basis
    vague = records[VAGUE]
    assert vague.origin == "rule" and "fast" in vague.basis and vague.state == ClarificationState.ASSUMPTION
    assert [(h.status, h.value) for h in vague.history] == [(AnswerStatus.ASSUMED, "Within 2 seconds")]


def test_unknown_and_open_items_have_no_value_and_conflicts_are_flagged():
    session = requirements_session()
    session = WF.answer(session, "", AnswerStatus.UNKNOWN)
    records = {r.question_id: r for r in decision_records(session)}
    assert records[CONTRADICTION].state == ClarificationState.UNKNOWN and records[CONTRADICTION].value == ""
    assert records[VAGUE].state == ClarificationState.OPEN and records[VAGUE].history == []


def test_an_answer_contradicting_its_requirement_is_a_conflict_not_a_decision():
    requirements = extract_requirements("REQ-1: The username should be easy to remember and at most 20 characters long.")
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=requirements))
    session = WF.answer(session, "At most 15 characters, letters only.")
    records = {r.question_id: r for r in decision_records(session)}
    clarification = records["rule.ambiguous_wording.REQ-1"]
    assert clarification.state == ClarificationState.CONFLICT
    assert clarification.value == "At most 15 characters, letters only."  # kept, but marked as disputed
    decision = next(r for r in records.values() if r.origin == "conflict")
    assert decision.state == ClarificationState.OPEN and "20 characters" in decision.basis
    assert state_counts(list(records.values()))[ClarificationState.CONFLICT] == 1


def test_the_trace_never_invents_requirements():
    session = WF.submit_input(
        WF.start(GrillKind.TEST_CASE, context_requirements=REQS), TestCaseDraft(requirement_id="REQ-99"),
    )
    question = Question(id="ai.tc.1", field="steps", prompt_text="Which steps?", requirement_ids=["REQ-42"],
                        origin=Source.AI)
    session = WF.add_questions(session, [question])
    known = {r.id for r in REQS}
    for record in decision_records(session):
        assert set(record.requirement_ids) <= known  # REQ-99 and REQ-42 are not in the document
    data = audit_data(session)
    assert {r["id"] for r in data["requirements"]} == known


def test_audit_exports():
    session = WF.answer(requirements_session(), "", AnswerStatus.UNKNOWN)
    data = json.loads(audit_json(session))
    assert data["session_id"] == session.id and data["events"][0]["action"] == "started"
    assert {d["state"] for d in data["decisions"]} >= {"unknown", "open"}
    rows = audit_rows(session)
    assert rows[0][t("grill.audit.col_action")] == t("grill.audit.action.answered")  # newest first
    markdown = trace_markdown(session)
    assert t("grill.trace.heading") in markdown and t("grill.state.unknown") in markdown


def test_trace_is_translated():
    session = WF.answer(requirements_session(), "", AnswerStatus.UNKNOWN)
    for lang in ("uk", "ru"):
        markdown = trace_markdown(session, lang)
        assert t("grill.trace.heading", lang) in markdown and "Decision trace" not in markdown


# --- Schema migration ------------------------------------------------------------------------

def v1_data() -> dict:
    """A session as schema 1 stored it: no events, timestamps, settled IDs, risk or model."""
    session = WF.answer(requirements_session(), "REQ-1: The password must be at least 8 characters.")
    data = session.model_dump(mode="json")
    for key in ("events", "created_at", "updated_at", "settled_question_ids"):
        data.pop(key)
    for question in data["questions"]:
        question.pop("risk")
        question.pop("ai_model")
    data["schema_version"] = 1
    return data


def test_schema_1_sessions_are_migrated_without_losing_answers():
    old = v1_data()
    session = load_session(old)
    assert session is not None and session.schema_version == SCHEMA_VERSION == 3
    assert session.answers[CONTRADICTION].value == "REQ-1: The password must be at least 8 characters."
    assert session.history == old["history"] and session.current_question_id == old["current_question_id"]
    assert [e.action for e in session.events] == [AuditAction.MIGRATED]
    # The current answer is still in the history, without a made-up time.
    assert [(h.at, h.value) for h in answer_history(session, CONTRADICTION)] == [
        ("", "REQ-1: The password must be at least 8 characters.")]


def test_migration_keeps_working_and_refuses_unknown_versions():
    session = load_session(v1_data())
    assert session is not None
    session = WF.answer(session, "Within 2 seconds")
    assert session.events[-1].action == AuditAction.ANSWERED
    assert load_session({**v1_data(), "schema_version": 4}) is None
    assert load_session({**v1_data(), "schema_version": "1"}) is None
    assert migrate_session_data(session.model_dump(mode="json")) == session.model_dump(mode="json")


def test_risk_defaults_for_old_questions():
    question = Question.model_validate({"id": "rule.x.REQ-1", "prompt_key": "question.ambiguous_wording"})
    assert question.risk == 0 and question.ai_model == ""


def test_requirement_model_unchanged():
    assert Requirement(id="REQ-1", text="x").model_dump().keys() == {"id", "text", "language", "source_line", "has_explicit_id"}
