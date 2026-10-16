"""Independent evaluation of the QA task agent against known problems of real documents.

    python -m spec_to_test.evaluation.qa_agent_eval [--json FILE] [--markdown FILE]

Each document in qa_agent_gold.json is analyzed as the on-change run does
(qa_agent.on_change.build_workspace: rule engine + generated test cases), then the
agent runs the gold's task ("Full check"). Rule-based only: no AI is involved.

The gold lists the known problems of the requirements and of the generated test
cases: kind, affected IDs and the trap it belongs to. It was judged from the texts,
not copied from the agent's output; requirement problems of reference_spec.md are
those of tests/test_reference_spec.py, those of the two Grill cases come from their
gold issues. A document or test case that no longer matches the gold (content
fingerprint, test case ID → requirement and type) stops the run: the gold is stale.

Scoring:
- only explicit problems count as found. Unknowns (the agent says the texts are not
  enough to judge) are listed as indirect hits and never count towards recall;
- a problem reported again (the other side of a contradiction or conflict, the
  second test case of the same boundary problem, an identical line) is a duplicate:
  it neither adds a true positive nor counts as a false positive;
- optional gold problems (debatable) are neither required nor false positives;
- `must_not` entries are traps a careful reviewer does not fall into (equal values
  in other units, another scope, a clear requirement): reporting one is a false
  positive and a false alarm of its trap;
- a line the agent merged (the same remark on several IDs, see qa_agent.tasks._merge)
  is scored as one line per ID, as if it had not been merged;
- status lines (coverage, traceability and suites report test cases that are not
  Approved yet) say nothing about the texts: the agent sums them up apart from the
  problems (AgentResult.approval) and they are counted there; a status line still
  among the problems is status noise, outside precision;
- scenarios that no generated test case covers (qatask.coverage.no_test_case) are
  not in the gold: they are neither true nor false positives;
- a test case problem with `expect` (probe value → whether the requirement's
  statement holds there: accepted, in time, still in effect, the change has
  happened) is resolved when the generated test cases give every listed value
  that outcome and leave no value "not specified". A resolved problem counts
  towards recall like a found one (the reader no longer has it) and is listed
  apart; it adds no line to precision. A `must_not` entry with `expect` is a
  correct test case: if the generated test cases stop matching it, that is a
  regression.

Metrics per problem kind, in total (micro) and as the mean over kinds (macro):
precision = true positives / (true positives + false positives), by the kind the
agent reported; recall = required gold problems found or resolved / required gold
problems, by the gold kind. Per trap: required problems found and false alarms.
"""

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

from spec_to_test.i18n import TRANSLATIONS
from spec_to_test.models import Workspace
from spec_to_test.qa_agent.on_change import build_workspace
from spec_to_test.qa_agent.tasks import AgentResult, Item, run_task
from spec_to_test.quantities import NUMBER, format_quantity, parse_number

from .cases import FIXTURES_DIR
from .runner import Ratio, threshold_failures

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLD_FILE = Path(__file__).with_name("qa_agent_gold.json")

RequirementKind = Literal[
    "contradiction", "ambiguous_wording", "missing_error_handling", "missing_boundary", "missing_expected_result",
]
TestCaseKind = Literal["template_test_case", "expectation_conflict", "boundary_semantics", "duplicate_test_case"]
REQUIREMENT_KINDS: tuple[str, ...] = get_args(RequirementKind)
TEST_CASE_KINDS: tuple[str, ...] = get_args(TestCaseKind)
# Agent output that fits none of the kinds above (counts against precision if reported).
OTHER = "other"
KINDS = (*REQUIREMENT_KINDS, *TEST_CASE_KINDS, OTHER)
Trap = Literal["contradiction", "within_after", "numeric_boundary", "error_handling", "template_test_case"]
TRAPS: tuple[str, ...] = get_args(Trap)

# Explicit problem lines of the agent → problem kind.
PROBLEM_KINDS = {
    "qatask.requirements.contradiction": "contradiction",
    "qatask.requirements.ambiguous_wording": "ambiguous_wording",
    "qatask.requirements.missing_error_handling": "missing_error_handling",
    "qatask.requirements.missing_expected_result": "missing_expected_result",
    "critic.step_generic": "template_test_case",
    "critic.step_placeholder": "template_test_case",
    "critic.expectation_conflict": "expectation_conflict",
    "critic.duplicate": "duplicate_test_case",
}
# Problem lines the gold does not judge: scenarios no generated test case covers.
UNJUDGED_KEYS = frozenset({"qatask.coverage.no_test_case"})
# Lines about review status (only Approved test cases count there), not about the texts.
STATUS_KEYS = frozenset({
    "qatask.coverage.missing", "qatask.trace.not_approved", "qatask.suites.no_approved",
    "qatask.suites.smoke_missing", "qatask.impact.test_case",
})
# Unknown lines → the kind of problem they point at (indirect, never counted as found).
UNKNOWN_KINDS = {
    "critic.expected_unspecified": "boundary_semantics",
    "critic.requirement_no_expected": "missing_expected_result",
    "qatask.coverage.unknown": "missing_expected_result",
}


# Test design outcomes → whether the requirement's statement holds at the probe value.
OUTCOME_HOLDS = {
    "valid": True, "in_time": True, "in_effect": True, "happened": True,
    "invalid": False, "too_late": False, "ended": False, "not_yet": False,
}
_OUTCOME_LABELS = {
    text.strip().lower(): key
    for key in (*OUTCOME_HOLDS, "stated", "unspecified")
    for text in TRANSLATIONS[f"design.{key}"].values()
}
# "29 minutes → not yet — the stated change has not happened"
_PROBE_LINE = re.compile(rf"^({NUMBER})\D.*?(?:→|->)\s*(.+?)\s*$")


def _value(text: str) -> str:
    number = parse_number(text)
    return text if number is None else format_quantity(number)


def probe_outcomes(expected_result: str) -> list[tuple[str, str]]:
    """(probe value, test design outcome) of each "value → outcome" line of an expected result."""
    found = []
    for line in expected_result.splitlines():
        if (match := _PROBE_LINE.match(line.strip())) and (key := _OUTCOME_LABELS.get(match.group(2).lower())):
            found.append((_value(match.group(1)), key))
    return found


class GoldError(Exception):
    """The gold no longer matches the documents or the generated test cases."""


class GoldProblem(BaseModel):
    # "requirement" (must_not only): any requirement problem kind.
    kind: Literal[RequirementKind, TestCaseKind, "requirement"]
    ids: list[str] = Field(min_length=1)
    trap: Trap | None = None
    # Other kinds the agent may report the same problem as ("too many attempts": vague or no boundary).
    accept: list[str] = Field(default_factory=list)
    optional: bool = False
    # Probe value → whether the requirement's statement holds there, for boundary problems of test cases.
    expect: dict[str, bool] = Field(default_factory=dict)
    note: str = ""

    def semantics_hold(self, expected_results: dict[str, str]) -> bool:
        """True when the test cases give every `expect` value its outcome and leave no value unspecified."""
        outcomes = [pair for i in self.ids for pair in probe_outcomes(expected_results.get(i, ""))]
        if any(key == "unspecified" for _, key in outcomes):
            return False
        for value, holds in self.expect.items():
            found = [OUTCOME_HOLDS.get(key) for v, key in outcomes if v == _value(value)]
            if not found or any(f is not holds for f in found):
                return False
        return True

    def matches(self, kind: str, ids: frozenset[str]) -> bool:
        if not (kind == self.kind or kind in self.accept or (self.kind == "requirement" and kind in REQUIREMENT_KINDS)):
            return False
        # A contradiction is about one pair: the agent has to name both sides.
        return set(self.ids) <= ids if self.kind == "contradiction" else bool(set(self.ids) & ids)

    def label(self) -> str:
        return f"{self.kind} {', '.join(self.ids)}" + (f" — {self.note}" if self.note else "")


class GoldDocument(BaseModel):
    name: str = Field(min_length=1)
    language: Literal["en", "ru", "uk"] = "en"
    # The document: a file under the repository root, or the requirements of a Grill eval case.
    file: str = ""
    grill_case: str = ""
    sha256: str = Field(min_length=16)  # prefix of the content hash
    # Test case ID → "<requirement ID> <test type>" of every test case the gold names.
    test_cases: dict[str, str] = Field(default_factory=dict)
    problems: list[GoldProblem] = Field(default_factory=list)
    must_not: list[GoldProblem] = Field(default_factory=list)

    def text(self) -> str:
        if self.grill_case:
            data = json.loads((FIXTURES_DIR / f"{self.grill_case}.json").read_text(encoding="utf-8"))
            return str(data["requirements"])
        return (REPO_ROOT / self.file).read_text(encoding="utf-8")


class Gold(BaseModel):
    description: str = ""
    task: str = Field(min_length=1)
    thresholds: dict[str, dict[str, float]] = Field(default_factory=dict)
    documents: list[GoldDocument] = Field(min_length=1)


def load_gold(path: Path = GOLD_FILE) -> Gold:
    return Gold.model_validate_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The agent's output as problems
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Found:
    kind: str
    ids: frozenset[str]
    line: str  # "critic.step_generic TC-001", for the report
    unknown: bool = False


def _ids(item: Item, workspace: Workspace) -> frozenset[str]:
    """The item's IDs, the IDs it names in its params, and the requirements of the test cases among them."""
    ids = {item.ref} | {i.strip() for key in ("related", "ids") for i in item.params.get(key, "").split(",")}
    ids.discard("")
    requirement_of = {tc.id: tc.requirement_id for tc in workspace.test_cases}
    return frozenset(ids | {requirement_of[i] for i in ids if i in requirement_of})


def _per_id(items: list[Item]) -> list[Item]:
    """A merged line (several IDs) as one line per ID, as the agent reported it before merging."""
    return [item.model_copy(update={"ref": i, "refs": []}) for item in items for i in item.ids or [""]]


def found_items(result: AgentResult, workspace: Workspace) -> tuple[list[Found], int]:
    """(explicit problems and mapped Unknowns, number of status lines among the problems) in report order."""
    found: list[Found] = []
    status = 0
    for step in result.steps:
        status += sum(item.key in STATUS_KEYS for item in step.problems)
        for item in _per_id(step.problems):
            if item.key in STATUS_KEYS or item.key in UNJUDGED_KEYS:
                continue
            kind = PROBLEM_KINDS.get(item.key, OTHER)
            found.append(Found(kind, _ids(item, workspace), f"{item.key} {item.ref}".strip()))
        for item in _per_id(step.unknowns):
            kind = UNKNOWN_KINDS.get(item.key, "")
            if item.key == "qatask.coverage.unknown_categories" and "scenario.boundary" in item.terms:
                kind = "missing_boundary"
            if kind:
                found.append(Found(kind, _ids(item, workspace), f"{item.key} {item.ref}".strip(), unknown=True))
    return found, status


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _ratios(names: Iterable[str]) -> dict[str, Ratio]:
    return {name: Ratio() for name in names}


@dataclass
class DocumentResult:
    name: str
    precision: dict[str, Ratio] = field(default_factory=lambda: _ratios(KINDS))
    recall: dict[str, Ratio] = field(default_factory=lambda: _ratios(KINDS))
    trap_recall: dict[str, Ratio] = field(default_factory=lambda: _ratios(TRAPS))
    # must_not entries of the trap that the agent fell into / must_not entries.
    trap_false_alarms: dict[str, Ratio] = field(default_factory=lambda: _ratios([*TRAPS, OTHER]))
    problems: int = 0  # lines in the agent's problem list, status lines included
    duplicates: int = 0
    status_noise: int = 0
    approval: int = 0  # status lines summed up apart from the problems
    optional_hits: int = 0
    missed: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    # Required problems the agent only pointed at with an Unknown.
    unknown_only: list[str] = field(default_factory=list)
    # Required test case problems the generated test cases no longer have (see `expect`).
    resolved: list[str] = field(default_factory=list)
    # must_not test cases with `expect` that the generated test cases no longer match.
    regressions: list[str] = field(default_factory=list)


def score_document(
    doc: GoldDocument, found: list[Found], status_lines: int = 0, expected_results: dict[str, str] | None = None,
    problem_lines: int | None = None, approval_lines: int = 0,
) -> DocumentResult:
    """Score the agent's output; `expected_results` (test case ID → expected result) checks `expect` entries.

    `problem_lines` is the length of the agent's problem list (merged lines count once);
    without it every explicit problem and status line counts as one line.
    """
    result = DocumentResult(name=doc.name, status_noise=status_lines, approval=approval_lines)
    expected_results = expected_results or {}
    # Required problems are credited before optional ones the same line also matches.
    order = sorted(range(len(doc.problems)), key=lambda i: doc.problems[i].optional)
    credited: set[int] = set()
    false_seen: set[tuple[str, frozenset[str]]] = set()
    fallen: set[int] = set()
    explicit = [f for f in found if not f.unknown]
    result.problems = len(explicit) + status_lines if problem_lines is None else problem_lines
    for item in explicit:
        matches = [i for i in order if doc.problems[i].matches(item.kind, item.ids)]
        if matches:
            fresh = [i for i in matches if i not in credited]
            if not fresh:
                result.duplicates += 1
                continue
            credited.add(fresh[0])
            if doc.problems[fresh[0]].optional:
                result.optional_hits += 1
            else:
                result.precision[item.kind].add(True)
            continue
        if (item.kind, item.ids) in false_seen:
            result.duplicates += 1
            continue
        false_seen.add((item.kind, item.ids))
        result.precision[item.kind].add(False)
        traps = [i for i, trap in enumerate(doc.must_not) if trap.matches(item.kind, item.ids)]
        fallen.update(traps)
        result.false_positives.append(item.line + (f" (trap: {doc.must_not[traps[0]].label()})" if traps else ""))

    for i, problem in enumerate(doc.problems):
        if problem.optional:
            continue
        hit = i in credited
        if not hit and problem.expect and problem.semantics_hold(expected_results):
            hit = True
            result.resolved.append(problem.label())
        result.recall[problem.kind].add(hit)
        if problem.trap:
            result.trap_recall[problem.trap].add(hit)
        if not hit:
            indirect = [f.line for f in found if f.unknown and problem.matches(f.kind, f.ids)]
            result.missed.append(problem.label() + (f" [Unknown only: {'; '.join(indirect)}]" if indirect else ""))
            if indirect:
                result.unknown_only.append(problem.label())
    for i, trap in enumerate(doc.must_not):
        result.trap_false_alarms[trap.trap or OTHER].add(i in fallen)
        if trap.expect and not trap.semantics_hold(expected_results):
            result.regressions.append(trap.label())
    return result


@dataclass
class EvalResult:
    task: str
    documents: list[DocumentResult]

    def _sum(self, attr: str, names: Iterable[str]) -> dict[str, Ratio]:
        total = _ratios(names)
        for doc in self.documents:
            for name, ratio in getattr(doc, attr).items():
                total[name].num += ratio.num
                total[name].den += ratio.den
        return total

    def totals(self) -> dict[str, float | int | None]:
        precision, recall = self._sum("precision", KINDS), self._sum("recall", KINDS)
        traps, alarms = self._sum("trap_recall", TRAPS), self._sum("trap_false_alarms", [*TRAPS, OTHER])
        out: dict[str, float | int | None] = {
            "precision": Ratio(sum(r.num for r in precision.values()), sum(r.den for r in precision.values())).value,
            "recall": Ratio(sum(r.num for r in recall.values()), sum(r.den for r in recall.values())).value,
        }
        # Macro: the mean over the kinds with data, so 46 template test cases do not outweigh the rest.
        for name, ratios in (("precision", precision), ("recall", recall)):
            values = [r.value for r in ratios.values() if r.value is not None]
            out[f"{name}_macro"] = round(sum(values) / len(values), 4) if values else None
        out |= {f"precision.{k}": r.value for k, r in precision.items()}
        out |= {f"recall.{k}": r.value for k, r in recall.items()}
        out |= {f"trap.{k}": r.value for k, r in traps.items()}
        out["false_alarms"] = sum(r.num for r in alarms.values())
        problems = sum(d.problems for d in self.documents)
        out |= {
            "problems": problems,
            "duplicates": sum(d.duplicates for d in self.documents),
            "status_noise": sum(d.status_noise for d in self.documents),
            "status_noise_share": Ratio(sum(d.status_noise for d in self.documents), problems).value,
            "approval": sum(d.approval for d in self.documents),
            "unknown_only": sum(len(d.unknown_only) for d in self.documents),
            "resolved": sum(len(d.resolved) for d in self.documents),
            "regressions": sum(len(d.regressions) for d in self.documents),
        }
        return out

    def to_data(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "totals": self.totals(),
            "documents": [
                {
                    "name": d.name,
                    "precision": {k: [r.num, r.den] for k, r in d.precision.items() if r.den},
                    "recall": {k: [r.num, r.den] for k, r in d.recall.items() if r.den},
                    "problems": d.problems, "duplicates": d.duplicates, "status_noise": d.status_noise,
                    "approval": d.approval,
                    "optional_hits": d.optional_hits, "missed": d.missed, "false_positives": d.false_positives,
                    "resolved": d.resolved, "regressions": d.regressions,
                }
                for d in self.documents
            ],
        }

    def to_markdown(self, failures: list[str] | None = None) -> str:
        def fmt(value: float | int | None) -> str:
            return "—" if value is None else (f"{value:.2f}" if isinstance(value, float) else str(value))

        def frac(ratio: Ratio) -> str:
            return f"{ratio.num}/{ratio.den}" if ratio.den else "—"

        precision, recall = self._sum("precision", KINDS), self._sum("recall", KINDS)
        totals = self.totals()
        out = [f"# QA Agent evaluation (task “{self.task}”, rule-based)", "",
               "| Kind | Precision | TP/reported | Recall | found/required |", "|---|---|---|---|---|"]
        for kind in KINDS:
            if precision[kind].den or recall[kind].den:
                out.append(f"| {kind} | {fmt(precision[kind].value)} | {frac(precision[kind])} | "
                           f"{fmt(recall[kind].value)} | {frac(recall[kind])} |")
        out.append(f"| **total (micro)** | {fmt(totals['precision'])} | | {fmt(totals['recall'])} | |")
        out.append(f"| **mean of kinds (macro)** | {fmt(totals['precision_macro'])} | | {fmt(totals['recall_macro'])} | |")
        out += ["", "| Document | Precision | Recall | Problem lines | Duplicates | Status noise | Not Approved "
                "(apart) | Unknown only |", "|---|---|---|---|---|---|---|---|"]
        for doc in self.documents:
            p = Ratio(sum(r.num for r in doc.precision.values()), sum(r.den for r in doc.precision.values()))
            r = Ratio(sum(x.num for x in doc.recall.values()), sum(x.den for x in doc.recall.values()))
            out.append(f"| {doc.name} | {fmt(p.value)} | {fmt(r.value)} | {doc.problems} | {doc.duplicates} | "
                       f"{doc.status_noise} | {doc.approval} | {len(doc.unknown_only)} |")
        out.append(f"\nStatus noise: {totals['status_noise']} of {totals['problems']} problem lines "
                   f"({fmt(totals['status_noise_share'])}) only say that test cases are not Approved; "
                   f"{totals['approval']} such lines are summed up apart from the problems.")
        out.append(f"\nResolved in the generated test cases (counted in recall): {totals['resolved']}. "
                   f"Regressions of correct test cases: {totals['regressions']}.")
        traps, alarms = self._sum("trap_recall", [*TRAPS, OTHER]), self._sum("trap_false_alarms", [*TRAPS, OTHER])
        out += ["", "| Trap | Found | False alarms |", "|---|---|---|"]
        out += [f"| {t} | {frac(traps[t])} | {frac(alarms[t])} |" for t in [*TRAPS, OTHER] if traps[t].den or alarms[t].den]
        for doc in self.documents:
            if doc.missed or doc.false_positives or doc.resolved or doc.regressions:
                out += ["", f"## {doc.name}"]
                out += [f"- missed: {m}" for m in doc.missed]
                out += [f"- false positive: {m}" for m in doc.false_positives]
                out += [f"- regression: {m}" for m in doc.regressions]
                out += [f"- resolved: {m}" for m in doc.resolved]
        if failures is not None:
            out += ["", "## Thresholds", ""]
            out += [f"- FAILED {f}" for f in failures] or ["- all thresholds met"]
        return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_gold(doc: GoldDocument, text: str, workspace: Workspace) -> list[str]:
    """Why the gold does not fit the document and its generated test cases ([] = it fits)."""
    errors = []
    if not _fingerprint(text).startswith(doc.sha256):
        errors.append(f"{doc.name}: the document changed (sha256 {_fingerprint(text)[:16]}, gold {doc.sha256})")
    test_cases = {tc.id: f"{tc.requirement_id} {tc.test_type.value}" for tc in workspace.test_cases}
    for tc_id, expected in doc.test_cases.items():
        if test_cases.get(tc_id) != expected:
            errors.append(f"{doc.name}: {tc_id} is {test_cases.get(tc_id, 'missing')}, gold says {expected}")
    known = set(test_cases) | {r.id for r in workspace.requirements}
    for problem in [*doc.problems, *doc.must_not]:
        if unknown := [i for i in problem.ids if i not in known]:
            errors.append(f"{doc.name}: {problem.kind} names unknown IDs {', '.join(unknown)}")
        if missing := [i for i in problem.ids if i in test_cases and i not in doc.test_cases]:
            errors.append(f"{doc.name}: {', '.join(missing)} not in the gold's test_cases")
    return errors


def run_eval(gold: Gold | None = None) -> EvalResult:
    """Run the agent on every gold document and score it. Raises GoldError when the gold is stale."""
    gold = gold or load_gold()
    results = []
    errors = []
    for doc in gold.documents:
        text = doc.text()
        workspace = build_workspace(text, doc.name, doc.language)
        if problems := check_gold(doc, text, workspace):
            errors += problems
            continue
        agent = run_task(gold.task, workspace)
        found, status = found_items(agent, workspace)
        expected_results = {tc.id: tc.expected_result for tc in workspace.test_cases}
        results.append(score_document(doc, found, status, expected_results, problem_lines=len(agent.problems),
                                      approval_lines=sum(len(step.approval) for step in agent.steps)))
    if errors:
        raise GoldError("\n".join(errors))
    return EvalResult(task=gold.task, documents=results)


def main(argv: list[str] | None = None) -> int:
    """Exits with 1 when a threshold in the gold is not met, 2 when the gold is stale."""
    parser = argparse.ArgumentParser(prog="python -m spec_to_test.evaluation.qa_agent_eval",
                                     description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gold", type=Path, default=GOLD_FILE, help="gold file")
    parser.add_argument("--json", type=Path, help="write the full result as JSON")
    parser.add_argument("--markdown", type=Path, help="write the summary as Markdown")
    args = parser.parse_args(argv)
    gold = load_gold(args.gold)
    try:
        result = run_eval(gold)
    except GoldError as error:
        print(f"The gold is stale, update it after checking the documents:\n{error}", file=sys.stderr)
        return 2
    failures = threshold_failures(result.totals(), gold.thresholds)
    summary = result.to_markdown(failures)
    print(summary)
    if args.json:
        args.json.write_text(json.dumps({**result.to_data(), "failures": failures}, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(summary, encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
