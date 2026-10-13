"""Answer states (CONFIRMED / ASSUMPTION / UNKNOWN / CONFLICT / OPEN) and contradictions:
detected deterministically, asked about, resolved only by the user, and reported."""

from spec_to_test.grill.conflicts import (
    ConflictKind,
    detect_conflicts,
    question_state,
    question_states,
    superseded_questions,
    unresolved_conflicts,
)
from spec_to_test.grill.models import (
    AnswerStatus,
    ClarificationState,
    GrillKind,
    GrillMode,
    GrillSession,
    GrillStep,
    Question,
    RequirementsDraft,
    TestCaseDraft,
)
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.grill.report import build_report, report_markdown
from spec_to_test.grill.validation import deterministic_review
from spec_to_test.models import Requirement, Source

REQS = [
    Requirement(id="REQ-1", text="The password must be at least 8 characters."),
    Requirement(id="REQ-2", text="Users can upload a profile photo."),
]
SOURCE_CONFLICT = [
    Requirement(id="REQ-1", text="The password must be at least 8 characters."),
    Requirement(id="REQ-2", text="The password must be at least 10 characters."),
]
TEN = "The minimum is at least 10 characters."


def ai(qid: str, ids: list[str], text: str = "What is the rule?") -> Question:
    return Question(id=qid, prompt_text=text, requirement_ids=ids, origin=Source.AI, importance="high")


def with_answer(s: GrillSession, qid: str, ids: list[str], value: str, status=AnswerStatus.ANSWERED) -> GrillSession:
    s = WF.add_questions(s, [ai(qid, ids, f"Question {qid}?")])
    return WF.answer(s, value, status)


def started() -> GrillSession:
    return WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=REQS))


def finalize(s: GrillSession) -> GrillSession:
    s = WF.review(s)
    s = WF.request_confirmation(s, accept_unresolved=bool(s.warning_findings))
    return WF.confirm(s)


# --- States ------------------------------------------------------------------------------------------

def test_each_state():
    s = started()
    states = question_states(s)
    assert set(states.values()) == {ClarificationState.OPEN}
    s = WF.answer(s, "The photo appears on the profile page.")  # REQ-2 expected result
    s = WF.answer(s, "", AnswerStatus.UNKNOWN)  # REQ-2 error handling
    s = with_answer(s, "ai.req.a", ["REQ-1"], "Only letters and digits", AnswerStatus.ASSUMED)
    s = with_answer(s, "ai.req.b", ["REQ-1"], TEN)
    assert s.current_question.id.startswith("conflict.")  # the contradiction is asked next
    states = question_states(s)
    assert states["rule.missing_expected_result.REQ-2"] == ClarificationState.CONFIRMED
    assert states["rule.missing_error_handling.REQ-2"] == ClarificationState.UNKNOWN
    assert states["ai.req.a"] == ClarificationState.ASSUMPTION
    assert states["ai.req.b"] == ClarificationState.CONFLICT


# --- Detection -------------------------------------------------------------------------------------------

def test_answer_contradicting_its_requirement_is_a_conflict_and_is_asked_next():
    s = with_answer(started(), "ai.req.min", ["REQ-1"], TEN)
    [conflict] = unresolved_conflicts(s)
    assert conflict.kind == ConflictKind.REQUIREMENT and conflict.requirement_ids == ["REQ-1"]
    assert conflict.statements == ["REQ-1: The password must be at least 8 characters.", TEN]
    assert conflict.phrases == ["at least 10 characters", "at least 8 characters"]
    question = s.current_question
    assert question.id == conflict.id and question.priority == "high" and question.essential
    assert [c.value for c in question.choices] == conflict.statements  # offered verbatim, nothing chosen
    assert question.allow_free_text


def test_two_answers_that_disagree_are_a_conflict():
    s = with_answer(started(), "ai.req.a", ["REQ-2"], "Photos up to 5 MB are accepted; bigger ones are rejected.")
    s = with_answer(s, "ai.req.b", ["REQ-2"], "Photos may be at most 10 MB.")
    [conflict] = [c for c in unresolved_conflicts(s) if c.kind == ConflictKind.ANSWERS]
    assert conflict.question_ids == ["ai.req.a", "ai.req.b"] and conflict.requirement_ids == ["REQ-2"]


def test_agreeing_or_unrelated_answers_are_not_conflicts():
    s = with_answer(started(), "ai.req.a", ["REQ-1"], "Yes, at least 8 characters.")
    s = with_answer(s, "ai.req.b", ["REQ-2"], "Photos up to 5 MB; larger ones are rejected.")
    s = with_answer(s, "ai.req.c", ["REQ-1"], "At most 64 characters; longer ones are rejected.")  # a new limit
    assert detect_conflicts(s) == []


def test_unknown_and_skipped_answers_are_never_compared():
    s = with_answer(started(), "ai.req.min", ["REQ-1"], "", AnswerStatus.UNKNOWN)
    assert detect_conflicts(s) == []


def test_source_contradiction_choice_does_not_raise_a_new_conflict():
    s = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=SOURCE_CONFLICT))
    [conflict] = detect_conflicts(s)
    assert conflict.kind == ConflictKind.SOURCE and not conflict.resolved
    s = WF.answer(s, "REQ-1: The password must be at least 8 characters.")  # differs from REQ-2, on purpose
    [conflict] = detect_conflicts(s)
    assert conflict.resolved and conflict.resolution.startswith("REQ-1")
    assert s.step == GrillStep.SHOW_DRAFT  # no endless "which is correct?" loop


def test_test_case_field_conflicting_with_the_linked_requirement():
    s = WF.submit_input(WF.start(GrillKind.TEST_CASE, GrillMode.INTERVIEW, context_requirements=REQS), TestCaseDraft())
    s = WF.answer(s, "REQ-1")
    while s.current_question_id != "tc.expected_result":
        q = s.current_question
        s = WF.answer(s, "negative") if q.id == "tc.test_type" else (
            WF.answer(s, "Enter a password and submit") if q.essential else WF.skip(s))
    s = WF.answer(s, "Passwords shorter than at least 10 characters are rejected")
    [conflict] = unresolved_conflicts(s)
    assert conflict.field == "expected_result" and s.current_question_id == conflict.id
    assert not s.current_question.choices  # the user writes the correct value
    s = WF.answer(s, "Passwords shorter than 8 characters are rejected")
    assert unresolved_conflicts(s) == [] and s.draft.expected_result.endswith("8 characters are rejected")


# --- Resolution --------------------------------------------------------------------------------------------

def test_choosing_the_requirement_resolves_and_supersedes_the_answer():
    s = with_answer(started(), "ai.req.min", ["REQ-1"], TEN)
    conflict_id = s.current_question_id
    s = WF.answer(s, "REQ-1: The password must be at least 8 characters.")
    [conflict] = detect_conflicts(s)
    assert conflict.resolved and conflict.resolution.startswith("REQ-1")
    assert superseded_questions(s) == {"ai.req.min"}
    assert question_state(s, s.question("ai.req.min")) == ClarificationState.CONFIRMED  # no longer contested
    assert s.answers[conflict_id].status == AnswerStatus.ANSWERED


def test_unknown_leaves_the_conflict_open_and_review_warns():
    s = with_answer(started(), "ai.req.min", ["REQ-1"], TEN)
    s = WF.answer(s, "", AnswerStatus.UNKNOWN)
    assert len(unresolved_conflicts(s)) == 1
    findings = deterministic_review(s)
    conflict_findings = [f for f in findings if f.message_key == "grill.check.answer_conflict"]
    assert len(conflict_findings) == 1 and conflict_findings[0].requirement_ids == ["REQ-1"]
    assert conflict_findings[0].level.value == "warning"  # must be fixed or explicitly accepted
    assert not any(f.message_key == "grill.check.question_open" and f.params.get("question", "").startswith("conflict.")
                   for f in findings)  # reported once, not also as an open question


def test_resolved_conflict_needs_no_acceptance():
    s = with_answer(started(), "ai.req.min", ["REQ-1"], TEN)
    s = WF.answer(s, TEN)  # the author keeps the stricter rule: a decision, not a guess
    assert not any(f.message_key == "grill.check.answer_conflict" for f in deterministic_review(s))


# --- Report ---------------------------------------------------------------------------------------------------------

def test_report_lists_contradictions_and_keeps_contested_answers_out_of_decisions():
    open_case = finalize(with_answer(started(), "ai.req.min", ["REQ-1"], TEN))
    report = build_report(open_case)
    assert [(c.resolved, c.statements[1]) for c in report.contradictions] == [(False, TEN)]
    assert TEN not in [i.text for i in report.confirmed]  # contested: not a decision
    assert "Unresolved" in report_markdown(report)

    s = with_answer(started(), "ai.req.min", ["REQ-1"], TEN)
    s = WF.answer(s, "REQ-1: The password must be at least 8 characters.")
    report = build_report(finalize(s))
    [item] = report.contradictions
    assert item.resolved and item.resolution.startswith("REQ-1")
    decisions = [i.text for i in report.confirmed]
    assert TEN not in decisions  # superseded
    assert "REQ-1: The password must be at least 8 characters." in decisions  # the decision itself
    text = report_markdown(report)
    contradictions = text.split("## Contradictions")[1].split("## ")[0]
    assert "Resolved: REQ-1" in contradictions and TEN in contradictions


def test_source_contradictions_are_reported():
    s = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=SOURCE_CONFLICT))
    s = WF.answer(s, "", AnswerStatus.UNKNOWN)
    report = build_report(finalize(s))
    [item] = report.contradictions
    assert item.kind == ConflictKind.SOURCE and not item.resolved
    assert item.statements == [f"{r.id}: {r.text}" for r in SOURCE_CONFLICT]


# --- Workspace hand-over ------------------------------------------------------------------------------------

def test_contradicted_or_overruled_clarifications_never_resolve_findings():
    from spec_to_test.grill.integration import resolutions
    from spec_to_test.models import Workspace
    from spec_to_test.rule_engine import analyze_requirements

    photo = [Requirement(id="REQ-3", text="Users can upload a profile photo of at most 5 MB.")]
    workspace = Workspace(requirements=photo, findings=analyze_requirements(photo).findings)
    answer = "Photos of at most 10 MB appear on the profile page."

    def session_with(decision: str | None) -> GrillSession:
        s = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=photo))
        s = WF.answer(s, answer)
        if decision is None:
            s = WF.answer(s, "", AnswerStatus.UNKNOWN)
        else:
            s = WF.answer(s, decision)
        while s.step == GrillStep.ASK_QUESTION:
            s = WF.skip(s) if not s.current_question.essential else WF.answer(s, "", AnswerStatus.UNKNOWN)
        return finalize(s)

    def resolvable(s: GrillSession) -> set[str]:
        return {r.question_id for r in resolutions(s, workspace)}

    expected_id = "rule.missing_expected_result.REQ-3"
    assert expected_id not in resolvable(session_with(None))  # still contradicted
    assert expected_id not in resolvable(session_with("REQ-3: " + photo[0].text))  # overruled
    assert expected_id in resolvable(session_with(answer))  # the author kept it: a decision
