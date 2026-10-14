"""Adaptive Grill: risk-ranked questions, findings resolved earlier are not asked again,
and AI questions carry their model and never repeat a settled question."""

import json
from types import SimpleNamespace

from pydantic import SecretStr

from spec_to_test.grill import ai as grill_ai
from spec_to_test.grill.ai import AIInterviewQuestions
from spec_to_test.grill.models import GrillKind, Question, RequirementsDraft
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.grill.planner import question_risk
from spec_to_test.input_parser import extract_requirements
from spec_to_test.llm.config import AIConfig
from spec_to_test.models import Finding, FindingType, Severity, Source

REQS = extract_requirements("""REQ-1: The page should load fast.
REQ-2: The password must be at least 8 characters.
REQ-3: Users can reset their password via email etc.
REQ-4: The password must be at least 10 characters.""")


class Model:
    def __init__(self, *questions):
        self.reply = AIInterviewQuestions.model_validate({"questions": list(questions)})
        self.calls = []
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=self.reply)

    def factory(self, config):
        return self


def config() -> AIConfig:
    return AIConfig(provider="anthropic", model="model-x", api_key=SecretStr("not-a-real-key"))


def session(settled: list[str] | None = None):
    return WF.submit_input(
        WF.start(GrillKind.REQUIREMENTS, settled_question_ids=settled), RequirementsDraft(requirements=REQS)
    )


def test_risk_combines_severity_quality_and_spread():
    finding = Finding(requirement_id="REQ-1", type=FindingType.AMBIGUOUS_WORDING, severity=Severity.MEDIUM)
    assert question_risk(finding, 100) == 30
    assert question_risk(finding, 50) == 50
    paired = finding.model_copy(update={"severity": Severity.HIGH, "related_requirement_ids": ["REQ-2"]})
    assert question_risk(paired, 0) == 100  # capped


def test_riskier_questions_come_first_within_a_priority():
    s = session()
    ranked = []
    while s.pending_questions:
        current = s.current_question
        ranked.append((current.priority, current.risk, current.id))
        s = WF.skip(s) if not current.essential else WF.answer(s, "", "unknown")
    priorities = [p for p, _, _ in ranked]
    assert priorities == sorted(priorities, key=["high", "medium", "low"].index)
    for level in ("high", "medium"):
        risks = [r for p, r, qid in ranked if p == level and not qid.startswith("rule.contradiction")]
        assert risks == sorted(risks, reverse=True), ranked


def test_findings_resolved_before_are_not_asked_again():
    settled = ["rule.contradiction.REQ-2+REQ-4", "rule.ambiguous_wording.REQ-1"]
    s = session(settled)
    asked = {q.id for q in s.questions}
    assert not asked & set(settled)
    assert "rule.ambiguous_wording.REQ-3" in asked  # other findings are still asked
    assert s.settled_question_ids == sorted(settled)


def test_ai_does_not_repeat_a_settled_question_and_records_its_model():
    s = session(["rule.ambiguous_wording.REQ-1"])
    model = Model(
        {"field": "", "requirement_ids": ["REQ-1"], "question": 'What measurable criteria replace: "fast"?',
         "reason": "Already settled.", "importance": "medium"},
        {"field": "", "requirement_ids": ["REQ-3"], "question": "Which channels besides email can be used?",
         "reason": "The scope of the reset flow.", "importance": "medium"},
    )
    question = grill_ai.next_question(s, config(), True, client_factory=model.factory)
    assert question is not None and question.prompt_text.startswith("Which channels")
    assert question.ai_model == "model-x" and question.origin == Source.AI
    payload = json.loads(model.calls[0]["messages"][-1]["content"].split("<grill>\n", 1)[1].rsplit("\n</grill>", 1)[0])
    assert 'What measurable criteria replace: "fast"?' in payload["already_asked"]


def test_on_response_sees_the_raw_reply_but_cannot_change_the_result():
    s = session()
    seen = []
    model = Model({"field": "", "requirement_ids": ["REQ-99"], "question": "Invented?", "reason": "-",
                   "importance": "low"})
    assert grill_ai.next_question(s, config(), True, client_factory=model.factory, on_response=seen.append) is None
    assert len(seen) == 1 and seen[0].questions[0].requirement_ids == ["REQ-99"]


def test_merged_ai_question_keeps_its_model_in_the_session():
    s = session()
    question = Question(id="ai.req.1", prompt_text="Which channels besides email?", requirement_ids=["REQ-3"],
                        origin=Source.AI, ai_model="model-x", importance="low")
    merged = WF.merge_questions(s, [question])
    assert merged.question("ai.req.1").ai_model == "model-x"
    assert merged.current_question_id != "ai.req.1"  # a low-priority AI question does not jump the queue
