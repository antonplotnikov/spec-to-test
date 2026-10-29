"""The analysis page: confirm a recommendation, see it in the table, and get refused a second final decision."""

import json

from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto, home
from spec_to_test.storage import data_dir, load_latest

APP_PATH = str(PROJECT_ROOT / "app.py")
FIRST = ("Login spec\nREQ-1: The user must log in with a password.\n"
         "REQ-2: The session must expire after 30 minutes.\n")
CHANGED = FIRST.replace("30 minutes", "15 minutes")


def changed_document_app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    home(at).text_area(key="requirements_text").input(FIRST).run()
    home(at).button(key="analyze").click().run()
    home(at).text_area(key="requirements_text").input(CHANGED).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    return at


def test_a_recommendation_is_accepted_shown_and_cannot_be_decided_twice_without_a_change(tmp_path):
    at = changed_document_app()
    cases_before = [(tc.id, tc.review_status) for tc in load_latest().test_cases]

    next(s for s in at.selectbox if s.label == "Requirement").select("REQ-2")
    next(b for b in at.button if b.label == "Accept").click().run()
    assert not at.exception
    assert any("Decision DEC-001 saved: Accepted" in t.value for t in at.toast)

    decisions = json.loads((data_dir() / "impact_decisions.json").read_text(encoding="utf-8"))["decisions"]
    assert [(d["requirement_id"], d["decision"]) for d in decisions] == [("REQ-2", "accepted")]

    rows = next(d.value for d in at.table if "Decision" in d.value.columns)
    assert dict(zip(rows["ID"], rows["Decision"], strict=True)).get("REQ-2") == "Accepted"

    next(s for s in at.selectbox if s.label == "Requirement").select("REQ-2")
    next(b for b in at.button if b.label == "Reject").click().run()
    assert any("already has a current decision" in t.value for t in at.toast)
    assert len(json.loads((data_dir() / "impact_decisions.json").read_text(encoding="utf-8"))["decisions"]) == 1

    # Confirming changes no test case status.
    assert [(tc.id, tc.review_status) for tc in load_latest().test_cases] == cases_before
    goto(at, "rtm")  # the page still draws after the decisions
    assert not at.exception
