"""What the Grill page shows beside the interview: derived from the session, never invented."""

from spec_to_test.grill.inputs import requirements_draft
from spec_to_test.grill.insights import (
    assumed_answers,
    focus_requirement,
    group_findings,
    interview_counts,
    question_category,
    related_requirements,
    scope_findings,
    session_requirements,
    unresolved,
)
from spec_to_test.grill.models import AnswerStatus, GrillKind, GrillMode, Question, Source
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.models import ClarificationStatus, Workspace
from spec_to_test.rule_engine import analyze_requirements

TEXT = """REQ-1: The password must be at least 8 characters.
REQ-2: The password must be at least 10 characters.
REQ-3: The page should load fast."""


def session():
    started = WF.start(GrillKind.REQUIREMENTS, GrillMode.INTERVIEW, None)
    return WF.submit_input(started, requirements_draft(TEXT), TEXT)


def test_requirements_and_rule_findings_come_from_the_session():
    s = session()
    assert [r.id for r in session_requirements(s)] == ["REQ-1", "REQ-2", "REQ-3"]
    groups = group_findings(scope_findings(s, None))
    assert [f.requirement_id for f in groups.ambiguities] == ["REQ-3"]
    assert len(groups.contradictions) == 1  # reported on both sides, listed once


def test_the_analyzed_workspace_is_used_when_it_holds_the_same_requirements():
    s = session()
    result = analyze_requirements(session_requirements(s))
    for finding in result.findings:
        finding.status = ClarificationStatus.RESOLVED
    workspace = Workspace(requirements=result.requirements, findings=result.findings)
    assert group_findings(scope_findings(s, workspace)).ambiguities == []  # resolved there, so not open
    other = Workspace(requirements=[r.model_copy(update={"text": "changed"}) for r in result.requirements])
    assert group_findings(scope_findings(s, other)).ambiguities  # different text: the rules run again


def test_question_categories():
    def q(qid: str, **kw) -> Question:
        return Question(id=qid, prompt_text="?", **kw)

    assert question_category(q("rule.contradiction.REQ-1+REQ-2")) == "contradiction"
    assert question_category(q("conflict.abc")) == "contradiction"
    assert question_category(q("rule.ambiguous_wording.REQ-3")) == "ambiguous_wording"
    assert question_category(q("followup.vague.rule.x")) == "clarity"
    assert question_category(q("followup.limit.rule.x")) == "boundary"
    assert question_category(q("ai.1", origin=Source.AI)) == "ai"
    assert question_category(q("tc.steps", field="steps")) == "field"


def test_focus_and_related_requirements():
    s = session()
    question = s.current_question
    assert question is not None and question.id.startswith("rule.contradiction.")
    focus = focus_requirement(s, question)
    assert focus is not None and focus.id == "REQ-1"
    related = related_requirements(s, "REQ-1", scope_findings(s, None))
    assert [r.id for r in related] == ["REQ-2"]
    assert related_requirements(s, "REQ-3", scope_findings(s, None)) == []


def test_assumptions_are_counted_apart_from_confirmed_answers():
    s = session()
    s = WF.answer(s, "REQ-1: The password must be at least 8 characters.", AnswerStatus.ASSUMED,
                  expected_revision=s.revision)
    counts = interview_counts(s)
    assert (counts.confirmed, counts.assumptions) == (0, 1)
    assert [value for _, value in assumed_answers(s)] == ["REQ-1: The password must be at least 8 characters."]
    assert counts.conflicts == 0  # the source contradiction is decided, as an assumption
    s = WF.answer(s, "", AnswerStatus.UNKNOWN, expected_revision=s.revision)
    assert interview_counts(s).unknowns == 1
    waiting = unresolved(s)
    assert waiting and all(q.id in {x.id for x in s.questions} for q in waiting)
    assert [q.rank for q in waiting] == sorted(q.rank for q in waiting)
