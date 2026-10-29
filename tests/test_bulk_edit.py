"""Search, filters and bulk actions over test cases: the rules, and the editor page that uses them."""

from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto, home
from spec_to_test.bulk_edit import delete_cases, filter_cases, matches, set_review_status
from spec_to_test.models import ReviewStatus, TestCase, TestType, Workspace
from spec_to_test.storage import load_latest

APP_PATH = str(PROJECT_ROOT / "app.py")


def case(n: int, title: str, steps=("Open the page.",), expected="The page opens.",
         status=ReviewStatus.DRAFT) -> TestCase:
    return TestCase(id=f"TC-{n}", requirement_id="REQ-1", title=title, test_type=TestType.POSITIVE,
                    steps=list(steps), expected_result=expected, review_status=status)


def test_a_search_needs_every_word_and_looks_at_id_title_steps_and_result():
    tc = case(1, "Login with a valid password", steps=("Type the password.",), expected="Dashboard is shown")
    assert matches(tc, "")
    assert matches(tc, "tc-1 login")  # ID and title
    assert matches(tc, "password dashboard")  # steps and result
    assert not matches(tc, "login logout")  # every word must appear


def test_the_status_filter_keeps_only_the_chosen_statuses():
    cases = [case(1, "a", status=ReviewStatus.DRAFT), case(2, "b", status=ReviewStatus.APPROVED)]
    assert [c.id for c in filter_cases(cases, statuses={ReviewStatus.APPROVED})] == ["TC-2"]
    assert [c.id for c in filter_cases(cases)] == ["TC-1", "TC-2"]  # no filter: everything


def test_a_bulk_status_change_touches_only_the_chosen_cases_and_counts_real_changes():
    ws = Workspace(test_cases=[case(1, "a"), case(2, "b", status=ReviewStatus.REVIEWED), case(3, "c")])
    changed = set_review_status(ws, ["TC-1", "TC-2"], ReviewStatus.REVIEWED)
    assert changed == 1  # TC-2 already had the status
    assert [c.review_status for c in ws.test_cases] == [ReviewStatus.REVIEWED, ReviewStatus.REVIEWED, ReviewStatus.DRAFT]


def test_a_bulk_delete_removes_only_the_chosen_cases():
    ws = Workspace(test_cases=[case(1, "a"), case(2, "b"), case(3, "c")])
    assert delete_cases(ws, ["TC-2", "TC-404"]) == 1
    assert [c.id for c in ws.test_cases] == ["TC-1", "TC-3"]


def analyzed_app(example_text) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    return at


def test_the_editor_searches_and_bulk_changes_the_saved_statuses(example_text):
    at = goto(analyzed_app(example_text), "tests")
    search = next(ti for ti in at.text_input if ti.label == "Search ID, title, steps or expected result")
    search.input("REQ-3").run()
    table = next(d.value for d in at.table if "Test ID" in d.value.columns)
    assert set(table["ID"]) == {"REQ-3"}  # the search narrows the table to the requirement's cases
    chosen = next(ms for ms in at.multiselect if ms.label == "Test cases to change")
    picked = chosen.options[0].split(" — ")[0]  # options show "ID — title"
    chosen.select(picked).run()
    next(b for b in at.button if b.label == "Set to Reviewed").click().run()
    assert not at.exception
    assert any("set to Reviewed" in t.value for t in at.toast)
    saved = next(tc for tc in load_latest().test_cases if tc.id == picked)
    assert saved.review_status == ReviewStatus.REVIEWED


def test_a_bulk_delete_needs_the_confirmation_and_then_removes_the_chosen_cases(example_text):
    at = goto(analyzed_app(example_text), "tests")
    before = len(load_latest().test_cases)
    chosen = next(ms for ms in at.multiselect if ms.label == "Test cases to change")
    chosen.select(chosen.options[0]).run()
    button = next(b for b in at.button if b.label == "Delete chosen test cases")
    assert button.disabled
    next(c for c in at.checkbox if c.label.startswith("Delete these 1 test case")).check().run()
    next(b for b in at.button if b.label == "Delete chosen test cases").click().run()
    assert not at.exception
    assert len(load_latest().test_cases) == before - 1
