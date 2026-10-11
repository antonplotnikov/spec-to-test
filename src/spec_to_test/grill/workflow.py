"""Grill workflow: validated transitions between explicit steps.

    COLLECT_INPUT ─submit_input→ ASK_QUESTION ⇄ (answer / skip / back / edit)
                                     │ proceed_to_draft, or no questions left
                                     ▼
                                 SHOW_DRAFT ─update_draft→ SHOW_DRAFT
                                     │ review (also allowed while asking)
                                     ▼
                                   REVIEW ─request_confirmation→ AWAITING_CONFIRMATION ─confirm→ FINALIZED
                                     ▲ resume ◀───────────────────────────┘
    Any non-final step ─cancel→ CANCELLED.

Analysis, context updates and re-analysis are not separate resting steps:
they run inside a transition (the planner is called again after each answer).

Optional AI output enters only through two transitions, and only after the
caller (the page) has asked for consent and called the model:
- add_questions: extra questions, never essential; kept until handled.
- add_ai_findings: extra review findings, never blocking; replaced by the
  next review, so they always describe the draft that was reviewed.

Every method returns a new session and leaves its input untouched, so the
workflow keeps no state of its own and one instance can serve every user.
Passing `expected_revision` rejects actions from an outdated page.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from spec_to_test.grill.drafts import AnyDraft, DraftError, apply_answer, check_length, editable_fields, merge_edit
from spec_to_test.grill.models import (
    Answer,
    AnswerStatus,
    ArtifactType,
    FindingLevel,
    GrillKind,
    GrillMode,
    GrillSession,
    GrillStep,
    Question,
    RequirementsDraft,
    ReviewFinding,
)
from spec_to_test.grill.validation import deterministic_review, sort_findings
from spec_to_test.models import Requirement, Source

QuestionPlanner = Callable[[GrillSession], list[Question]]
Reviewer = Callable[[GrillSession], list[ReviewFinding]]


class GrillError(Exception):
    """A rejected action. `code` maps to the grill.error.<code> translation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Action(StrEnum):
    SUBMIT_INPUT = "submit_input"
    ANSWER = "answer"
    SKIP = "skip"
    BACK = "back"
    EDIT_ANSWER = "edit_answer"
    PROCEED_TO_DRAFT = "proceed_to_draft"
    CONTINUE_INTERVIEW = "continue_interview"
    UPDATE_DRAFT = "update_draft"
    REVIEW = "review"
    RESUME = "resume"
    REQUEST_CONFIRMATION = "request_confirmation"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    ADD_QUESTIONS = "add_questions"
    ADD_AI_FINDINGS = "add_ai_findings"


_ACTIVE = frozenset(GrillStep) - {GrillStep.FINALIZED, GrillStep.CANCELLED}

# Steps from which each action is allowed.
ALLOWED: dict[Action, frozenset[GrillStep]] = {
    Action.SUBMIT_INPUT: frozenset({GrillStep.COLLECT_INPUT}),
    Action.ANSWER: frozenset({GrillStep.ASK_QUESTION}),
    Action.SKIP: frozenset({GrillStep.ASK_QUESTION}),
    Action.BACK: frozenset({GrillStep.ASK_QUESTION, GrillStep.SHOW_DRAFT}),
    Action.EDIT_ANSWER: frozenset({GrillStep.ASK_QUESTION, GrillStep.SHOW_DRAFT, GrillStep.REVIEW}),
    Action.PROCEED_TO_DRAFT: frozenset({GrillStep.ASK_QUESTION}),
    Action.CONTINUE_INTERVIEW: frozenset({GrillStep.SHOW_DRAFT}),
    Action.UPDATE_DRAFT: frozenset({GrillStep.SHOW_DRAFT, GrillStep.REVIEW}),
    Action.REVIEW: frozenset({GrillStep.ASK_QUESTION, GrillStep.SHOW_DRAFT, GrillStep.REVIEW}),
    Action.RESUME: frozenset({GrillStep.REVIEW, GrillStep.AWAITING_CONFIRMATION}),
    Action.REQUEST_CONFIRMATION: frozenset({GrillStep.REVIEW}),
    Action.CONFIRM: frozenset({GrillStep.AWAITING_CONFIRMATION}),
    Action.CANCEL: _ACTIVE,
    Action.ADD_QUESTIONS: frozenset({GrillStep.ASK_QUESTION, GrillStep.SHOW_DRAFT, GrillStep.REVIEW}),
    Action.ADD_AI_FINDINGS: frozenset({GrillStep.REVIEW}),
}


def allowed_actions(session: GrillSession) -> set[Action]:
    return {action for action, steps in ALLOWED.items() if session.step in steps}


def no_questions(session: GrillSession) -> list[Question]:
    return []


@dataclass(frozen=True)
class GrillWorkflow:
    """Stateless controller. `planner` proposes questions, `reviewer` checks drafts."""

    planner: QuestionPlanner = no_questions
    reviewer: Reviewer = deterministic_review

    # --- Start --------------------------------------------------------------

    @staticmethod
    def start(
        kind: GrillKind,
        mode: GrillMode = GrillMode.INTERVIEW,
        artifact: ArtifactType | None = None,
        context_requirements: list[Requirement] | None = None,
    ) -> GrillSession:
        if kind == GrillKind.REVIEW:
            if artifact is None:
                raise GrillError("missing_artifact")
            mode = GrillMode.REVIEW_DRAFT
        else:
            artifact = ArtifactType(kind.value)
        return GrillSession(
            kind=kind, artifact=artifact, mode=mode, context_requirements=list(context_requirements or [])
        )

    def submit_input(
        self, session: GrillSession, draft: AnyDraft, input_text: str = "", *, expected_revision: int | None = None
    ) -> GrillSession:
        """Store the user's input (or an empty draft for an interview) and analyze it."""
        new = self._begin(session, Action.SUBMIT_INPUT, expected_revision)
        if draft.draft_type != new.artifact.value:
            raise GrillError("draft_type_mismatch")
        new.draft = draft.model_copy(deep=True)
        new.input_text = input_text
        new.draft_revision = 1
        if new.kind == GrillKind.REVIEW:
            return self._finish(self._run_review(new))
        return self._finish(self._advance(new))

    # --- Interview ------------------------------------------------------------

    def answer(
        self,
        session: GrillSession,
        value: str,
        status: AnswerStatus = AnswerStatus.ANSWERED,
        *,
        expected_revision: int | None = None,
    ) -> GrillSession:
        """Answer the current question (confirmed, assumed, or unknown)."""
        if status == AnswerStatus.SKIPPED:
            return self.skip(session, expected_revision=expected_revision)
        new = self._begin(session, Action.ANSWER, expected_revision)
        question = self._current(new)
        if status != AnswerStatus.UNKNOWN:
            value = value.strip()
            if not value:
                raise GrillError("empty_answer")
            try:
                check_length(value)
            except DraftError as exc:
                raise GrillError(exc.code) from None
            if not question.allow_free_text and value not in {c.value for c in question.choices}:
                raise GrillError("invalid_choice")
        else:
            value = ""
        return self._finish(self._advance(self._record(new, question, status, value)))

    def skip(self, session: GrillSession, *, expected_revision: int | None = None) -> GrillSession:
        new = self._begin(session, Action.SKIP, expected_revision)
        question = self._current(new)
        if question.essential:
            raise GrillError("essential_question")
        return self._finish(self._advance(self._record(new, question, AnswerStatus.SKIPPED, "")))

    def back(self, session: GrillSession, *, expected_revision: int | None = None) -> GrillSession:
        """Show the previous question again; its answer can then be changed."""
        new = self._begin(session, Action.BACK, expected_revision)
        if new.step == GrillStep.SHOW_DRAFT:
            target = next((qid for qid in reversed(new.history) if new.question(qid)), None)
        else:
            position = new.history.index(new.current_question_id) if new.current_question_id in new.history else 0
            target = next((qid for qid in reversed(new.history[:position]) if new.question(qid)), None)
        if target is None:
            raise GrillError("no_previous_question")
        new.current_question_id = target
        new.step = GrillStep.ASK_QUESTION
        return self._finish(new)

    def edit_answer(
        self, session: GrillSession, question_id: str, *, expected_revision: int | None = None
    ) -> GrillSession:
        """Go back to any known question to change its answer."""
        new = self._begin(session, Action.EDIT_ANSWER, expected_revision)
        if new.question(question_id) is None:
            raise GrillError("unknown_question")
        new.current_question_id = question_id
        new.interview_closed = False
        new.step = GrillStep.ASK_QUESTION
        return self._finish(new)

    def proceed_to_draft(self, session: GrillSession, *, expected_revision: int | None = None) -> GrillSession:
        """Stop asking and show the draft; open questions stay marked as unresolved."""
        new = self._begin(session, Action.PROCEED_TO_DRAFT, expected_revision)
        new.interview_closed = True
        new.step = GrillStep.SHOW_DRAFT
        return self._finish(new)

    def continue_interview(self, session: GrillSession, *, expected_revision: int | None = None) -> GrillSession:
        new = self._begin(session, Action.CONTINUE_INTERVIEW, expected_revision)
        new.interview_closed = False
        new = self._advance(new)
        if new.step != GrillStep.ASK_QUESTION:
            raise GrillError("no_pending_questions")
        return self._finish(new)

    # --- Draft and review -------------------------------------------------------

    def update_draft(
        self, session: GrillSession, draft: AnyDraft, *, expected_revision: int | None = None
    ) -> GrillSession:
        """Accept a direct edit; changed fields become user-confirmed."""
        new = self._begin(session, Action.UPDATE_DRAFT, expected_revision)
        assert new.draft is not None  # guaranteed by the session invariants
        try:
            merged = merge_edit(new.draft, draft)
        except DraftError as exc:
            raise GrillError(exc.code) from None
        if merged != new.draft:
            new.draft = merged
            new.draft_revision += 1
            new.accepted_unresolved = False
        new.step = GrillStep.SHOW_DRAFT
        return self._finish(new)

    def review(self, session: GrillSession, *, expected_revision: int | None = None) -> GrillSession:
        """Run the reviewer on the current draft (allowed at any point after input)."""
        new = self._begin(session, Action.REVIEW, expected_revision)
        return self._finish(self._run_review(new))

    def resume(self, session: GrillSession, *, expected_revision: int | None = None) -> GrillSession:
        """Leave the review (or decline confirmation) and keep editing."""
        new = self._begin(session, Action.RESUME, expected_revision)
        current = new.current_question
        if current is not None and not new.interview_closed and current in new.pending_questions:
            new.step = GrillStep.ASK_QUESTION
        else:
            new.step = GrillStep.SHOW_DRAFT
        new.accepted_unresolved = False
        return self._finish(new)

    def request_confirmation(
        self, session: GrillSession, accept_unresolved: bool = False, *, expected_revision: int | None = None
    ) -> GrillSession:
        """Ask the user to confirm the reviewed draft.

        Blocking findings must be fixed. Warnings (unknown values, assumptions,
        open questions) are allowed only when the user explicitly accepts them.
        """
        new = self._begin(session, Action.REQUEST_CONFIRMATION, expected_revision)
        if not new.review_is_current:
            raise GrillError("review_outdated")
        if new.blocking_findings:
            raise GrillError("blocking_findings")
        if new.warning_findings and not accept_unresolved:
            raise GrillError("unresolved_not_accepted")
        new.accepted_unresolved = bool(new.warning_findings)
        new.step = GrillStep.AWAITING_CONFIRMATION
        return self._finish(new)

    def confirm(self, session: GrillSession, *, expected_revision: int | None = None) -> GrillSession:
        """The only way to finalize: an explicit user confirmation."""
        new = self._begin(session, Action.CONFIRM, expected_revision)
        if not new.review_is_current:
            raise GrillError("review_outdated")
        new.step = GrillStep.FINALIZED
        return self._finish(new)

    def cancel(self, session: GrillSession, *, expected_revision: int | None = None) -> GrillSession:
        new = self._begin(session, Action.CANCEL, expected_revision)
        new.step = GrillStep.CANCELLED
        return self._finish(new)

    # --- Optional AI output ----------------------------------------------------------

    def add_questions(
        self, session: GrillSession, questions: list[Question], *, expected_revision: int | None = None
    ) -> GrillSession:
        """Add AI questions and ask the first new one.

        Questions already known (same ID) are ignored. AI questions are never
        essential, so the user may always skip them.
        """
        new = self._begin(session, Action.ADD_QUESTIONS, expected_revision)
        assert new.draft is not None
        known = {q.id for q in new.questions}
        added: list[Question] = []
        for question in questions:
            if question.origin != Source.AI:
                raise GrillError("invalid_question")
            if question.field and question.field not in editable_fields(new.draft):
                raise GrillError("invalid_field")
            if not question.field and not isinstance(new.draft, RequirementsDraft):
                raise GrillError("invalid_field")
            if question.id in known:
                continue
            known.add(question.id)
            added.append(question.model_copy(update={"essential": False}, deep=True))
        if not added:
            raise GrillError("no_new_questions")
        new.questions = [*new.questions, *added]
        new.interview_closed = False
        new.accepted_unresolved = False
        new.current_question_id = added[0].id
        if added[0].id not in new.history:
            new.history.append(added[0].id)
        new.step = GrillStep.ASK_QUESTION
        return self._finish(new)

    def add_ai_findings(
        self, session: GrillSession, findings: list[ReviewFinding], *, expected_revision: int | None = None
    ) -> GrillSession:
        """Attach an AI review to the current review (replacing an earlier AI review).

        AI findings can warn or suggest, never block: they are not verified facts.
        """
        new = self._begin(session, Action.ADD_AI_FINDINGS, expected_revision)
        if not new.review_is_current:
            raise GrillError("review_outdated")
        if any(f.origin != Source.AI or f.level == FindingLevel.BLOCKING for f in findings):
            raise GrillError("invalid_findings")
        kept = [f for f in new.findings if f.origin != Source.AI]
        new.findings = sort_findings(kept + [f.model_copy(deep=True) for f in findings])
        new.accepted_unresolved = False
        return self._finish(new)

    # --- Internals ----------------------------------------------------------------

    @staticmethod
    def _begin(session: GrillSession, action: Action, expected_revision: int | None) -> GrillSession:
        if expected_revision is not None and expected_revision != session.revision:
            raise GrillError("stale_session")
        if session.step not in ALLOWED[action]:
            raise GrillError("invalid_transition")
        return session.model_copy(deep=True)

    @staticmethod
    def _finish(session: GrillSession) -> GrillSession:
        session.revision += 1
        # Re-validate so a transition can never produce an inconsistent session.
        return GrillSession.model_validate(session.model_dump())

    @staticmethod
    def _current(session: GrillSession) -> Question:
        question = session.current_question
        if question is None:
            raise GrillError("unknown_question")
        return question

    @staticmethod
    def _record(session: GrillSession, question: Question, status: AnswerStatus, value: str) -> GrillSession:
        previous = session.answers.get(question.id)
        if previous is not None and previous.status == status and previous.value == value:
            return session  # unchanged answer: just move on
        answer = Answer(
            question_id=question.id,
            status=status,
            value=value,
            revision=previous.revision + 1 if previous else 1,
        )
        assert session.draft is not None
        try:
            updated = apply_answer(session.draft, question, answer)
        except DraftError as exc:
            raise GrillError(exc.code) from None
        session.answers = {**session.answers, question.id: answer}
        if updated != session.draft:
            session.draft = updated
            session.draft_revision += 1
            session.accepted_unresolved = False
        return session

    def _replan(self, session: GrillSession) -> GrillSession:
        """Merge new planner output: keep handled questions, drop stale unanswered ones.

        AI questions are not the planner's, so they stay until the user handles them.
        """
        planned = self.planner(session)
        planned_ids = {q.id for q in planned}
        kept = [
            q for q in session.questions
            if (q.id in session.answers or q.origin == Source.AI) and q.id not in planned_ids
        ]
        session.questions = kept + [q for q in planned if q.id not in {k.id for k in kept}]
        session.history = [qid for qid in session.history if session.question(qid)]
        return session

    def _advance(self, session: GrillSession) -> GrillSession:
        """Re-analyze, then ask the next open question or show the draft."""
        session = self._replan(session)
        pending = session.pending_questions
        if pending and not session.interview_closed:
            session.current_question_id = pending[0].id
            if pending[0].id not in session.history:
                session.history.append(pending[0].id)
            session.step = GrillStep.ASK_QUESTION
        else:
            session.step = GrillStep.SHOW_DRAFT
        return session

    def _run_review(self, session: GrillSession) -> GrillSession:
        session.findings = self.reviewer(session)
        session.reviewed_revision = session.draft_revision
        session.step = GrillStep.REVIEW
        return session
