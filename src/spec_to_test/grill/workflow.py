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

The next question is always the highest-priority open one (ties keep queue
order), and the planner runs again after every answer, so the queue adapts.

Optional AI output enters only through these transitions, and only after the
caller (the page) has asked for consent and called the model:
- add_questions: extra questions, never essential; kept until handled; the
  first one is asked at once (the user asked for them).
- merge_questions: the AI interviewer's question joins the same ranked queue
  as the built-in ones (one interview, no separate AI phase).
- add_ai_findings: extra review findings, never blocking; replaced by the
  next review, so they always describe the draft that was reviewed.

Every method returns a new session and leaves its input untouched, so the
workflow keeps no state of its own and one instance can serve every user.
Passing `expected_revision` rejects actions from an outdated page.

Audit trail: every transition that changes something appends an `AuditEvent`
(answers keep their previous status and value), so the history of each
decision can be shown and exported. `clock` gives the timestamps.

Reactive queue: the open questions are recalculated after every answer
(confirmed, assumed or unknown), every direct draft edit, and every change of
finding status in the analyzed document (`sync_settled`). An open question
that no longer applies is not deleted: it moves to `session.retired` with the
reason (resolved in the document, answered by another answer, obsolete) and a
`question_retired` event, and comes back under the same ID (`question_restored`)
if it applies again. Answered questions are never removed, the question on
screen is replaced only if it was retired, and IDs never change, so progress,
traceability and the audit log stay intact.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from spec_to_test.grill.drafts import AnyDraft, DraftError, apply_answer, check_length, editable_fields, merge_edit
from spec_to_test.grill.models import (
    Answer,
    AnswerStatus,
    ArtifactType,
    AuditAction,
    AuditEvent,
    FindingLevel,
    GrillKind,
    GrillMode,
    GrillSession,
    GrillStep,
    Question,
    RequirementsDraft,
    RetiredQuestion,
    RetireReason,
    ReviewFinding,
    utc_now,
)
from spec_to_test.grill.validation import deterministic_review, sort_findings
from spec_to_test.models import Requirement, Source

QuestionPlanner = Callable[[GrillSession], list[Question]]
Reviewer = Callable[[GrillSession], list[ReviewFinding]]
# Open question ID -> ID of the answered question that already covers it.
Coverage = Callable[[GrillSession], dict[str, str]]


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
    MERGE_QUESTIONS = "merge_questions"
    ADD_AI_FINDINGS = "add_ai_findings"
    SYNC_FINDINGS = "sync_findings"


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
    Action.MERGE_QUESTIONS: frozenset({GrillStep.ASK_QUESTION, GrillStep.SHOW_DRAFT}),
    Action.ADD_AI_FINDINGS: frozenset({GrillStep.REVIEW}),
    Action.SYNC_FINDINGS: frozenset({
        GrillStep.ASK_QUESTION, GrillStep.SHOW_DRAFT, GrillStep.REVIEW, GrillStep.AWAITING_CONFIRMATION,
    }),
}


def allowed_actions(session: GrillSession) -> set[Action]:
    return {action for action, steps in ALLOWED.items() if session.step in steps}


def no_questions(session: GrillSession) -> list[Question]:
    return []


def no_coverage(session: GrillSession) -> dict[str, str]:
    return {}


@dataclass(frozen=True)
class GrillWorkflow:
    """Stateless controller. `planner` proposes questions, `reviewer` checks drafts."""

    planner: QuestionPlanner = no_questions
    reviewer: Reviewer = deterministic_review
    clock: Callable[[], str] = utc_now
    # Which open questions other answers already cover (they leave the queue).
    coverage: Coverage = no_coverage

    # --- Start --------------------------------------------------------------

    @staticmethod
    def start(
        kind: GrillKind,
        mode: GrillMode = GrillMode.INTERVIEW,
        artifact: ArtifactType | None = None,
        context_requirements: list[Requirement] | None = None,
        settled_question_ids: list[str] | None = None,
    ) -> GrillSession:
        """A new session. `settled_question_ids`: rule questions whose findings are already
        resolved in the analyzed document (they are not asked again)."""
        if kind == GrillKind.REVIEW:
            if artifact is None:
                raise GrillError("missing_artifact")
            mode = GrillMode.REVIEW_DRAFT
        else:
            artifact = ArtifactType(kind.value)
        return GrillSession(
            kind=kind, artifact=artifact, mode=mode, context_requirements=list(context_requirements or []),
            settled_question_ids=sorted(set(settled_question_ids or [])),
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
        new.created_at = new.created_at or self.clock()
        self._log(new, AuditAction.STARTED, origin=Source.USER, detail=new.mode.value)
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
            changed = [f for f in editable_fields(merged) if getattr(merged, f) != getattr(new.draft, f)]
            new.draft = merged
            new.draft_revision += 1
            new.accepted_unresolved = False
            self._log(new, AuditAction.DRAFT_EDITED, origin=Source.USER, fields=changed)
            new = self._replan(new)  # a filled field answers its open question
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
        self._log(new, AuditAction.CONFIRMATION_REQUESTED, origin=Source.USER,
                  detail=f"accepted_warnings={len(new.warning_findings)}" if new.accepted_unresolved else "")
        return self._finish(new)

    def confirm(self, session: GrillSession, *, expected_revision: int | None = None) -> GrillSession:
        """The only way to finalize: an explicit user confirmation."""
        new = self._begin(session, Action.CONFIRM, expected_revision)
        if not new.review_is_current:
            raise GrillError("review_outdated")
        new.step = GrillStep.FINALIZED
        self._log(new, AuditAction.CONFIRMED, origin=Source.USER)
        return self._finish(new)

    def cancel(self, session: GrillSession, *, expected_revision: int | None = None) -> GrillSession:
        new = self._begin(session, Action.CANCEL, expected_revision)
        new.step = GrillStep.CANCELLED
        self._log(new, AuditAction.CANCELLED, origin=Source.USER)
        return self._finish(new)

    # --- Finding status in the analyzed document ----------------------------------

    def sync_settled(
        self, session: GrillSession, settled_question_ids: list[str], *, expected_revision: int | None = None
    ) -> GrillSession:
        """Follow finding status changes made in the analyzed document during the interview.

        `settled_question_ids` are the rule questions whose findings are resolved
        now. A newly resolved finding's open question is retired; a reopened
        finding's question returns to the queue. Answers are never touched. The
        question on screen stays unless it was retired. A review that was shown
        is redone, because its open-question warnings changed.

        Returns the session unchanged (same revision) when nothing changed, so a
        page may call it on every render.
        """
        wanted = sorted(set(settled_question_ids))
        if session.is_terminal or not isinstance(session.draft, RequirementsDraft):
            return session
        if wanted == sorted(set(session.settled_question_ids)):
            return session
        new = self._begin(session, Action.SYNC_FINDINGS, expected_revision)
        before = set(new.settled_question_ids)
        resolved, reopened = sorted(set(wanted) - before), sorted(before - set(wanted))
        new.settled_question_ids = wanted
        self._log(new, AuditAction.FINDINGS_SYNCED, origin=Source.USER,
                  detail="; ".join(part for part in (
                      f"resolved: {', '.join(resolved)}" if resolved else "",
                      f"reopened: {', '.join(reopened)}" if reopened else "",
                  ) if part))
        pending_before = [q.id for q in new.pending_questions]
        known_before = {q.id for q in new.questions} | {r.question.id for r in new.retired}
        new = self._replan(new)
        for question_id in reopened:  # settled when the interview started: never in the queue before
            if question_id not in known_before and (question := new.question(question_id)) is not None:
                self._log(new, AuditAction.QUESTION_RESTORED, question_id=question_id, origin=question.origin)
        queue_changed = [q.id for q in new.pending_questions] != pending_before
        if new.step == GrillStep.ASK_QUESTION:
            if new.current_question is None:  # the question on screen was retired
                new = self._select(new)
        elif new.step == GrillStep.SHOW_DRAFT and not new.interview_closed:
            new = self._select(new)  # a reopened finding is asked at once
        elif new.step in (GrillStep.REVIEW, GrillStep.AWAITING_CONFIRMATION) and queue_changed:
            new.accepted_unresolved = False
            new = self._run_review(new)
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
        added = self._new_ai_questions(new, questions)
        if not added:
            raise GrillError("no_new_questions")
        new.questions = [*new.questions, *added]
        self._log_added(new, added)
        new.interview_closed = False
        new.accepted_unresolved = False
        new.current_question_id = added[0].id
        if added[0].id not in new.history:
            new.history.append(added[0].id)
        new.step = GrillStep.ASK_QUESTION
        return self._finish(new)

    def merge_questions(
        self, session: GrillSession, questions: list[Question], *, expected_revision: int | None = None
    ) -> GrillSession:
        """Add AI interviewer questions to the queue and ask whatever ranks highest.

        Unlike add_questions, the new question does not jump the queue: a
        high-priority built-in question is still asked first. A question the
        user went back to (already answered) stays on screen.
        """
        new = self._begin(session, Action.MERGE_QUESTIONS, expected_revision)
        assert new.draft is not None
        if new.interview_closed:
            raise GrillError("interview_closed")
        added = self._new_ai_questions(new, questions)
        if not added:
            raise GrillError("no_new_questions")
        new.questions = [*new.questions, *added]
        self._log_added(new, added)
        new.accepted_unresolved = False
        current = new.current_question
        if new.step == GrillStep.ASK_QUESTION and current is not None and current.id in new.answers:
            return self._finish(new)  # the user is changing an earlier answer
        return self._finish(self._select(new))

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
        self._log(new, AuditAction.AI_REVIEWED, origin=Source.AI, detail=f"findings={len(findings)}")
        return self._finish(new)

    # --- Internals ----------------------------------------------------------------

    @staticmethod
    def _new_ai_questions(session: GrillSession, questions: list[Question]) -> list[Question]:
        """Validated copies of AI questions the session does not have yet (never essential)."""
        assert session.draft is not None
        known = {q.id for q in session.questions} | {r.question.id for r in session.retired}
        added: list[Question] = []
        for question in questions:
            if question.origin != Source.AI:
                raise GrillError("invalid_question")
            if question.field and question.field not in editable_fields(session.draft):
                raise GrillError("invalid_field")
            if not question.field and not isinstance(session.draft, RequirementsDraft):
                raise GrillError("invalid_field")
            if question.id in known:
                continue
            known.add(question.id)
            added.append(question.model_copy(update={"essential": False}, deep=True))
        return added

    @staticmethod
    def _begin(session: GrillSession, action: Action, expected_revision: int | None) -> GrillSession:
        if expected_revision is not None and expected_revision != session.revision:
            raise GrillError("stale_session")
        if session.step not in ALLOWED[action]:
            raise GrillError("invalid_transition")
        return session.model_copy(deep=True)

    def _log(self, session: GrillSession, action: AuditAction, **details: object) -> None:
        session.events = [*session.events, AuditEvent(at=self.clock(), action=action, **details)]  # type: ignore[arg-type]

    def _log_added(self, session: GrillSession, added: list[Question]) -> None:
        for question in added:
            self._log(session, AuditAction.QUESTION_ADDED, question_id=question.id, origin=question.origin,
                      detail=question.ai_model)

    def _finish(self, session: GrillSession) -> GrillSession:
        session.updated_at = self.clock()
        session.revision += 1
        # Re-validate so a transition can never produce an inconsistent session.
        return GrillSession.model_validate(session.model_dump())

    @staticmethod
    def _current(session: GrillSession) -> Question:
        question = session.current_question
        if question is None:
            raise GrillError("unknown_question")
        return question

    def _record(self, session: GrillSession, question: Question, status: AnswerStatus, value: str) -> GrillSession:
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
        self._log(
            session, AuditAction.ANSWER_CHANGED if previous else AuditAction.ANSWERED,
            question_id=question.id, status=status, value=value, answer_revision=answer.revision,
            previous_status=previous.status if previous else None, previous_value=previous.value if previous else "",
            origin=Source.USER,
        )
        if updated != session.draft:
            session.draft = updated
            session.draft_revision += 1
            session.accepted_unresolved = False
        return session

    def _replan(self, session: GrillSession) -> GrillSession:
        """Recalculate the open questions; keep handled ones, retire those that no longer apply.

        AI questions are not the planner's, so they stay until the user handles
        them (or another answer covers them). A question that leaves the queue
        is kept in `session.retired` with its reason; one that applies again is
        restored under the same ID.
        """
        covered = {qid: by for qid, by in self.coverage(session).items() if qid not in session.answers}
        planned = [q for q in self.planner(session) if q.id not in covered]
        planned_ids = {q.id for q in planned}
        kept = [
            q for q in session.questions
            if (q.id in session.answers or (q.origin == Source.AI and q.id not in covered)) and q.id not in planned_ids
        ]
        kept_ids = {k.id for k in kept}
        questions = kept + [q for q in planned if q.id not in kept_ids]
        active = {q.id for q in questions}

        retired = {r.question.id: r for r in session.retired}
        for question in questions:
            if retired.pop(question.id, None) is not None:
                self._log(session, AuditAction.QUESTION_RESTORED, question_id=question.id, origin=question.origin)
        for question in session.questions:
            if question.id in active:
                continue
            if question.id in covered:
                reason, by = RetireReason.ANSWERED_ELSEWHERE, covered[question.id]
            elif question.id in session.settled_question_ids:
                reason, by = RetireReason.SETTLED, ""
            else:
                reason, by = RetireReason.OBSOLETE, ""
            retired[question.id] = RetiredQuestion(question=question, reason=reason, at=self.clock(), covered_by=by)
            self._log(session, AuditAction.QUESTION_RETIRED, question_id=question.id, origin=question.origin,
                      detail=f"{reason.value}:{by}" if by else reason.value)

        session.questions = questions
        session.retired = list(retired.values())
        session.history = [qid for qid in session.history if session.question(qid)]
        return session

    def _advance(self, session: GrillSession) -> GrillSession:
        """Re-analyze, then ask the highest-priority open question or show the draft."""
        return self._select(self._replan(session))

    @staticmethod
    def _select(session: GrillSession) -> GrillSession:
        upcoming = session.next_pending
        if upcoming is not None and not session.interview_closed:
            session.current_question_id = upcoming.id
            if upcoming.id not in session.history:
                session.history.append(upcoming.id)
            session.step = GrillStep.ASK_QUESTION
        else:
            session.step = GrillStep.SHOW_DRAFT
        return session

    def _run_review(self, session: GrillSession) -> GrillSession:
        session.findings = self.reviewer(session)
        session.reviewed_revision = session.draft_revision
        session.step = GrillStep.REVIEW
        counts = {level: sum(f.level == level for f in session.findings) for level in FindingLevel}
        self._log(session, AuditAction.REVIEWED, origin=Source.RULE,
                  detail=", ".join(f"{level.value}={n}" for level, n in counts.items()))
        return session
