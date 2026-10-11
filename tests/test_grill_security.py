"""Grill Mode security checks: no network without AI, bounded input, safe output."""

import csv
import io
import time

import pytest
from streamlit.testing.v1 import AppTest
from test_grill_integration import bug_draft, reviewed, tc_draft

from conftest import PROJECT_ROOT
from spec_to_test import exports
from spec_to_test.exports import jira_defects_csv, jira_test_cases_csv
from spec_to_test.grill.drafts import DraftError, draft_from_text
from spec_to_test.grill.inputs import parse_draft
from spec_to_test.grill.integration import add_to_workspace, result_markdown
from spec_to_test.grill.models import AnswerStatus, BugReportDraft, GrillKind, TestCaseDraft
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.grill.workflow import GrillError
from spec_to_test.input_parser import MAX_TEXT_CHARS
from spec_to_test.models import Requirement, Severity, TestType, Workspace

HOSTILE = "=HYPERLINK(\"http://evil.example\",\"x\") <script>alert(1)</script> ![x](http://evil.example/p.png)"


def workspace() -> Workspace:
    return Workspace(requirements=[Requirement(id="REQ-1", text="The password must be at least 8 characters.")])


def test_grill_flow_makes_no_network_calls_without_ai(no_network):
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30)
    at.run()
    at.sidebar.radio(key="app_mode").set_value("grill").run()
    at.radio(key="grill_kind").set_value("requirements").run()
    at.text_area(key="grill_requirements_text").input("REQ-1: The page should load fast.").run()
    at.button(key="grill_start").click().run()
    at.button(key="grill_review_button").click().run()
    assert not at.exception


def test_api_key_never_enters_the_grill_session(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-very-secret-123")
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30)
    at.run()
    at.sidebar.radio(key="app_mode").set_value("grill").run()
    at.radio(key="grill_kind").set_value("test_case").run()
    at.button(key="grill_start").click().run()
    assert not at.exception
    stored = repr(at.session_state.to_dict())
    assert "grill_session" in stored
    assert "test-key-very-secret-123" not in stored


def test_too_long_answers_and_fields_are_rejected():
    session = WF.submit_input(WF.start(GrillKind.TEST_CASE), TestCaseDraft())
    with pytest.raises(GrillError) as error:
        WF.answer(session, "x" * (MAX_TEXT_CHARS + 1))
    assert error.value.code == "too_long"
    assert WF.answer(session, "x" * MAX_TEXT_CHARS).revision == session.revision + 1
    for field in ("title", "steps"):
        with pytest.raises(DraftError) as draft_error:
            draft_from_text(TestCaseDraft(), {field: "x" * (MAX_TEXT_CHARS + 1)})
        assert draft_error.value.code == "too_long"


def test_assumed_answers_are_bounded_too():
    session = WF.submit_input(WF.start(GrillKind.TEST_CASE), TestCaseDraft())
    with pytest.raises(GrillError):
        WF.answer(session, "x" * (MAX_TEXT_CHARS + 1), AnswerStatus.ASSUMED)


def test_pathological_drafts_do_not_hang():
    start = time.perf_counter()
    for text in ["a" * 99_000, ":" * 99_000, "1." * 49_000, "Steps:" + "\n- x" * 24_000, "*" * 99_000 + ":"]:
        parse_draft(text, BugReportDraft)
    assert time.perf_counter() - start < 5


def test_grill_items_cannot_inject_spreadsheet_formulas():
    ws = workspace()
    ws, _ = add_to_workspace(reviewed(tc_draft(title=HOSTILE, test_type=TestType.NEGATIVE,
                                                expected_result="An error is shown"), ws), ws)
    ws, _ = add_to_workspace(reviewed(bug_draft(summary="@SUM(A1:A9)", severity=Severity.LOW), ws), ws)
    for export in (jira_test_cases_csv(ws), exports.testrail_csv(ws), jira_defects_csv(ws.defects)):
        cells = [cell for row in csv.reader(io.StringIO(export)) for cell in row]
        assert not [cell for cell in cells if cell.startswith(("=", "+", "-", "@"))]
    assert "'=HYPERLINK" in exports.testrail_csv(ws)


def test_markdown_download_shows_hostile_text_literally():
    md = result_markdown(reviewed(tc_draft(title=HOSTILE), workspace()))
    assert "<script>" not in md and r"\<script\>" in md
    assert "![x](" not in md
