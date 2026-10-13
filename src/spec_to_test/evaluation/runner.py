"""Run evaluation cases through the real Grill pipeline and measure the AI's quality.

Each case runs a Requirements Grill exactly as the page does: the built-in
planner, the AI interviewer after every answer (one question, merged into the
same ranked queue), the deterministic and AI reviews, and the final test case
suggestions. The author is scripted (cases.py); the model is either scripted
(`ScriptedModel`, deterministic, used in CI) or real (`--live`, optional).

Metrics (ratios keep their numerator and denominator, so cases add up exactly):

- relevance               asked questions that address a gold issue / asked questions
- duplication             asked questions repeating an earlier one about the same requirement / asked
- coverage                gold issues addressed by at least one asked question / gold issues
- resolved_reasked        asked questions whose finding was resolved in the document at that moment
                          (before the interview, or by a `steps` change during it) / asked
- false_positive_rate     `must_not_ask` traps that an asked question fell into / traps
- contradiction_recall    gold contradicting pairs the rule engine reports / gold pairs
- contradiction_precision reported contradicting pairs that are gold pairs / reported pairs (a pair in
                          `non_contradictions`, or any pair a person did not judge contradictory, counts
                          against it)
- hallucination_raw       model items with an invented requirement ID, a number that is not in the
                          input, or a quote/basis the input does not contain / model items
- hallucination_accepted  the same check on what passed the trust filters / accepted AI items
- test_case_quality       quality checks passed / checks run, over suggested test cases (rule-based
                          and accepted AI): steps, expected result, a real requirement, a traceable
                          basis, and no number that is neither in the input nor derived by the
                          built-in test design (boundary values, equivalence class representatives)
- test_coverage           requirements with at least one suggested test case / requirements
- invented_requirements   requirement IDs in the result (decision trace, findings, test cases) that the
                          document does not contain (a count)
- ai_errors               failed model calls (a count); the interview must go on without them
- invented_values         numbers in the clarified draft that neither the document nor an answer
                          contains (a count; the interview must never make up a value)
- progress_regressions    times the number of handled questions went down during the interview (a
                          count; reactive updates must not reset progress)
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from spec_to_test.grill import ai as grill_ai
from spec_to_test.grill.insights import question_category
from spec_to_test.grill.models import AnswerStatus, GrillKind, GrillSession, GrillStep, Question, RequirementsDraft
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.grill.report import Basis, SuggestedTestCase, fact_texts, rule_based_tests
from spec_to_test.grill.rules import boundary_hints, numbers_in, requirement_findings
from spec_to_test.grill.text import render_question
from spec_to_test.grill.trace import decision_records
from spec_to_test.grill.workflow import GrillError
from spec_to_test.input_parser import extract_requirements
from spec_to_test.llm.config import AIConfig
from spec_to_test.llm.providers import AIError
from spec_to_test.models import FindingType, Requirement, Source
from spec_to_test.test_design import design_tests, format_value

from .cases import FIXTURES_DIR, EvalCase, load_cases
from .scripted import ScriptedModel, scripted_config

MAX_TURNS = 60  # questions per case; a safety stop, never reached by a healthy interview
THRESHOLDS_FILE = FIXTURES_DIR.parent / "thresholds.json"
# Metrics where higher is better (the others are rates or counts to keep low).
HIGHER_IS_BETTER = frozenset({
    "relevance", "coverage", "test_case_quality", "test_coverage", "contradiction_recall", "contradiction_precision",
})
RATIOS = ("relevance", "duplication", "coverage", "resolved_reasked", "false_positive_rate",
          "contradiction_recall", "contradiction_precision", "hallucination_raw",
          "hallucination_accepted", "test_case_quality", "test_coverage")
COUNTS = ("invented_requirements", "invented_values", "progress_regressions", "ai_errors", "questions_asked",
          "ai_questions_asked")
ClientFactory = Callable[[AIConfig], Any]


@dataclass
class Ratio:
    num: int = 0
    den: int = 0

    @property
    def value(self) -> float | None:
        return round(self.num / self.den, 4) if self.den else None

    def add(self, hit: bool) -> None:
        self.num += int(hit)
        self.den += 1


class AskedQuestion(BaseModel):
    id: str
    prompt: str
    origin: str
    category: str
    requirement_ids: list[str]
    relevant: bool = False
    duplicate: bool = False
    # Its finding was resolved in the document when it was asked.
    settled: bool = False
    false_positive: bool = False


@dataclass
class CaseResult:
    name: str
    mode: str
    ratios: dict[str, Ratio] = field(default_factory=lambda: {name: Ratio() for name in RATIOS})
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COUNTS, 0))
    asked: list[AskedQuestion] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    hallucinations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    contradiction_misses: list[str] = field(default_factory=list)

    def metrics(self) -> dict[str, float | int | None]:
        return {**{k: r.value for k, r in self.ratios.items()}, **self.counts}


@dataclass
class SuiteResult:
    mode: str
    cases: list[CaseResult]

    def totals(self) -> dict[str, float | int | None]:
        ratios = {name: Ratio() for name in RATIOS}
        counts = dict.fromkeys(COUNTS, 0)
        for case in self.cases:
            for name, ratio in case.ratios.items():
                ratios[name].num += ratio.num
                ratios[name].den += ratio.den
            for name, count in case.counts.items():
                counts[name] += count
        return {**{k: r.value for k, r in ratios.items()}, **counts}

    def to_data(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "totals": self.totals(),
            "cases": [
                {
                    "name": c.name, "metrics": c.metrics(), "uncovered": c.uncovered,
                    "hallucinations": c.hallucinations, "errors": c.errors, "false_positives": c.false_positives,
                    "contradiction_misses": c.contradiction_misses,
                    "asked": [q.model_dump() for q in c.asked],
                }
                for c in self.cases
            ],
        }

    def to_markdown(self, failures: list[str] | None = None) -> str:
        def fmt(value: float | int | None) -> str:
            return "—" if value is None else (f"{value:.2f}" if isinstance(value, float) else str(value))

        names = [*RATIOS, *COUNTS]
        out = [f"# Grill AI evaluation ({self.mode})", "", "| Case | " + " | ".join(names) + " |",
               "|" + "---|" * (len(names) + 1)]
        for case in self.cases:
            metrics = case.metrics()
            out.append(f"| {case.name} | " + " | ".join(fmt(metrics[n]) for n in names) + " |")
        totals = self.totals()
        out.append("| **total** | " + " | ".join(fmt(totals[n]) for n in names) + " |")
        for case in self.cases:
            if case.uncovered or case.hallucinations or case.errors or case.false_positives or case.contradiction_misses:
                out += ["", f"## {case.name}"]
                out += [f"- not covered: {item}" for item in case.uncovered]
                out += [f"- false positive: {item}" for item in case.false_positives]
                out += [f"- contradiction: {item}" for item in case.contradiction_misses]
                out += [f"- caught hallucination: {item}" for item in case.hallucinations]
                out += [f"- model error: {item}" for item in case.errors]
        if failures is not None:
            out += ["", "## Thresholds", ""]
            out += [f"- FAILED {f}" for f in failures] or ["- all thresholds met"]
        return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _strip_ids(text: str, ids: set[str]) -> str:
    for requirement_id in sorted(ids, key=len, reverse=True):
        text = text.replace(requirement_id, " ")
    return text


def _quote_in(quote: str, texts: list[str]) -> bool:
    needle = " ".join(quote.split()).casefold()
    return bool(needle) and any(needle in " ".join(text.split()).casefold() for text in texts)


def _invented_number(text: str, allowed: set[str], ids: set[str]) -> bool:
    return bool(numbers_in(_strip_ids(text, ids)) - allowed)


def _derived_numbers(requirements: list[Requirement]) -> set[str]:
    """Values the built-in test design derives from stated limits (boundaries, class representatives)."""
    numbers = {value for r in requirements for _, values in boundary_hints(r) for value in values}
    for requirement in requirements:
        for classes in design_tests(requirement).partitions:
            numbers |= {format_value(part.representative) for part in classes.partitions}
    return numbers


class _Context:
    """What the input contains at the moment a model reply is checked."""

    def __init__(self, session: GrillSession, requirements: list[Requirement]) -> None:
        self.ids = {r.id for r in requirements}
        self.texts = grill_ai.input_texts(session)
        self.numbers = numbers_in("\n".join(self.texts))
        self.requirements = {r.id: r for r in requirements}

    def allowed_numbers(self, case: SuggestedTestCase) -> set[str]:
        """Input numbers; for a rule-based test also the values the test design derived from its requirement."""
        if case.origin != Source.RULE:
            return self.numbers
        return self.numbers | _derived_numbers([self.requirements[i] for i in case.requirement_ids if i in self.requirements])


def raw_problem(kind: str, item: Any, ctx: _Context) -> str:
    """Why a raw model item is a hallucination ("" if it is not)."""
    ids = [i.strip() for i in getattr(item, "requirement_ids", [])]
    if unknown := [i for i in ids if i not in ctx.ids]:
        return f"invented requirement {', '.join(unknown)}"
    if kind in ("interview", "questions") and _invented_number(item.question, ctx.numbers, ctx.ids):
        return f"number not in the input: {item.question}"
    if kind == "review" and item.quote.strip() and not _quote_in(item.quote, ctx.texts):
        return f"quote not in the input: {item.quote}"
    if kind == "test_cases":
        if not ids:
            return f"test case without a requirement: {item.title}"
        if not _quote_in(item.basis_quote, ctx.texts):
            return f"basis not in the input: {item.basis_quote}"
        if _invented_number(item.expected_result, ctx.numbers, ctx.ids):
            return f"number not in the input: {item.expected_result}"
    return ""


def _accepted_question_problem(question: Question, ctx: _Context) -> str:
    if unknown := [i for i in question.requirement_ids if i not in ctx.ids]:
        return f"invented requirement {', '.join(unknown)}"
    if _invented_number(question.prompt_text, ctx.numbers, ctx.ids):
        return f"number not in the input: {question.prompt_text}"
    return ""


def case_quality_checks(case: SuggestedTestCase, ids: set[str], facts: list[str], allowed: set[str]) -> list[bool]:
    """Steps, expected result, real requirement, traceable basis, no invented number."""
    traceable = case.basis == Basis.REQUIREMENT and not case.basis_quote or _quote_in(case.basis_quote, facts)
    return [
        bool(case.steps),
        bool(case.expected_result.strip()),
        bool(case.requirement_ids) and all(i in ids for i in case.requirement_ids),
        traceable,
        not _invented_number(case.expected_result, allowed, ids),
    ]


def addresses(question: AskedQuestion, issue_ids: list[str], topics: list[str], keywords: list[str]) -> bool:
    if not set(question.requirement_ids) & set(issue_ids):
        return False
    text = question.prompt.casefold()
    return question.category in topics or any(k.casefold() in text for k in keywords)


# ---------------------------------------------------------------------------
# One case
# ---------------------------------------------------------------------------

def run_case(
    case: EvalCase,
    *,
    use_ai: bool = True,
    config: AIConfig | None = None,
    client_factory: ClientFactory | None = None,
    mode: str = "scripted",
) -> CaseResult:
    """Run one case. Without `config`/`client_factory` the case's scripted replies are used."""
    lang = case.language
    if use_ai and client_factory is None:
        model = ScriptedModel(case.ai)
        config, client_factory = scripted_config(), model.factory
    result = CaseResult(name=case.name, mode=mode if use_ai else "rules")
    requirements = extract_requirements(case.requirements)
    known = {r.id for r in requirements}
    session = WF.submit_input(
        WF.start(GrillKind.REQUIREMENTS, settled_question_ids=case.settled), RequirementsDraft(requirements=requirements)
    )
    ai_questions: list[tuple[Question, _Context]] = []
    raw: list[tuple[str, Any, _Context]] = []
    settled = set(case.settled)
    steps = sorted(case.steps, key=lambda step: step.after)
    handled = 0

    def observer(kind: str, ctx: _Context) -> Callable[[BaseModel], None]:
        def observe(reply: BaseModel) -> None:
            items = getattr(reply, "questions", None) or getattr(reply, "findings", None) or getattr(reply, "test_cases", None) or []
            raw.extend((kind, item, ctx) for item in items)
        return observe

    def call(kind: str, fn: Callable[..., Any]) -> Any:
        ctx = _Context(session, requirements)
        try:
            return fn(session, config, True, lang, client_factory, on_response=observer(kind, ctx)), ctx
        except AIError as exc:
            result.counts["ai_errors"] += 1
            result.errors.append(f"{kind}: {exc.code}")
            return None, ctx

    last_fingerprint = None
    for _ in range(MAX_TURNS):
        while steps and steps[0].after <= len(session.answers):
            step = steps.pop(0)  # findings resolved or reopened in the document, as on the analysis page
            settled = (settled | set(step.resolve)) - set(step.reopen)
            session = WF.sync_settled(session, sorted(settled))
        if use_ai and grill_ai.wants_next_question(session):
            fingerprint = grill_ai.interview_fingerprint(session)
            if fingerprint != last_fingerprint:  # once per interview state, like the page
                last_fingerprint = fingerprint
                question, ctx = call("interview", grill_ai.next_question)
                if question is not None:
                    ai_questions.append((question, ctx))
                    try:
                        session = WF.merge_questions(session, [question])
                    except GrillError:
                        pass
        if session.step != GrillStep.ASK_QUESTION:
            break
        current = session.current_question
        assert current is not None
        prompt = render_question(current, lang)[0]
        result.asked.append(AskedQuestion(
            id=current.id, prompt=prompt, origin=current.origin.value, category=question_category(current),
            requirement_ids=list(current.requirement_ids), settled=current.id in settled,
        ))
        scripted = case.answer_for(current.id, prompt)
        status = scripted.status
        if status == AnswerStatus.SKIPPED and current.essential:
            status = AnswerStatus.UNKNOWN
        if status == AnswerStatus.SKIPPED:
            session = WF.skip(session)
        else:
            session = WF.answer(session, scripted.value, status)
        if session.progress[0] < handled:
            result.counts["progress_regressions"] += 1
        handled = session.progress[0]

    # Reviews and test case suggestions, as on the page.
    session = WF.review(session)
    findings = []
    if use_ai:
        found, _ = call("review", grill_ai.review_draft)
        findings = list(found or [])
        session = WF.add_ai_findings(session, findings)
    ai_tests: list[SuggestedTestCase] = []
    if use_ai:
        found, _ = call("test_cases", grill_ai.suggest_test_cases)
        ai_tests = list(found or [])
    tests = [*rule_based_tests(session, lang), *ai_tests]

    _score_questions(case, result)
    result.counts["ai_questions_asked"] = sum(q.origin == "ai" for q in result.asked)
    for kind, item, ctx in raw:
        problem = raw_problem(kind, item, ctx)
        result.ratios["hallucination_raw"].add(bool(problem))
        if problem:
            result.hallucinations.append(f"{kind}: {problem}")
    end = _Context(session, requirements)
    accepted_problems = [_accepted_question_problem(q, ctx) for q, ctx in ai_questions]
    accepted_problems += [
        "invented requirement" if any(i not in known for i in f.requirement_ids)
        else ("quote not in the input" if f.params.get("quote") and not _quote_in(f.params["quote"], end.texts) else "")
        for f in findings
    ]
    facts = [text for texts in fact_texts(session).values() for text in texts] + end.texts
    for test in ai_tests:
        accepted_problems.append("" if all(case_quality_checks(test, known, facts, end.numbers)) else "unsupported test case")
    for problem in accepted_problems:
        result.ratios["hallucination_accepted"].add(bool(problem))
    for test in tests:
        for passed in case_quality_checks(test, known, facts, end.allowed_numbers(test)):
            result.ratios["test_case_quality"].add(passed)
    tested = {i for test in tests for i in test.requirement_ids}
    for requirement in requirements:
        result.ratios["test_coverage"].add(requirement.id in tested)
    mentioned = {i for r in decision_records(session, lang) for i in r.requirement_ids}
    mentioned |= {i for f in session.findings for i in f.requirement_ids} | tested
    result.counts["invented_requirements"] = len(mentioned - known)
    said = numbers_in("\n".join([r.text for r in requirements] + [a.value for a in session.answers.values()]))
    if isinstance(session.draft, RequirementsDraft):
        for statement in session.draft.statements:
            result.counts["invented_values"] += len(numbers_in(_strip_ids(statement.text, known)) - said)
    _score_contradictions(case, requirements, result)
    return result


def _pair(ids: list[str]) -> frozenset[str]:
    return frozenset(i.strip() for i in ids)


def _score_contradictions(case: EvalCase, requirements: list[Requirement], result: CaseResult) -> None:
    """Contradicting pairs the rule engine reports, against the pairs a person judged."""
    reported = {
        _pair([f.requirement_id, *f.related_requirement_ids])
        for _, f in requirement_findings(requirements) if f.type == FindingType.CONTRADICTION
    }
    gold = {_pair(p) for p in case.gold.contradictions}
    not_gold = {_pair(p) for p in case.gold.non_contradictions}
    for pair in sorted(gold, key=sorted):
        result.ratios["contradiction_recall"].add(pair in reported)
        if pair not in reported:
            result.contradiction_misses.append(f"missed {' / '.join(sorted(pair))}")
    for pair in sorted(reported, key=sorted):
        result.ratios["contradiction_precision"].add(pair in gold)
        if pair not in gold:
            kind = "different context or equal value" if pair in not_gold else "not judged contradictory"
            result.contradiction_misses.append(f"false {' / '.join(sorted(pair))} ({kind})")


def _score_questions(case: EvalCase, result: CaseResult) -> None:
    earlier: list[AskedQuestion] = []
    for question in result.asked:
        same_scope = [
            q.prompt for q in earlier
            if set(q.requirement_ids) == set(question.requirement_ids) or set(q.requirement_ids) & set(question.requirement_ids)
        ]
        question.duplicate = any(q.id == question.id for q in earlier) or grill_ai.is_duplicate(question.prompt, same_scope)
        question.relevant = any(addresses(question, i.requirement_ids, i.topics, i.keywords) for i in case.gold.issues)
        result.ratios["duplication"].add(question.duplicate)
        result.ratios["relevance"].add(question.relevant)
        result.ratios["resolved_reasked"].add(question.settled)
        question.false_positive = any(
            addresses(question, trap.requirement_ids, trap.topics, trap.keywords) for trap in case.gold.must_not_ask
        )
        earlier.append(question)
    for trap in case.gold.must_not_ask:
        hits = [q for q in result.asked if addresses(q, trap.requirement_ids, trap.topics, trap.keywords)]
        result.ratios["false_positive_rate"].add(bool(hits))
        if hits:
            result.false_positives.append(f"{', '.join(trap.requirement_ids)}: {hits[0].prompt}")
    for issue in case.gold.issues:
        covered = any(addresses(q, issue.requirement_ids, issue.topics, issue.keywords) for q in result.asked)
        result.ratios["coverage"].add(covered)
        if not covered:
            result.uncovered.append(f"{', '.join(issue.requirement_ids)}: {issue.note or ', '.join(issue.topics)}")
    result.counts["questions_asked"] = len(result.asked)


# ---------------------------------------------------------------------------
# Suite and thresholds
# ---------------------------------------------------------------------------

def run_suite(
    cases: list[EvalCase] | None = None,
    *,
    use_ai: bool = True,
    config: AIConfig | None = None,
    client_factory: ClientFactory | None = None,
    mode: str = "scripted",
) -> SuiteResult:
    cases = cases if cases is not None else load_cases()
    results = [
        run_case(case, use_ai=use_ai, config=config, client_factory=client_factory, mode=mode) for case in cases
    ]
    return SuiteResult(mode=mode if use_ai else "rules", cases=results)


def load_thresholds(path: Path = THRESHOLDS_FILE) -> dict[str, dict[str, dict[str, float]]]:
    data: dict[str, dict[str, dict[str, float]]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def check_thresholds(result: SuiteResult, thresholds: dict[str, dict[str, float]]) -> list[str]:
    """Threshold violations as readable lines ([] = all met). A metric with no data is not checked."""
    totals = result.totals()
    failures = []
    for name, limits in thresholds.items():
        value = totals.get(name)
        if value is None:
            continue
        if "min" in limits and value < limits["min"]:
            failures.append(f"{name} = {value} < {limits['min']}")
        if "max" in limits and value > limits["max"]:
            failures.append(f"{name} = {value} > {limits['max']}")
    return failures
