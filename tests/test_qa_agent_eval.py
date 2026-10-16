"""The QA Agent evaluation: a hand-written gold, scoring that is not inflated, a gated baseline."""

import json

import pytest
from test_reference_spec import EXPECTED as REFERENCE_EXPECTED

from spec_to_test import test_design
from spec_to_test.evaluation.cases import FIXTURES_DIR, EvalCase
from spec_to_test.evaluation.qa_agent_eval import (
    REQUIREMENT_KINDS,
    TRAPS,
    Found,
    GoldDocument,
    GoldError,
    GoldProblem,
    found_items,
    load_gold,
    main,
    probe_outcomes,
    run_eval,
    score_document,
)
from spec_to_test.evaluation.runner import threshold_failures
from spec_to_test.models import Workspace
from spec_to_test.qa_agent import tasks
from spec_to_test.qa_agent.on_change import build_workspace
from spec_to_test.qa_agent.tasks import Item, run_task


@pytest.fixture(scope="module")
def gold():
    return load_gold()


@pytest.fixture(scope="module")
def result(gold):
    return run_eval(gold)


def _doc(gold, name: str) -> GoldDocument:
    return next(d for d in gold.documents if d.name == name)


# ---------------------------------------------------------------------------
# The gold
# ---------------------------------------------------------------------------

def test_gold_covers_the_five_documents_every_kind_and_every_trap(gold):
    assert [d.name for d in gold.documents] == [
        "password_reset", "qa_demo", "reference_spec", "checkout_ru", "uk_units_ranges"]
    required = [p for d in gold.documents for p in d.problems if not p.optional]
    assert {p.kind for p in required} >= {*REQUIREMENT_KINDS, "template_test_case", "expectation_conflict",
                                          "boundary_semantics"}
    assert all(any(p.trap == trap for p in required) for trap in TRAPS)
    # Traps a good reviewer must not fall into, too.
    must_not = {t.trap for d in gold.documents for t in d.must_not}
    assert {"contradiction", "numeric_boundary", "error_handling", "template_test_case"} <= must_not


def test_reference_spec_requirement_gold_is_the_reference_test_gold(gold):
    doc = _doc(gold, "reference_spec")
    expected = {(req_id, kind.value) for req_id, kinds in REFERENCE_EXPECTED.items() for kind in kinds}
    assert {(i, p.kind) for p in doc.problems if p.kind in REQUIREMENT_KINDS for i in p.ids} == expected
    clear = {req_id for req_id, kinds in REFERENCE_EXPECTED.items() if not kinds}
    assert {i for t in doc.must_not if t.kind == "requirement" for i in t.ids} == clear


@pytest.mark.parametrize("name", ["checkout_ru", "uk_units_ranges"])
def test_grill_case_gold_agrees_with_the_grill_eval(gold, name):
    doc = _doc(gold, name)
    case = EvalCase.model_validate_json((FIXTURES_DIR / f"{doc.grill_case}.json").read_text(encoding="utf-8"))
    required = [p for p in doc.problems if not p.optional and p.kind in REQUIREMENT_KINDS]
    assert {frozenset(p.ids) for p in required if p.kind == "contradiction"} == {
        frozenset(pair) for pair in case.gold.contradictions}
    assert {frozenset(pair) for pair in case.gold.non_contradictions} <= {
        frozenset(t.ids) for t in doc.must_not if t.kind == "contradiction"}
    for issue in case.gold.issues:  # every issue the Grill must ask about is a known problem here too
        assert any(set(p.ids) == set(issue.requirement_ids) for p in required), issue.note


def test_a_changed_document_or_renumbered_test_case_makes_the_gold_stale(gold):
    changed = gold.model_copy(deep=True)
    changed.documents[0].sha256 = "0" * 16
    changed.documents[1].test_cases["TC-001"] = "REQ-2 positive"
    with pytest.raises(GoldError) as error:
        run_eval(changed)
    assert "password_reset: the document changed" in str(error.value)
    assert "qa_demo: TC-001 is REQ-1 positive, gold says REQ-2 positive" in str(error.value)


def test_gold_ids_must_exist_and_named_test_cases_must_be_fingerprinted(gold):
    changed = gold.model_copy(deep=True)
    changed.documents[1].problems.append(GoldProblem(kind="ambiguous_wording", ids=["REQ-99"]))
    changed.documents[1].test_cases.pop("TC-006")
    with pytest.raises(GoldError) as error:
        run_eval(changed)
    assert "unknown IDs REQ-99" in str(error.value) and "TC-006 not in the gold's test_cases" in str(error.value)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

SYNTHETIC = GoldDocument(
    name="synthetic", sha256="0" * 16,
    problems=[
        GoldProblem(kind="contradiction", ids=["REQ-1", "REQ-2"], trap="contradiction"),
        GoldProblem(kind="boundary_semantics", ids=["TC-1", "TC-2"], trap="within_after"),
        GoldProblem(kind="missing_boundary", ids=["REQ-5"], accept=["ambiguous_wording"]),
        GoldProblem(kind="missing_error_handling", ids=["REQ-3"], optional=True),
    ],
    must_not=[GoldProblem(kind="contradiction", ids=["REQ-3", "REQ-4"], trap="contradiction")],
)


def found(kind: str, *ids: str, unknown: bool = False) -> Found:
    return Found(kind, frozenset(ids), f"{kind} {' '.join(ids)}", unknown=unknown)


def test_both_sides_of_a_contradiction_count_once():
    score = score_document(SYNTHETIC, [found("contradiction", "REQ-1", "REQ-2"), found("contradiction", "REQ-2", "REQ-1")])
    assert (score.precision["contradiction"].num, score.precision["contradiction"].den) == (1, 1)
    assert score.recall["contradiction"].value == 1.0 and score.duplicates == 1


def test_the_same_problem_on_two_test_cases_counts_once():
    score = score_document(SYNTHETIC, [found("boundary_semantics", "TC-1"), found("boundary_semantics", "TC-2")])
    assert score.precision["boundary_semantics"].den == 1 and score.duplicates == 1
    assert score.trap_recall["within_after"].value == 1.0


def test_an_unknown_is_not_a_found_problem():
    score = score_document(SYNTHETIC, [found("boundary_semantics", "TC-1", unknown=True)])
    assert score.recall["boundary_semantics"].value == 0.0
    assert score.precision["boundary_semantics"].den == 0
    assert score.unknown_only == ["boundary_semantics TC-1, TC-2"]
    assert any("Unknown only" in line for line in score.missed)


def test_a_contradiction_needs_the_right_pair():
    score = score_document(SYNTHETIC, [found("contradiction", "REQ-1", "REQ-7")])
    assert score.recall["contradiction"].value == 0.0
    assert score.precision["contradiction"].value == 0.0


def test_a_trap_is_a_false_positive_and_a_false_alarm_once():
    lines = [found("contradiction", "REQ-3", "REQ-4"), found("contradiction", "REQ-3", "REQ-4")]
    score = score_document(SYNTHETIC, lines)
    assert (score.precision["contradiction"].num, score.precision["contradiction"].den) == (0, 1)
    assert score.trap_false_alarms["contradiction"].value == 1.0 and score.duplicates == 1
    assert "trap:" in score.false_positives[0]


def test_optional_problems_are_neutral_and_accepted_kinds_count():
    score = score_document(SYNTHETIC, [found("missing_error_handling", "REQ-3"), found("ambiguous_wording", "REQ-5")])
    assert score.optional_hits == 1 and score.precision["missing_error_handling"].den == 0
    assert score.precision["ambiguous_wording"].value == 1.0 and score.recall["missing_boundary"].value == 1.0
    assert score.recall["missing_error_handling"].den == 0  # optional problems are not required


def test_status_lines_are_apart_and_never_false_positives(gold):
    doc = _doc(gold, "qa_demo")
    workspace = build_workspace(doc.text(), doc.name, doc.language)
    agent = run_task(gold.task, workspace)
    items, status = found_items(agent, workspace)
    # "Not Approved" lines are summed up apart from the problems, so none is noise among them.
    assert status == 0 and agent.approval is not None and any(step.approval for step in agent.steps)
    assert all(not f.line.startswith(("qatask.coverage.", "qatask.trace.", "qatask.suites.")) for f in items)
    # Test case problems also carry their requirement, so requirement-level gold can match them.
    assert found("template_test_case", "TC-001", "REQ-1").ids <= next(f.ids for f in items if "TC-001" in f.line)


def test_a_merged_line_is_scored_as_one_line_per_id():
    workspace = Workspace(document_hash="doc")
    step = tasks.StepResult(tool="critic", problems=[
        Item(key="critic.step_generic", params={"steps": "1"}, ref="TC-1", refs=["TC-2"]),
        Item(key="qatask.coverage.no_test_case", ref="REQ-1", terms=["scenario.boundary"]),
    ], approval=[Item(key="qatask.trace.not_approved", ref="REQ-1")])
    items, status = found_items(tasks.AgentResult(task="t", status="done", steps=[step]), workspace)
    # Scenarios no test case covers are not in the gold: neither true nor false positives.
    assert [(f.kind, f.ids) for f in items] == [("template_test_case", frozenset({"TC-1"})),
                                               ("template_test_case", frozenset({"TC-2"}))]
    assert status == 0
    score = score_document(SYNTHETIC, items, status, problem_lines=2, approval_lines=1)
    assert (score.problems, score.approval, score.status_noise) == (2, 1, 0)


def test_critic_unknowns_are_mapped_as_unknown(gold):
    # A plain exact value still leaves its neighbours "not specified".
    workspace = build_workspace("REQ-1: The discount is 10%.", "exact", "en")
    items, _ = found_items(run_task(gold.task, workspace), workspace)
    boundary = next(tc.id for tc in workspace.test_cases if tc.test_type.value == "boundary")
    assert any(f.unknown and f.kind == "boundary_semantics" and boundary in f.ids for f in items)


# ---------------------------------------------------------------------------
# Boundary semantics of the generated test cases
# ---------------------------------------------------------------------------

TIMED = GoldDocument(
    name="timed", sha256="0" * 16,
    problems=[GoldProblem(kind="boundary_semantics", ids=["TC-1", "TC-2"], trap="within_after",
                          expect={"29": False, "31": True})],
    must_not=[GoldProblem(kind="boundary_semantics", ids=["TC-3"], trap="numeric_boundary",
                          expect={"499": False, "500": True})],
)
FIXED = {
    "TC-1": "29 minutes → not yet — the stated change has not happened\n30 minutes → as stated in the requirement\n"
            "31 minutes → the stated change has happened",
    "TC-2": "15 minutes → not yet — the stated change has not happened\n60 minutes → the stated change has happened",
    "TC-3": "499 рублей → отклоняется (невалидное)\n500 рублей → принимается (валидное)",
}


def test_probe_outcomes_read_every_language():
    assert probe_outcomes(FIXED["TC-1"]) == [("29", "not_yet"), ("30", "stated"), ("31", "happened")]
    assert probe_outcomes("14 хвилин → ще ні — зазначена зміна ще не відбулася\nкрок без значення") == [
        ("14", "not_yet")]
    assert probe_outcomes("1 023 КБ → приймається (валідне)") == [("1023", "valid")]


def test_a_boundary_problem_is_resolved_only_by_the_stated_outcomes():
    score = score_document(TIMED, [], expected_results=FIXED)
    assert score.recall["boundary_semantics"].value == 1.0 and score.trap_recall["within_after"].value == 1.0
    assert score.resolved == [TIMED.problems[0].label()] and score.missed == [] and score.regressions == []
    assert score.precision["boundary_semantics"].den == 0  # nothing was reported
    old = {**FIXED, "TC-1": "29 minutes → not specified — needs clarification\n31 minutes → not specified — needs "
                            "clarification"}
    wrong = {**FIXED, "TC-1": "29 minutes → the stated change has happened\n31 minutes → the stated change has happened"}
    unspecified_class = {**FIXED, "TC-2": "60 minutes → not specified — needs clarification"}
    missing_probe = {**FIXED, "TC-1": "30 minutes → as stated in the requirement"}
    for expected_results in (old, wrong, unspecified_class, missing_probe, {}):
        score = score_document(TIMED, [], expected_results=expected_results)
        assert score.recall["boundary_semantics"].value == 0.0 and score.resolved == []


def test_a_correct_test_case_that_changes_is_a_regression():
    broken = {**FIXED, "TC-3": "499 рублей → принимается (валидное)\n500 рублей → принимается (валидное)"}
    assert score_document(TIMED, [], expected_results=broken).regressions == [TIMED.must_not[0].label()]
    stale = {**FIXED, "TC-3": "500 рублей → как указано в требовании\n501 рубль → не определено — требует уточнения"}
    assert score_document(TIMED, [], expected_results=stale).regressions == [TIMED.must_not[0].label()]


def test_gold_expectations_restate_their_notes(gold):
    timed = [p for d in gold.documents for p in [*d.problems, *d.must_not] if p.kind == "boundary_semantics"]
    assert timed and all(p.expect for p in timed)
    assert all(i.startswith("TC-") for p in timed for i in p.ids)


# ---------------------------------------------------------------------------
# The baseline
# ---------------------------------------------------------------------------

def test_the_agent_meets_the_gold_thresholds(gold, result):
    assert threshold_failures(result.totals(), gold.thresholds) == []


def test_a_regression_of_the_agent_fails_the_thresholds(gold, monkeypatch):
    monkeypatch.setattr(tasks, "_FINDING_TYPES", ())  # the agent stops reporting requirement findings
    failures = threshold_failures(run_eval(gold).totals(), gold.thresholds)
    assert any(f.startswith("recall.contradiction") for f in failures)


def test_missing_expected_results_are_reported_explicitly_without_false_alarms(result):
    totals = result.totals()
    # 10 of 11: «Сесія завершується через 15 хвилин» names a checkable change, so the rules accept it.
    assert totals["recall.missing_expected_result"] == pytest.approx(10 / 11, abs=1e-3)
    assert totals["precision.missing_expected_result"] == 1.0 and totals["false_alarms"] == 0
    missed = [line for d in result.documents for line in d.missed if line.startswith("missing_expected_result")]
    assert missed == ["missing_expected_result REQ-5 — що бачить користувач після завершення сесії"]
    # Found as problems, not as Unknowns of the critic or coverage.
    assert not any(line.startswith("missing_expected_result") for d in result.documents for line in d.unknown_only)


def test_a_regression_of_missing_expected_results_shows_in_the_eval(gold, monkeypatch):
    monkeypatch.setattr(tasks, "_FINDING_TYPES", tuple(t for t in tasks._FINDING_TYPES
                                                       if t.value != "missing_expected_result"))
    assert run_eval(gold).totals()["recall.missing_expected_result"] == 0.0


def test_boundary_semantics_are_resolved_without_regressions(result):
    totals = result.totals()
    assert totals["recall.boundary_semantics"] == 1.0 and totals["trap.within_after"] == 1.0
    assert totals["regressions"] == 0 and totals["precision"] == 1.0 and totals["false_alarms"] == 0


def test_a_regression_of_the_test_design_fails_the_thresholds(gold, monkeypatch):
    monkeypatch.setattr(test_design, "_timing", lambda text, quantity: None)  # "after 30 minutes" as equality again
    failures = threshold_failures(run_eval(gold).totals(), gold.thresholds)
    assert any(f.startswith("recall.boundary_semantics") for f in failures)
    monkeypatch.undo()
    monkeypatch.setattr(test_design, "_step", lambda *values: 2)  # probes too far from the limits
    totals = run_eval(gold).totals()
    assert totals["regressions"] == 2
    assert any(f.startswith("regressions") for f in threshold_failures(totals, gold.thresholds))


def test_the_run_is_deterministic(gold, result):
    assert run_eval(gold).to_data() == result.to_data()


def test_command_line_writes_reports(tmp_path, capsys):
    assert main(["--json", str(tmp_path / "r.json"), "--markdown", str(tmp_path / "r.md")]) == 0
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["failures"] == [] and data["totals"]["false_alarms"] == 0
    markdown = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "| **total (micro)** |" in markdown and "Status noise:" in markdown and "all thresholds met" in markdown
    assert markdown in capsys.readouterr().out


def test_command_line_reports_a_stale_gold(tmp_path, gold, capsys):
    stale = gold.model_copy(deep=True)
    stale.documents[0].sha256 = "f" * 16
    path = tmp_path / "gold.json"
    path.write_text(stale.model_dump_json(), encoding="utf-8")
    assert main(["--gold", str(path)]) == 2
    assert "stale" in capsys.readouterr().err
