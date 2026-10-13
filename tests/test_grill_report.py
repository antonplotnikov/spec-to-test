"""Final Grill report: confirmed facts, assumptions and unknowns stay apart; test cases trace to sources."""

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from spec_to_test.grill import ai as grill_ai
from spec_to_test.grill.ai import AITestCases, suggest_test_cases, to_test_cases
from spec_to_test.grill.integration import IntegrationError
from spec_to_test.grill.models import (
    AnswerStatus,
    GrillKind,
    GrillMode,
    GrillSession,
    GrillStep,
    Question,
    RequirementsDraft,
    TestCaseDraft,
)
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.grill.report import Basis, build_report, report_markdown
from spec_to_test.i18n import LANGUAGES
from spec_to_test.llm.config import AIConfig
from spec_to_test.llm.providers import AIError
from spec_to_test.models import Requirement, Source

FAKE_KEY = "test-key-123"
REQS = [
    Requirement(id="REQ-1", text="The page should load fast."),
    Requirement(id="REQ-2", text="The password must be at least 8 characters."),
    Requirement(id="REQ-3", text="Users can reset their password via email etc."),
]
CONFIRMED = "The page is interactive within 2 seconds on 4G."
ASSUMED = "Passwords longer than 64 characters are rejected"


def finalize(session: GrillSession) -> GrillSession:
    session = WF.review(session)
    session = WF.request_confirmation(session, accept_unresolved=bool(session.warning_findings))
    session = WF.confirm(session)
    assert session.step == GrillStep.FINALIZED
    return session


def requirements_session(final: bool = True) -> GrillSession:
    """Built-in questions: confirmed, skipped, unknown; one AI question answered as an assumption."""
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=REQS))
    session = WF.answer(session, "", AnswerStatus.UNKNOWN)  # REQ-3 expected result (high, asked first)
    session = WF.skip(session)  # REQ-3 wording (riskier than REQ-1's, so asked first)
    session = WF.answer(session, CONFIRMED)  # REQ-1 wording
    session = WF.add_questions(session, [Question(
        id="ai.req.max", prompt_text="Is there a maximum password length?", requirement_ids=["REQ-2"],
        origin=Source.AI, importance="high",
    )])
    session = WF.answer(session, ASSUMED, AnswerStatus.ASSUMED)
    return finalize(session) if final else session


def tc_session(requirement_id: str = "REQ-2") -> GrillSession:
    draft = TestCaseDraft(
        requirement_id=requirement_id, feature="" if requirement_id else "Sign-up",
        title="Short password is rejected", test_type="negative",
        preconditions=["The sign-up page is open"], steps=["Enter a 7-character password", "Submit"],
        expected_result="The password is rejected",
    )
    session = WF.submit_input(
        WF.start(GrillKind.TEST_CASE, GrillMode.REVIEW_DRAFT, context_requirements=REQS), draft,
    )
    while session.step == GrillStep.ASK_QUESTION:
        question = session.current_question
        if question.field == "objective":
            session = WF.answer(session, "Check the minimum length", AnswerStatus.ASSUMED)
        elif question.essential:
            session = WF.answer(session, "", AnswerStatus.UNKNOWN)
        else:
            session = WF.skip(session)
    return finalize(session)


# --- Facts, assumptions, unknowns -------------------------------------------------------------------

def test_requirements_report_keeps_the_three_kinds_apart():
    report = build_report(requirements_session())
    assert [(i.text, i.origin, i.requirement_ids) for i in report.confirmed] == [(CONFIRMED, "user_confirmed", ["REQ-1"])]
    assert [(i.text, i.origin, i.requirement_ids) for i in report.assumptions] == [(ASSUMED, "assumption", ["REQ-2"])]
    assert sorted(i.origin for i in report.unknowns) == ["skipped", "unknown"]
    assert all(i.requirement_ids == ["REQ-3"] for i in report.unknowns)
    assert report.confirmed[0].where  # the question it answers


def test_nothing_is_invented_for_unknown_or_skipped_questions():
    session = requirements_session()
    assert {s.text for s in session.draft.statements} == {CONFIRMED, ASSUMED}  # no text for REQ-3
    report = build_report(session)
    by_id = {r.id: r for r in report.clarified_requirements}
    assert by_id["REQ-1"].confirmed == [CONFIRMED] and by_id["REQ-1"].assumed == []
    assert by_id["REQ-2"].assumed == [ASSUMED] and by_id["REQ-2"].confirmed == []
    assert by_id["REQ-3"].confirmed == [] and len(by_id["REQ-3"].open) == 2
    assert [r.text for r in report.clarified_requirements] == [r.text for r in REQS]  # verbatim


def test_report_needs_a_confirmed_session():
    with pytest.raises(IntegrationError) as err:
        build_report(requirements_session(final=False))
    assert err.value.code == "not_finalized"


def test_test_case_report_uses_field_provenance():
    report = build_report(tc_session())
    confirmed = {i.where: i.origin for i in report.confirmed}
    assert confirmed["Title"] == "source" and confirmed["Expected result"] == "source"
    assert [(i.where, i.text) for i in report.assumptions] == [("Objective", "Check the minimum length")]
    assert "Objective" not in confirmed
    assert [r.id for r in report.clarified_requirements] == ["REQ-2"]


# --- Suggested test cases ----------------------------------------------------------------------------

def test_rule_based_test_cases_trace_to_the_requirements():
    report = build_report(requirements_session())
    assert report.suggested_tests
    assert {rid for case in report.suggested_tests for rid in case.requirement_ids} == {"REQ-1", "REQ-2", "REQ-3"}
    assert all(c.origin == Source.RULE and c.basis == Basis.REQUIREMENT and c.steps for c in report.suggested_tests)


def test_test_case_report_suggests_only_for_the_linked_requirement():
    cases = build_report(tc_session()).suggested_tests
    assert cases and {rid for c in cases for rid in c.requirement_ids} == {"REQ-2"}


def test_no_link_means_no_suggested_test_cases():
    assert build_report(tc_session(requirement_id="")).suggested_tests == []


def ai_case(**overrides) -> dict:
    case = {
        "title": "Password of exactly 8 characters is accepted", "requirement_ids": ["REQ-2"],
        "test_type": "boundary", "preconditions": [], "steps": ["Enter an 8-character password", "Submit"],
        "expected_result": "The password is accepted", "basis_quote": "at least 8 characters",
    }
    return {**case, **overrides}


def test_ai_test_case_basis_is_decided_from_the_quote_not_by_the_model():
    session = requirements_session()
    response = AITestCases.model_validate({"test_cases": [
        ai_case(),
        ai_case(title="Fast load", requirement_ids=["REQ-1"], basis_quote="within 2 seconds on 4g"),
        ai_case(title="65 characters rejected", basis_quote="longer than 64 characters"),
        ai_case(title="Invented limit", basis_quote="at most 128 characters"),  # nowhere in the input
        ai_case(title="Invented requirement", requirement_ids=["REQ-99"]),
        ai_case(title="No steps", steps=["  "]),
        ai_case(title="Empty quote", basis_quote=""),
        ai_case(title="password of exactly 8 characters is ACCEPTED"),  # duplicate title
    ]})
    cases = to_test_cases(response, session)
    assert [(c.title, c.basis) for c in cases] == [
        ("Password of exactly 8 characters is accepted", Basis.REQUIREMENT),
        ("Fast load", Basis.CONFIRMED),
        ("65 characters rejected", Basis.ASSUMPTION),
    ]
    assert all(c.origin == Source.AI for c in cases)


class FakeModel:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=self.reply)


def config() -> AIConfig:
    return AIConfig(provider="anthropic", model="test-model", api_key=SecretStr(FAKE_KEY))


def test_ai_test_cases_need_consent_and_a_requirement():
    model = FakeModel(AITestCases(test_cases=[]))
    with pytest.raises(AIError) as err:
        suggest_test_cases(requirements_session(), config(), consent=False, client_factory=lambda c: model)
    assert err.value.code == "consent_required"
    assert suggest_test_cases(tc_session(""), config(), True, client_factory=lambda c: model) == []
    assert model.calls == []


def test_ai_test_cases_prompt_forbids_guessing():
    model = FakeModel(AITestCases.model_validate({"test_cases": [ai_case()]}))
    cases = suggest_test_cases(requirements_session(), config(), True, lang="ru", client_factory=lambda c: model)
    assert len(cases) == 1
    system = model.calls[0]["system"]
    assert "do not write that test case" in system and "Do not invent" in system and "Russian" in system
    assert model.calls[0]["output_format"] is AITestCases


def test_ai_test_cases_are_added_after_the_rule_based_ones():
    session = requirements_session()
    ai = to_test_cases(AITestCases.model_validate({"test_cases": [ai_case()]}), session)
    report = build_report(session, ai_tests=ai)
    assert report.suggested_tests[-1].origin == Source.AI
    assert sum(c.origin == Source.AI for c in report.suggested_tests) == 1


# --- Markdown ---------------------------------------------------------------------------------------------------

def test_markdown_has_every_section_in_order():
    session = requirements_session()
    ai = to_test_cases(AITestCases.model_validate({"test_cases": [ai_case()]}), session)
    text = report_markdown(build_report(session, ai_tests=ai))
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Clarified requirements", "## Confirmed decisions", "## Assumptions (not confirmed)",
        "## Unresolved questions", "## Contradictions", "## Review findings accepted as unresolved",
        "## Suggested test scenarios",
    ]
    confirmed = text.split("## Confirmed decisions")[1].split("## Assumptions")[0]
    assumptions = text.split("## Assumptions (not confirmed)")[1].split("## Unresolved")[0]
    assert CONFIRMED in confirmed and ASSUMED not in confirmed
    assert ASSUMED in assumptions and CONFIRMED not in assumptions
    assert "Boundary values · Requirement · AI suggestion" in text
    assert "Based on: “at least 8 characters”" in text


def test_markdown_escapes_user_text():
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=REQS))
    session = WF.answer(session, "**bold** | <script>")
    session = WF.skip(session)
    session = WF.answer(session, "", AnswerStatus.UNKNOWN)
    text = report_markdown(build_report(finalize(session)))
    assert "**bold**" not in text and "<script>" not in text


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_markdown_is_translated(lang):
    text = report_markdown(build_report(requirements_session(), lang), lang)
    assert "grill.report." not in text and "grill.provenance." not in text and "grill.answer_status." not in text


def test_report_lists_the_ai_interviewer_questions_like_any_other():
    report = build_report(requirements_session())
    assert grill_ai.MAX_INTERVIEW_QUESTIONS > 0
    assert report.assumptions[0].where == "Is there a maximum password length?"
