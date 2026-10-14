"""The AI quality evaluation suite: deterministic, offline, and gated by thresholds."""

import json

import pytest

from spec_to_test.evaluation import check_thresholds, load_cases, load_thresholds, run_case, run_suite
from spec_to_test.evaluation.__main__ import main
from spec_to_test.evaluation.cases import EvalCase
from spec_to_test.evaluation.runner import RATIOS, SuiteResult


@pytest.fixture(scope="module")
def scripted() -> SuiteResult:
    return run_suite()


@pytest.fixture(scope="module")
def rules() -> SuiteResult:
    return run_suite(use_ai=False)


def test_fixtures_are_valid_and_cover_the_scenarios():
    cases = load_cases()
    assert len(cases) >= 25
    assert len({c.name for c in cases}) == len(cases)
    assert cases[:4] == [c for c in cases if c.name in (
        "password_reset", "file_upload_api_failure", "checkout_ru", "password_reset_resumed")]
    by_language = {lang: [c for c in cases if c.language == lang] for lang in ("en", "ru", "uk")}
    assert all(len(group) >= 7 for group in by_language.values())
    assert all(c.gold.issues for c in cases)
    # Every scenario type the suite is meant to measure is present.
    assert sum(bool(c.gold.contradictions) for c in cases) >= 10
    assert sum(bool(c.gold.non_contradictions) for c in cases) >= 6
    assert sum(bool(c.gold.must_not_ask) for c in cases) >= 8
    assert sum(bool(c.steps) for c in cases) >= 3 and any(c.settled for c in cases)
    assert sum(any("error" in reply for replies in c.ai.values() for reply in replies) for c in cases) >= 4
    assert any("USD" in c.requirements for c in cases) and any("грн" in c.requirements for c in cases)
    assert any("₽" in c.requirements or "руб" in c.requirements for c in cases)


def test_scripted_and_rule_runs_meet_their_thresholds(scripted, rules):
    thresholds = load_thresholds()
    assert check_thresholds(scripted, thresholds["scripted"]) == []
    assert check_thresholds(rules, thresholds["rules"]) == []


def test_the_suite_is_deterministic(scripted, no_network):
    again = run_suite()
    assert again.to_data() == scripted.to_data()


def test_ai_adds_coverage_without_duplicates(scripted, rules):
    ai, base = scripted.totals(), rules.totals()
    assert ai["coverage"] > base["coverage"]
    assert ai["duplication"] == 0 and ai["resolved_reasked"] == 0
    assert ai["ai_questions_asked"] > 0


def test_hallucinations_are_caught_before_they_reach_the_user(scripted):
    totals = scripted.totals()
    assert totals["hallucination_raw"] > 0  # the fixtures do plant some
    assert totals["hallucination_accepted"] == 0
    assert totals["invented_requirements"] == 0
    planted = next(c for c in scripted.cases if c.name == "password_reset").hallucinations
    assert any("REQ-12" in h for h in planted) and any("REQ-42" in h for h in planted)
    assert any("within 3 seconds" in h for h in planted)


def test_rule_engine_quality_without_ai(rules):
    totals = rules.totals()
    assert totals["false_positive_rate"] == 0
    assert totals["contradiction_recall"] == 1.0 and totals["contradiction_precision"] == 1.0
    assert totals["invented_values"] == 0 and totals["progress_regressions"] == 0
    for case in rules.cases:
        assert not case.false_positives, case.name
        assert not case.contradiction_misses, case.name


def test_findings_changed_during_the_interview_update_the_queue(scripted):
    for name, reopened, resolved in (
        ("en_reopen_mid_interview", "rule.ambiguous_wording.REQ-2", "rule.missing_error_handling.REQ-1"),
        ("ru_reopen_steps", "rule.missing_expected_result.REQ-1", "rule.missing_error_handling.REQ-3"),
        ("uk_reopen_steps", "rule.ambiguous_wording.REQ-2", "rule.missing_error_handling.REQ-3"),
    ):
        case = next(c for c in scripted.cases if c.name == name)
        asked = [q.id for q in case.asked]
        assert reopened in asked, name  # reopened in the document: asked after all
        assert resolved not in asked, name  # resolved in the document before it came up
        assert case.ratios["resolved_reasked"].value == 0
        assert case.counts["progress_regressions"] == 0
        assert case.ratios["coverage"].value == 1.0


def test_one_answer_can_settle_another_question(scripted):
    for name, settled in (
        ("en_answered_elsewhere", "rule.missing_boundary.REQ-1"),
        ("ru_answered_elsewhere", "rule.missing_error_handling.REQ-1"),
        ("uk_answered_elsewhere", "rule.missing_boundary.REQ-1"),
    ):
        case = next(c for c in scripted.cases if c.name == name)
        assert settled not in {q.id for q in case.asked}, name
        assert case.ratios["false_positive_rate"].value == 0


def test_model_repeats_and_false_dilemmas_are_dropped(scripted):
    prompts = {c.name: [q.prompt for q in c.asked] for c in scripted.cases}
    assert not any("1800 seconds" in p for p in prompts["en_equivalent_units"])  # 30 min = 1800 s
    assert not any("1024 КБ" in p for p in prompts["uk_units_ranges"])  # 1 MB = 1024 KB
    assert not any("1 день" in p for p in prompts["ru_time_units"])  # 24 h = 1 day
    assert not any("200 мс или" in p for p in prompts["ru_duplicates_ai"])  # the rule question asks it
    assert not any("500 или 1000" in p for p in prompts["checkout_ru"])  # now found by the rules
    assert sum("после отправки" in p for p in prompts["ru_duplicates_ai"]) == 1
    assert sum("fast" in p.casefold() for p in prompts["en_duplicates"]) == 1


def test_every_kind_of_model_failure_is_survived(scripted):
    case = next(c for c in scripted.cases if c.name == "en_api_failures")
    assert case.errors == ["interview: connection", "interview: api", "review: rate_limit", "test_cases: auth"]
    assert case.counts["ai_questions_asked"] == 1 and case.ratios["coverage"].value == 1.0


def test_an_api_failure_does_not_stop_the_interview(scripted):
    case = next(c for c in scripted.cases if c.name == "file_upload_api_failure")
    assert case.counts["ai_errors"] == 1 and case.errors == ["interview: rate_limit"]
    assert case.counts["questions_asked"] > case.counts["ai_questions_asked"] > 0  # the next call worked
    assert case.ratios["coverage"].value == 1.0


def test_resolved_findings_are_not_asked_again(scripted):
    case = next(c for c in scripted.cases if c.name == "password_reset_resumed")
    asked = {q.id for q in case.asked}
    assert not asked & {"rule.ambiguous_wording.REQ-5", "rule.contradiction.REQ-4+REQ-7"}
    assert not any("fast" in q.prompt for q in case.asked)  # the model's repeat was dropped too


def test_metrics_are_ratios_with_counts(scripted):
    data = scripted.to_data()
    assert set(RATIOS) <= set(data["totals"])
    for case in data["cases"]:
        for question in case["asked"]:
            assert question["prompt"] and isinstance(question["relevant"], bool)
    markdown = scripted.to_markdown([])
    assert "| **total** |" in markdown and "all thresholds met" in markdown


def test_thresholds_detect_a_regression(scripted):
    failures = check_thresholds(scripted, {"coverage": {"min": 1.01}, "hallucination_accepted": {"max": -1}})
    assert len(failures) == 2 and failures[0].startswith("coverage")


def test_a_case_without_gold_issues_scores_none_not_perfect():
    case = EvalCase(name="empty", requirements="REQ-1: The system must send a confirmation email after registration.")
    result = run_case(case, use_ai=False)
    assert result.ratios["coverage"].value is None


def test_command_line(tmp_path, capsys):
    out = tmp_path / "result.json"
    assert main(["--json", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["mode"] == "scripted" and data["failures"] == []
    assert "# Grill AI evaluation (scripted)" in capsys.readouterr().out
    report = tmp_path / "rules.md"
    assert main(["--rules-only", "--markdown", str(report)]) == 0
    assert "false_positive_rate" in report.read_text(encoding="utf-8")


def test_live_mode_needs_a_provider(capsys):
    assert main(["--live"]) == 2  # AI_PROVIDER=none in tests
