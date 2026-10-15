from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import goto, home
from spec_to_test.i18n import t
from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestType, Workspace
from spec_to_test.rtm import build_rtm, traceability_gaps

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")

STATED = Requirement(id="REQ-1", text="The system must send a confirmation email.")
VAGUE = Requirement(id="REQ-2", text="Fast and friendly login page.")


def tc(n: int, rid: str, status: ReviewStatus = ReviewStatus.DRAFT) -> TestCase:
    return TestCase(id=f"TC-{n}", requirement_id=rid, title=f"Case {n}", test_type=TestType.POSITIVE,
                    steps=["Open the page."], expected_result="The email is sent.", review_status=status)


def gaps_of(ws: Workspace):
    return traceability_gaps(build_rtm(ws), ws)


def test_empty_workspace_has_no_gaps():
    gaps = gaps_of(Workspace())
    assert (gaps.untested, gaps.unknown, gaps.unlinked, gaps.gaps) == ([], [], [], 0)


def test_requirement_without_test_cases_is_a_gap():
    gaps = gaps_of(Workspace(requirements=[STATED]))
    assert gaps.untested == ["REQ-1"] and gaps.unknown == [] and gaps.gaps == 1
    # Any linked test case closes the gap, Approved or not (that is the RTM's coverage).
    assert gaps_of(Workspace(requirements=[STATED], test_cases=[tc(1, "REQ-1")])).gaps == 0


def test_unknown_is_reported_apart_and_not_counted_as_a_gap():
    gaps = gaps_of(Workspace(requirements=[STATED, VAGUE]))
    assert gaps.untested == ["REQ-1"] and gaps.unknown == ["REQ-2"]
    assert gaps.gaps == 1
    # A tested vague requirement is neither a gap nor Unknown here.
    gaps = gaps_of(Workspace(requirements=[VAGUE], test_cases=[tc(1, "REQ-2")]))
    assert (gaps.unknown, gaps.gaps) == ([], 0)


def test_test_cases_without_a_requirement_are_unlinked():
    ws = Workspace(requirements=[STATED], test_cases=[tc(1, "REQ-1"), tc(2, "REQ-9"), tc(3, "REQ-1-OLD")])
    gaps = gaps_of(ws)
    assert gaps.unlinked == ["TC-2", "TC-3"] and gaps.untested == [] and gaps.gaps == 2


@pytest.mark.parametrize("lang", ["en", "uk", "ru"])
def test_analysis_tab_shows_summary_and_lists(lang):
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    at.selectbox(key="language").select(lang).run()
    home(at).text_area(key="requirements_text").input(f"REQ-1: {STATED.text}\nREQ-2: {VAGUE.text}\n").run()
    home(at).button(key="analyze").click().run()
    ws = at.session_state["workspace"]
    ws.test_cases = [tc(1, "REQ-9")]  # REQ-1 and REQ-2 lose their cases; TC-1 points nowhere
    at.session_state["workspace"] = ws
    goto(at, "analysis")
    assert not at.exception
    assert t("tab.gaps", lang) in [tab.label for tab in at.tabs]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics[t("gaps.untested", lang)] == "1"
    assert metrics[t("gaps.unknown", lang)] == "1"
    assert metrics[t("gaps.unlinked", lang)] == "1"
    warnings = "\n".join(w.value for w in at.warning)
    assert t("gaps.untested_heading", lang) in warnings and "REQ-1" in warnings
    assert t("gaps.unlinked_heading", lang) in warnings
    assert "TC-1" in warnings and t("gaps.not_in_document", lang, req="REQ-9") in warnings
    unknown = next(i.value for i in at.info if t("gaps.unknown_heading", lang) in i.value)
    assert "REQ-2" in unknown and "REQ-2" not in warnings


def test_analysis_tab_says_when_nothing_is_missing():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    home(at).text_area(key="requirements_text").input(f"REQ-1: {STATED.text}\n").run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    assert any(t("gaps.none") in s.value for s in at.success)
