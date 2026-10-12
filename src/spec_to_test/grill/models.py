"""Grill Mode data models: workflow state, drafts, questions and review findings.

Trust rules built into these models:
- Source requirements are kept verbatim; a draft never rewrites them.
- Every draft field records where its value came from (`Provenance`), so a
  user-confirmed fact is never mixed up with an assumption or an AI suggestion.
- Unknown values stay empty and are marked UNKNOWN instead of being guessed.
- A session reaches FINALIZED only through an explicit confirmation step.
"""

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, model_validator

from spec_to_test.models import Requirement, Severity, Source, TestType

SCHEMA_VERSION = 1


class GrillKind(StrEnum):
    REQUIREMENTS = "requirements"
    TEST_CASE = "test_case"
    BUG_REPORT = "bug_report"
    # QA Review: check an existing artifact without an interview.
    REVIEW = "review"


class ArtifactType(StrEnum):
    """What the session produces or reviews."""

    REQUIREMENTS = "requirements"
    TEST_CASE = "test_case"
    BUG_REPORT = "bug_report"


class GrillMode(StrEnum):
    INTERVIEW = "interview"  # build the artifact by answering questions
    REVIEW_DRAFT = "review_draft"  # start from the user's draft and improve it


class GrillStep(StrEnum):
    COLLECT_INPUT = "collect_input"
    ASK_QUESTION = "ask_question"
    SHOW_DRAFT = "show_draft"
    REVIEW = "review"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    FINALIZED = "finalized"
    CANCELLED = "cancelled"


TERMINAL_STEPS = frozenset({GrillStep.FINALIZED, GrillStep.CANCELLED})


class Provenance(StrEnum):
    """Where a draft value came from. Shown to the user and kept on export."""

    SOURCE = "source"  # present in the input the user provided (document or draft)
    USER_CONFIRMED = "user_confirmed"
    ASSUMPTION = "assumption"  # accepted for now, not confirmed
    AI_SUGGESTION = "ai_suggestion"
    UNKNOWN = "unknown"  # the user said the value is not known


class Reproducibility(StrEnum):
    ALWAYS = "always"
    INTERMITTENT = "intermittent"
    ONCE = "once"
    NOT_REPRODUCIBLE = "not_reproducible"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# Drafts (fields are optional until the user fills them)
# ---------------------------------------------------------------------------

class _Draft(BaseModel):
    # Field name -> where its current value came from. No entry = not filled yet.
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    # Free-form assumptions the user accepted without confirmation.
    assumptions: list[str] = Field(default_factory=list)


class TestCaseDraft(_Draft):
    __test__ = False  # tell pytest this is not a test class

    draft_type: Literal["test_case"] = "test_case"
    title: str = ""
    objective: str = ""
    # A real requirement ID from the document, or empty. Never invented.
    requirement_id: str = ""
    # Free-text feature under test when no requirement ID exists.
    feature: str = ""
    test_type: TestType | None = None
    preconditions: list[str] = Field(default_factory=list)
    test_data: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    expected_result: str = ""


class BugReportDraft(_Draft):
    draft_type: Literal["bug_report"] = "bug_report"
    summary: str = ""
    requirement_id: str = ""
    environment: str = ""
    app_version: str = ""
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    actual_result: str = ""
    expected_result: str = ""
    reproducibility: Reproducibility | None = None
    # Descriptions of screenshots, logs or links the user actually has.
    evidence: list[str] = Field(default_factory=list)
    severity: Severity | None = None
    priority: Priority | None = None


class Statement(BaseModel):
    """A clarification attached to requirements (never a rewrite of them)."""

    text: str = Field(min_length=1)
    provenance: Provenance
    requirement_ids: list[str] = Field(default_factory=list)
    # ID of the question that produced it, so re-answering replaces it.
    origin: str = ""


class RequirementsDraft(_Draft):
    draft_type: Literal["requirements"] = "requirements"
    # Original requirements, verbatim (facts from the source).
    requirements: list[Requirement] = Field(default_factory=list)
    statements: list[Statement] = Field(default_factory=list)


Draft = Annotated[TestCaseDraft | BugReportDraft | RequirementsDraft, Field(discriminator="draft_type")]

DRAFT_TYPES: dict[ArtifactType, type[TestCaseDraft] | type[BugReportDraft] | type[RequirementsDraft]] = {
    ArtifactType.TEST_CASE: TestCaseDraft,
    ArtifactType.BUG_REPORT: BugReportDraft,
    ArtifactType.REQUIREMENTS: RequirementsDraft,
}


# ---------------------------------------------------------------------------
# Questions and answers
# ---------------------------------------------------------------------------

class Choice(BaseModel):
    value: str = Field(min_length=1)
    label_key: str = ""  # translated label
    label_text: str = ""  # literal label (e.g. a requirement ID)


class Question(BaseModel):
    # Stable ID; an answered ID is never asked again.
    id: str = Field(min_length=1)
    # Draft field the answer fills; "" means a clarification statement.
    field: str = ""
    prompt_key: str = ""
    prompt_text: str = ""  # literal prompt, e.g. from an AI suggestion
    params: dict[str, str] = Field(default_factory=dict)
    # Why the question matters (shown next to it).
    reason_key: str = ""
    reason_text: str = ""
    choices: list[Choice] = Field(default_factory=list)
    allow_free_text: bool = True
    # Essential questions cannot be skipped (but may be answered "unknown").
    essential: bool = True
    requirement_ids: list[str] = Field(default_factory=list)
    origin: Source = Source.RULE
    # How much a test depends on the answer (AI interviewer questions); "" = not rated.
    importance: Literal["", "high", "medium", "low"] = ""

    @model_validator(mode="after")
    def _has_prompt(self) -> "Question":
        if not (self.prompt_key or self.prompt_text.strip()):
            raise ValueError("a question needs a prompt")
        if not self.allow_free_text and not self.choices:
            raise ValueError("a question without free text needs choices")
        return self


class AnswerStatus(StrEnum):
    ANSWERED = "answered"  # confirmed by the user
    ASSUMED = "assumed"  # accepted as an assumption, not confirmed
    UNKNOWN = "unknown"  # the user does not know
    SKIPPED = "skipped"


class Answer(BaseModel):
    question_id: str = Field(min_length=1)
    status: AnswerStatus
    value: str = ""
    # Increases every time the user changes this answer.
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _value_matches_status(self) -> "Answer":
        has_value = bool(self.value.strip())
        if self.status in (AnswerStatus.ANSWERED, AnswerStatus.ASSUMED) and not has_value:
            raise ValueError("an answer needs a value")
        if self.status in (AnswerStatus.UNKNOWN, AnswerStatus.SKIPPED) and has_value:
            raise ValueError("unknown or skipped answers carry no value")
        return self


# ---------------------------------------------------------------------------
# Review findings
# ---------------------------------------------------------------------------

class FindingLevel(StrEnum):
    BLOCKING = "blocking"  # must be fixed before finalizing
    WARNING = "warning"  # fix it, or explicitly accept it as unresolved
    SUGGESTION = "suggestion"  # optional improvement


class ReviewCategory(StrEnum):
    REQUIRED_FIELD = "required_field"
    UNKNOWN_VALUE = "unknown_value"
    PLACEHOLDER = "placeholder"
    DUPLICATE = "duplicate"
    TRACEABILITY = "traceability"
    ASSUMPTION = "assumption"
    AI_SUGGESTION = "ai_suggestion"
    CONTRADICTION = "contradiction"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CLARITY = "clarity"
    MISSING_CONDITION = "missing_condition"
    EXECUTABILITY = "executability"
    OPEN_QUESTION = "open_question"


class ReviewFinding(BaseModel):
    level: FindingLevel
    category: ReviewCategory
    field: str = ""
    # Translated message and fix (keys), or literal text from an AI review.
    message_key: str = ""
    message_text: str = ""
    suggestion_key: str = ""
    suggestion_text: str = ""
    params: dict[str, str] = Field(default_factory=dict)
    requirement_ids: list[str] = Field(default_factory=list)
    origin: Source = Source.RULE

    @model_validator(mode="after")
    def _has_message(self) -> "ReviewFinding":
        if not (self.message_key or self.message_text.strip()):
            raise ValueError("a finding needs a message")
        return self


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class GrillSession(BaseModel):
    """One Grill workflow. Stored per browser session; never shared between users."""

    schema_version: int = SCHEMA_VERSION
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: GrillKind
    artifact: ArtifactType
    mode: GrillMode = GrillMode.INTERVIEW
    step: GrillStep = GrillStep.COLLECT_INPUT
    # Increases with every transition; used to reject stale UI actions.
    revision: int = Field(default=0, ge=0)
    input_text: str = ""
    # Requirements from the analyzed document, for traceability checks.
    context_requirements: list[Requirement] = Field(default_factory=list)
    draft: Draft | None = None
    # Increases whenever the draft content changes.
    draft_revision: int = Field(default=0, ge=0)
    questions: list[Question] = Field(default_factory=list)
    answers: dict[str, Answer] = Field(default_factory=dict)
    current_question_id: str | None = None
    # Questions in the order they were shown (used by "back").
    history: list[str] = Field(default_factory=list)
    # The user chose to stop the interview and work on the draft.
    interview_closed: bool = False
    findings: list[ReviewFinding] = Field(default_factory=list)
    # Draft revision the findings were computed for (None = never reviewed).
    reviewed_revision: int | None = None
    accepted_unresolved: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> "GrillSession":
        if self.kind == GrillKind.REVIEW:
            if self.mode != GrillMode.REVIEW_DRAFT:
                raise ValueError("QA review works on an existing draft")
        elif self.artifact.value != self.kind.value:
            raise ValueError("artifact does not match the workflow")
        if self.draft is not None and self.draft.draft_type != self.artifact.value:
            raise ValueError("draft type does not match the artifact")
        # A session cancelled before any input has no draft.
        if self.step not in (GrillStep.COLLECT_INPUT, GrillStep.CANCELLED) and self.draft is None:
            raise ValueError("a draft is required after input")
        question_ids = [q.id for q in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question IDs must be unique")
        if any(key != answer.question_id for key, answer in self.answers.items()):
            raise ValueError("answer keys must match question IDs")
        if self.step == GrillStep.ASK_QUESTION and self.current_question_id not in question_ids:
            raise ValueError("the current question is unknown")
        if self.step in (GrillStep.AWAITING_CONFIRMATION, GrillStep.FINALIZED):
            if self.reviewed_revision != self.draft_revision:
                raise ValueError("confirmation requires an up-to-date review")
        return self

    # --- Derived views ----------------------------------------------------

    def question(self, question_id: str) -> Question | None:
        return next((q for q in self.questions if q.id == question_id), None)

    @property
    def current_question(self) -> Question | None:
        return self.question(self.current_question_id) if self.current_question_id else None

    @property
    def pending_questions(self) -> list[Question]:
        """Questions that have not been answered, marked unknown, or skipped."""
        return [q for q in self.questions if q.id not in self.answers]

    @property
    def unresolved_questions(self) -> list[Question]:
        """Pending questions plus those answered "unknown" or skipped."""
        open_statuses = (AnswerStatus.UNKNOWN, AnswerStatus.SKIPPED)
        return [
            q for q in self.questions
            if q.id not in self.answers or self.answers[q.id].status in open_statuses
        ]

    @property
    def progress(self) -> tuple[int, int]:
        """(questions handled, questions known so far)."""
        return len(self.questions) - len(self.pending_questions), len(self.questions)

    @property
    def is_terminal(self) -> bool:
        return self.step in TERMINAL_STEPS

    @property
    def review_is_current(self) -> bool:
        return self.reviewed_revision is not None and self.reviewed_revision == self.draft_revision

    @property
    def blocking_findings(self) -> list[ReviewFinding]:
        return [f for f in self.findings if f.level == FindingLevel.BLOCKING]

    @property
    def warning_findings(self) -> list[ReviewFinding]:
        return [f for f in self.findings if f.level == FindingLevel.WARNING]

    @property
    def known_requirement_ids(self) -> set[str] | None:
        """IDs a draft may link to, or None when no document is loaded."""
        if isinstance(self.draft, RequirementsDraft):
            return {r.id for r in self.draft.requirements}
        if self.context_requirements:
            return {r.id for r in self.context_requirements}
        return None


def load_session(raw: Any) -> GrillSession | None:
    """Return a valid session from session state, or None if missing or stale.

    Accepts a GrillSession (possibly from an older copy of the class after a
    code reload) or a plain dict. Anything invalid is discarded, never repaired.
    """
    if raw is None:
        return None
    try:
        data = raw.model_dump() if isinstance(raw, BaseModel) else raw
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            return None
        return GrillSession.model_validate(data)
    except (ValidationError, ValueError, TypeError, AttributeError):
        return None
