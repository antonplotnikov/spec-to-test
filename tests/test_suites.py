import csv
import io
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import goto, home
from spec_to_test import exports
from spec_to_test.i18n import t
from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestType, Workspace
from spec_to_test.suites import SuiteKind, plan_suites, suite_workspace

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")

REQS = [Requirement(id="REQ-1", text="The user must log in."), Requirement(id="REQ-2", text="The user can log out.")]


def tc(n: int, rid: str, test_type: TestType, status: ReviewStatus) -> TestCase:
    return TestCase(id=f"TC-{n}", requirement_id=rid, title=f"Case {n}", test_type=test_type,
                    steps=["Open the page."], expected_result="The page is shown.", review_status=status)


CASES = [
    tc(1, "REQ-1", TestType.POSITIVE, ReviewStatus.APPROVED),
    tc(2, "REQ-1", TestType.NEGATIVE, ReviewStatus.APPROVED),
    tc(3, "REQ-1", TestType.BOUNDARY, ReviewStatus.REVIEWED),
    tc(4, "REQ-2", TestType.POSITIVE, ReviewStatus.DRAFT),
]


def test_empty_workspace_gives_empty_suites():
    plan = plan_suites(Workspace())
    assert plan.suites == {kind: [] for kind in SuiteKind} and plan.smoke_missing == []
    # Requirements without test cases: nothing to run, and Smoke says nothing about them.
    plan = plan_suites(Workspace(requirements=REQS))
    assert all(not ids for ids in plan.suites.values()) and plan.smoke_missing == ["REQ-1", "REQ-2"]


def test_suites_follow_type_and_review_status():
    plan = plan_suites(Workspace(requirements=REQS, test_cases=CASES))
    assert plan.suites[SuiteKind.FULL] == ["TC-1", "TC-2", "TC-3", "TC-4"]
    assert plan.suites[SuiteKind.REGRESSION] == ["TC-1", "TC-2"]  # Approved only
    assert plan.suites[SuiteKind.SMOKE] == ["TC-1"]  # Approved and Positive
    # REQ-2's happy path is still a Draft, so Smoke does not represent REQ-2.
    assert plan.smoke_missing == ["REQ-2"]


@pytest.mark.parametrize("status", [ReviewStatus.DRAFT, ReviewStatus.REVIEWED])
def test_only_approved_cases_reach_smoke_and_regression(status):
    plan = plan_suites(Workspace(requirements=REQS[:1], test_cases=[tc(1, "REQ-1", TestType.POSITIVE, status)]))
    assert plan.suites[SuiteKind.SMOKE] == plan.suites[SuiteKind.REGRESSION] == []
    assert plan.suites[SuiteKind.FULL] == ["TC-1"] and plan.smoke_missing == ["REQ-1"]


def suites_tab(lang: str) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.selectbox(key="language").select(lang).run()
    home(at).text_area(key="requirements_text").input("REQ-1: The user must log in.\nREQ-2: The user can log out.\n").run()
    home(at).button(key="analyze").click().run()
    ws = at.session_state["workspace"]
    ws.test_cases = CASES
    at.session_state["workspace"] = ws
    goto(at, "tests")
    assert not at.exception
    return at


@pytest.mark.parametrize("lang", ["en", "uk", "ru"])
def test_tab_shows_counts_and_states_what_smoke_cannot_know(lang):
    at = suites_tab(lang)
    assert t("tab.suites", lang) in [tab.label for tab in at.tabs]
    metrics = {m.label: m.value for m in at.metric}
    assert [metrics[t(f"suites.{k.value}", lang)] for k in SuiteKind] == ["1", "2", "4"]
    assert any(t("suites.no_criticality", lang) == i.value for i in at.info)
    assert any(t("suites.smoke_missing", lang, ids="REQ-2") == w.value for w in at.warning)


def test_tab_lists_the_selected_suite():
    at = suites_tab("en")
    def listed() -> list[str]:
        return [str(v) for v in at.table[-1].value["Test ID"]]
    assert listed() == ["TC-1"]  # Smoke first
    at.selectbox(key="suite_kind").set_value(SuiteKind.REGRESSION).run()
    assert listed() == ["TC-1", "TC-2"]
    at.selectbox(key="suite_kind").set_value(SuiteKind.FULL).run()
    assert listed() == ["TC-1", "TC-2", "TC-3", "TC-4"]


def test_tab_without_test_cases_says_no_suite_can_be_formed():
    at = suites_tab("en")
    ws = at.session_state["workspace"]
    ws.test_cases = []
    at.session_state["workspace"] = ws
    at.run()
    assert any(t("suites.no_test_cases") == i.value for i in at.info)
    assert not any(m.label == t("suites.smoke") for m in at.metric)


def exported(text: str, column: str) -> list[str]:
    return [row[column] for row in csv.DictReader(io.StringIO(text))]


@pytest.mark.parametrize(("kind", "ids"), [
    (SuiteKind.SMOKE, ["TC-1"]),
    (SuiteKind.REGRESSION, ["TC-1", "TC-2"]),
    (SuiteKind.FULL, ["TC-1", "TC-2", "TC-3", "TC-4"]),
])
def test_suite_export_holds_only_the_suite_cases(kind, ids):
    ws = Workspace(requirements=REQS, test_cases=CASES)
    suite = suite_workspace(ws, kind)
    assert [s.split("]")[0].lstrip("[") for s in exported(exports.jira_test_cases_csv(suite), "Summary")] == ids
    assert exported(exports.testrail_csv(suite), "Title") == [f"Case {i.split('-')[1]}" for i in ids]
    assert [tc.id for tc in ws.test_cases] == ["TC-1", "TC-2", "TC-3", "TC-4"]  # the document is untouched


def test_empty_suite_exports_only_the_header():
    ws = Workspace(requirements=REQS, test_cases=[tc(1, "REQ-1", TestType.NEGATIVE, ReviewStatus.DRAFT)])
    for kind in (SuiteKind.SMOKE, SuiteKind.REGRESSION):
        suite = suite_workspace(ws, kind)
        assert suite.test_cases == []
        assert exported(exports.jira_test_cases_csv(suite), "Summary") == exported(exports.testrail_csv(suite), "Title") == []


def test_tab_offers_export_of_the_selected_suite_only_when_it_has_cases():
    at = suites_tab("en")
    def labels() -> list[str]:
        return [b.proto.label for b in at.get("download_button")]
    assert {"Smoke suite → Jira CSV", "Smoke suite → TestRail CSV"} <= set(labels())
    at.selectbox(key="suite_kind").set_value(SuiteKind.FULL).run()
    assert "Full suite → Jira CSV" in labels() and "Smoke suite → Jira CSV" not in labels()
    ws = at.session_state["workspace"]
    ws.test_cases = [tc(1, "REQ-1", TestType.NEGATIVE, ReviewStatus.DRAFT)]
    at.session_state["workspace"] = ws
    at.selectbox(key="suite_kind").set_value(SuiteKind.SMOKE).run()
    assert any(t("suites.empty") == i.value for i in at.info)
    assert not any("suite →" in label for label in labels())
