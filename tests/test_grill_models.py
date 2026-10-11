"""Grill models: validation rules, invariants and safe loading from session state."""

import pytest
from pydantic import ValidationError

from spec_to_test.grill.models import (
    SCHEMA_VERSION,
    Answer,
    AnswerStatus,
    ArtifactType,
    BugReportDraft,
    GrillKind,
    GrillMode,
    GrillSession,
    GrillStep,
    Question,
    RequirementsDraft,
    TestCaseDraft,
    load_session,
)
from spec_to_test.grill.workflow import GrillWorkflow
from spec_to_test.models import Requirement


def test_answer_value_must_match_status():
    assert Answer(question_id="q", status=AnswerStatus.ANSWERED, value="yes").value == "yes"
    with pytest.raises(ValidationError):
        Answer(question_id="q", status=AnswerStatus.ANSWERED, value="  ")
    with pytest.raises(ValidationError):
        Answer(question_id="q", status=AnswerStatus.UNKNOWN, value="guess")


def test_question_needs_a_prompt_and_choices_when_free_text_is_off():
    with pytest.raises(ValidationError):
        Question(id="q")
    with pytest.raises(ValidationError):
        Question(id="q", prompt_text="Pick one", allow_free_text=False)


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": GrillKind.REVIEW, "artifact": ArtifactType.TEST_CASE, "mode": GrillMode.INTERVIEW},
        {"kind": GrillKind.TEST_CASE, "artifact": ArtifactType.BUG_REPORT},
        {"kind": GrillKind.TEST_CASE, "artifact": ArtifactType.TEST_CASE, "draft": BugReportDraft()},
        {"kind": GrillKind.TEST_CASE, "artifact": ArtifactType.TEST_CASE, "step": GrillStep.SHOW_DRAFT},
        {"kind": GrillKind.TEST_CASE, "artifact": ArtifactType.TEST_CASE, "draft": TestCaseDraft(),
         "step": GrillStep.ASK_QUESTION, "current_question_id": "missing"},
        {"kind": GrillKind.TEST_CASE, "artifact": ArtifactType.TEST_CASE,
         "questions": [Question(id="q", prompt_text="a"), Question(id="q", prompt_text="b")]},
        {"kind": GrillKind.TEST_CASE, "artifact": ArtifactType.TEST_CASE,
         "answers": {"a": Answer(question_id="b", status=AnswerStatus.SKIPPED)}},
    ],
)
def test_inconsistent_sessions_are_rejected(fields):
    with pytest.raises(ValidationError):
        GrillSession(**fields)


def test_drafts_round_trip_through_json():
    for kind, draft in [
        (GrillKind.TEST_CASE, TestCaseDraft(title="T")),
        (GrillKind.BUG_REPORT, BugReportDraft(summary="S")),
        (GrillKind.REQUIREMENTS, RequirementsDraft(requirements=[Requirement(id="REQ-1", text="Text here.")])),
    ]:
        session = GrillWorkflow().submit_input(GrillWorkflow.start(kind), draft)
        restored = GrillSession.model_validate_json(session.model_dump_json())
        assert restored == session
        assert type(restored.draft) is type(draft)


def test_progress_and_unresolved_questions():
    session = GrillSession(
        kind=GrillKind.TEST_CASE, artifact=ArtifactType.TEST_CASE,
        questions=[Question(id=q, prompt_text=q) for q in ("a", "b", "c")],
        answers={
            "a": Answer(question_id="a", status=AnswerStatus.ANSWERED, value="x"),
            "b": Answer(question_id="b", status=AnswerStatus.UNKNOWN),
        },
    )
    assert session.progress == (2, 3)
    assert [q.id for q in session.pending_questions] == ["c"]
    assert [q.id for q in session.unresolved_questions] == ["b", "c"]


def test_load_session_accepts_valid_state():
    session = GrillWorkflow.start(GrillKind.BUG_REPORT)
    assert load_session(session) == session
    assert load_session(session.model_dump()) == session


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "garbage",
        42,
        {"kind": "test_case"},
        {"schema_version": SCHEMA_VERSION + 1, "kind": "test_case", "artifact": "test_case"},
        {"schema_version": SCHEMA_VERSION, "kind": "test_case", "artifact": "test_case", "step": "show_draft"},
        {"schema_version": SCHEMA_VERSION, "kind": "nonsense", "artifact": "test_case"},
    ],
)
def test_invalid_or_stale_state_is_discarded(raw):
    assert load_session(raw) is None
