"""QA Agent coverage, bug reports, exports, storage and the optional AI step proposals.

These are unit tests of the formatting and storage code, so they build run
records by hand; the real browser runs are in test_qa_agent_e2e.py.
"""

import io
import zipfile

import pytest

from spec_to_test.llm.config import AIConfig
from spec_to_test.llm.providers import AIError
from spec_to_test.models import Requirement, Severity
from spec_to_test.qa_agent import ai as qa_ai
from spec_to_test.qa_agent.bugs import generate_bugs
from spec_to_test.qa_agent.models import (
    CaseResult,
    PlanCase,
    PlanStep,
    QARun,
    RunState,
    RunStatus,
    StepAction,
    StepResult,
    TestPlan,
)
from spec_to_test.qa_agent.report import CoverageStatus, bugs_csv, bundle, coverage, markdown_report, results_csv
from spec_to_test.qa_agent.store import RunStore, open_run_store

REQUIREMENTS = [Requirement(id=f"REQ-{n}", text=f"Requirement {n}.") for n in range(1, 7)]
CHECK = PlanStep(action=StepAction.EXPECT_TEXT, value="Email is required")


def result(case_id: str, req: str, status: RunStatus, **extra) -> CaseResult:
    return CaseResult(case_id=case_id, requirement_id=req, title=f"Case {case_id}", status=status, **extra)


def sample_run(run_id: str = "a" * 16, created_at: str = "2026-10-13T10:00:00+00:00") -> QARun:
    failed = result(
        "QA-002", "REQ-2", RunStatus.FAILED, reason="assertion", error="Locator expected to contain text",
        expected_result='The error "Email is required" is shown.', actual_result="Page shows Thanks",
        screenshot="002-QA-002.png", console_errors=["TypeError: x"], test_case_id="TC-002",
        steps=[
            StepResult(index=0, step=PlanStep(action=StepAction.GOTO, value="http://127.0.0.1:8765/"), status=RunStatus.PASSED),
            StepResult(index=1, step=PlanStep(action=StepAction.FILL, target="label=Password", value="{{secret:PW}}"),
                       status=RunStatus.PASSED),
            StepResult(index=2, step=CHECK, status=RunStatus.FAILED, error="Locator expected to contain text"),
        ],
    )
    return QARun(
        id=run_id, target_url="http://127.0.0.1:8765/", created_at=created_at, state=RunState.COMPLETED,
        browser="Chromium 1", results=[
            result("QA-001", "REQ-1", RunStatus.PASSED),
            failed,
            result("QA-003", "REQ-3", RunStatus.BLOCKED, reason="destructive", reason_params={"term": "delete"}),
            result("QA-004", "REQ-4", RunStatus.NOT_RUN, reason="not_approved"),
            result("QA-005", "REQ-5", RunStatus.PASSED),
            result("QA-006", "REQ-5", RunStatus.NOT_RUN, reason="not_approved"),
            result("QA-007", "REQ-X", RunStatus.PASSED),
        ],
    )


def test_coverage_by_requirement():
    rows = {row.requirement_id: row for row in coverage(sample_run(), REQUIREMENTS)}
    assert rows["REQ-1"].status == CoverageStatus.PASSED
    assert rows["REQ-2"].status == CoverageStatus.FAILED
    assert rows["REQ-3"].status == CoverageStatus.BLOCKED
    assert rows["REQ-4"].status == CoverageStatus.NOT_RUN
    assert rows["REQ-5"].status == CoverageStatus.PARTIAL
    assert rows["REQ-6"].status == CoverageStatus.NOT_COVERED
    assert rows["REQ-X"].status == CoverageStatus.PASSED  # not in the document, still reported


def test_bug_reports_only_for_failures_and_built_from_the_run():
    run = sample_run()
    bugs = generate_bugs(run)
    assert len(bugs) == 1
    bug = bugs[0]
    assert (bug.case_id, bug.requirement_id, bug.test_case_id) == ("QA-002", "REQ-2", "TC-002")
    assert bug.steps_to_reproduce == [
        "Open http://127.0.0.1:8765/", 'Fill "Password" with "[secret:PW]"', 'Verify the page shows "Email is required"',
    ]
    assert 'Verify the page shows "Email is required"' in bug.expected
    assert bug.actual == "Page shows Thanks" and bug.severity == Severity.MEDIUM
    assert "screenshot: 002-QA-002.png" in bug.evidence and "console: TypeError: x" in bug.evidence


def test_markdown_report_and_csvs():
    run = sample_run()
    run.bugs = generate_bugs(run)
    text = markdown_report(run, REQUIREMENTS)
    assert "| 3 | 1 | 1 | 2 | 75.0% | 1 |" in text  # 3 passed / (3 + 1 failed)
    assert "| REQ-2 | Requirement 2. | QA-002 | Failed |" in text
    assert "Stopped before a destructive action" in text
    assert "screenshots/002-QA-002.png" in text and run.bugs[0].id in text
    assert "Звіт" not in text and "QA-звіт" in markdown_report(run, REQUIREMENTS, "uk")
    run.results[0].title = "=HYPERLINK(\"http://x\")"
    assert "'=HYPERLINK" in results_csv(run)  # spreadsheet formula injection is neutralized
    assert "Steps to reproduce" in bugs_csv(run)


def test_bundle_contains_evidence_and_nothing_outside_the_run(tmp_path):
    run = sample_run()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "002-QA-002.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "secret.txt").write_text("do not ship")
    run.results[0].screenshot = "../secret.txt"
    archive = zipfile.ZipFile(io.BytesIO(bundle(run, run_dir, REQUIREMENTS)))
    names = set(archive.namelist())
    assert {"report.md", "run.json", "results.csv", "bugs.csv", "coverage.json", "screenshots/002-QA-002.png"} <= names
    assert not any("secret" in name for name in names)


def test_store_round_trip_listing_pruning_and_safe_paths(tmp_path):
    store = RunStore(tmp_path)
    for n in range(3):
        run = sample_run(f"{n:016x}", f"2026-10-1{n}T10:00:00+00:00")
        run.document_hash = "doc"
        store.save(run)
    assert [r.id for r in store.runs("doc")] == [f"{n:016x}" for n in (2, 1, 0)]
    assert store.runs("other") == []
    run = store.load(f"{2:016x}")
    assert run is not None and run.results[1].status == RunStatus.FAILED
    (store.run_dir(run.id) / "002-QA-002.png").write_bytes(b"png")
    assert store.evidence(run, "002-QA-002.png") is not None
    assert store.evidence(run, "../../x") is None and store.evidence(run, "run.json/..") is None
    with pytest.raises(ValueError):
        store.run_dir("../../etc")
    store.prune(keep=1)
    assert len(store.runs()) == 1
    plan = TestPlan(document_hash="doc", cases=[PlanCase(id="QA-001", requirement_id="REQ-1", title="t")])
    store.save_plan(plan)
    assert store.load_plan("doc") == plan and store.load_plan("missing") is None
    with pytest.raises(ValueError):
        store.save_plan(TestPlan(document_hash="../x"))


def test_session_mode_keeps_runs_in_a_private_folder(monkeypatch):
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE")
    state: dict = {}
    store = open_run_store(state, "default")
    other = open_run_store({}, "default")
    assert store.root != other.root  # another browser session never sees these runs
    assert oct(store.root.parent.stat().st_mode & 0o777) == "0o700"
    assert open_run_store(state, "default").root == store.root


def test_local_mode_keeps_runs_per_project(tmp_path):
    store = open_run_store({}, "proj1")
    assert store.root == tmp_path / "data" / "qa_agent" / "proj1"
    with pytest.raises(ValueError):
        open_run_store({}, "../x")


# --- Optional AI ------------------------------------------------------------------

class FakeClient:
    def __init__(self, steps):
        self.steps = steps
        self.prompts: list[str] = []


def fake_factory(steps):
    client = FakeClient(steps)

    def factory(config):
        return client

    return client, factory


def test_ai_proposals_are_validated_data(monkeypatch):
    client, factory = fake_factory(None)

    def fake_request(config, system, user, output, client_factory, max_tokens):
        client.prompts.append(system + user)
        return output.model_validate({"steps": [
            {"action": "goto", "value": "/login"},
            {"action": "fill", "target": "label=Password", "value": "{{secret:DEMO_PASSWORD}}"},
            {"action": "expect_text", "value": "Welcome"},
        ]})

    monkeypatch.setattr(qa_ai, "request_structured", fake_request)
    case = PlanCase(id="QA-001", requirement_id="REQ-1", title="Sign in")
    steps = qa_ai.suggest_steps(AIConfig(provider="anthropic", model="m"), case, "Sign in.", ["Log in"],
                                "http://127.0.0.1:8765/", ["DEMO_PASSWORD"], factory)
    assert [s.action for s in steps] == [StepAction.GOTO, StepAction.FILL, StepAction.EXPECT_TEXT]
    assert "DEMO_PASSWORD" in client.prompts[0]


@pytest.mark.parametrize(
    "bad",
    [
        {"action": "eval", "value": "document.cookie"},
        {"action": "click", "target": "", "value": ""},
        {"action": "expect_text", "value": "{{secret:X}}"},
    ],
)
def test_one_invalid_ai_step_rejects_the_whole_proposal(monkeypatch, bad):
    monkeypatch.setattr(qa_ai, "request_structured", lambda *a, **k: a[3].model_validate(
        {"steps": [{"action": "goto", "value": "/"}, bad]}))
    case = PlanCase(id="QA-001", requirement_id="REQ-1", title="x")
    with pytest.raises(AIError):
        qa_ai.suggest_steps(AIConfig(provider="anthropic", model="m"), case, "", [], "", [])
