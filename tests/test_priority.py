import csv
import io
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import goto, home
from spec_to_test import exports
from spec_to_test.migrations import migrate_workspace_data
from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestPriority, TestType, Workspace
from spec_to_test.suites import SuiteKind, plan_suites
from spec_to_test.test_generator import generate_test_cases

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")
REQ = Requirement(id="REQ-1", text="The user must log in.")


def tc(n: int, priority: TestPriority, test_type: TestType = TestType.POSITIVE,
       status: ReviewStatus = ReviewStatus.APPROVED) -> TestCase:
    return TestCase(id=f"TC-{n}", requirement_id="REQ-1", title=f"Case {n}", test_type=test_type,
                    steps=["Open the page."], expected_result="The page is shown.", review_status=status,
                    priority=priority)


def test_existing_and_generated_cases_are_medium():
    saved = Workspace(requirements=[REQ], test_cases=[tc(1, TestPriority.MEDIUM)]).model_dump(mode="json")
    del saved["test_cases"][0]["priority"]  # a save from before the field existed
    loaded = Workspace.model_validate(migrate_workspace_data(json.loads(json.dumps(saved))))
    assert loaded.test_cases[0].priority == TestPriority.MEDIUM
    ws = Workspace(requirements=[Requirement(id="REQ-1", text="The password must be at least 8 characters.")])
    assert {case.priority for case in generate_test_cases(ws)} == {TestPriority.MEDIUM}  # never High by heuristics


def test_smoke_keeps_high_and_medium_and_leaves_low_out():
    cases = [tc(1, TestPriority.HIGH), tc(2, TestPriority.MEDIUM), tc(3, TestPriority.LOW),
             tc(4, TestPriority.HIGH, TestType.NEGATIVE), tc(5, TestPriority.HIGH, status=ReviewStatus.REVIEWED)]
    plan = plan_suites(Workspace(requirements=[REQ], test_cases=cases))
    assert plan.suites[SuiteKind.SMOKE] == ["TC-1", "TC-2"]
    # Regression and Full do not look at priority.
    assert plan.suites[SuiteKind.REGRESSION] == ["TC-1", "TC-2", "TC-3", "TC-4"]
    assert plan.suites[SuiteKind.FULL] == ["TC-1", "TC-2", "TC-3", "TC-4", "TC-5"]
    only_low = plan_suites(Workspace(requirements=[REQ], test_cases=[tc(1, TestPriority.LOW)]))
    assert only_low.suites[SuiteKind.SMOKE] == [] and only_low.smoke_missing == ["REQ-1"]


def test_exports_carry_the_priority():
    ws = Workspace(requirements=[REQ], test_cases=[tc(1, TestPriority.HIGH), tc(2, TestPriority.LOW)])
    rows = list(csv.DictReader(io.StringIO(exports.testrail_csv(ws))))
    assert [row["Priority"] for row in rows] == ["High", "Low"]
    jira = list(csv.reader(io.StringIO(exports.jira_test_cases_csv(ws))))
    assert jira[0] == exports.JIRA_TEST_HEADERS  # column layout unchanged
    assert "*Priority:* high" in jira[1][2] and "*Priority:* low" in jira[2][2]


@pytest.mark.parametrize("storage", ["session", "local"])
def test_priority_survives_language_switch_and_document_switch(storage, monkeypatch):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", storage)
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    home(at).text_area(key="requirements_text").input("REQ-1: The user must log in.\n").run()
    home(at).button(key="analyze").click().run()
    first = at.session_state["workspace"].document_hash
    goto(at, "tests")
    next(sb for sb in at.selectbox if sb.label == "Priority").set_value(TestPriority.HIGH)
    next(b for b in at.button if b.label == "Save").click().run()
    assert not at.exception
    assert at.session_state["workspace"].test_cases[0].priority == TestPriority.HIGH

    at.selectbox(key="language").select("ru").run()
    assert not at.exception
    assert next(sb for sb in at.selectbox if sb.label == "Приоритет").value == TestPriority.HIGH
    assert "Высокий" in at.table[0].value["Приоритет"].tolist()

    home(at).text_area(key="requirements_text").input("REQ-1: The user can log out.\n").run()
    home(at).button(key="analyze").click().run()
    assert at.session_state["workspace"].test_cases[0].priority == TestPriority.MEDIUM
    at.sidebar.selectbox(key="project_document_select").set_value(first).run()
    reopened = at.session_state["workspace"]
    assert reopened.document_hash == first and reopened.test_cases[0].priority == TestPriority.HIGH
    rows = list(csv.DictReader(io.StringIO(exports.testrail_csv(reopened))))
    assert rows[0]["Priority"] == "High"
