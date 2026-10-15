from pathlib import Path

from streamlit.testing.v1 import AppTest

from conftest import goto, home
from spec_to_test.i18n import t
from spec_to_test.models import ReviewStatus

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


def open_tests_page(text: str) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    home(at).text_area(key="requirements_text").input(text).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    return goto(at, "tests")


def check(at: AppTest) -> str:
    [text] = [m.value for m in [*at.warning, *at.info] if "Before approving" in m.value or "Review of approved" in m.value]
    return text


def test_check_shows_critic_problems_and_missing_scenarios_before_approval():
    at = open_tests_page("REQ-1: The password must be at least 8 characters long.\n")
    text = check(at)
    assert "Before approving TC-001" in text
    assert "Critic problems:" in text and "**Steps**" in text
    assert "Scenario coverage of REQ-1 by Approved test cases: 0%." in text
    assert "Missing applicable scenarios: Happy Path, Boundary." in text
    assert "Approving this test case would cover: Happy Path." in text
    assert "Approval is not blocked" in text
    assert sum("Before approving" in m.value for m in [*at.warning, *at.info]) == 1  # shown once


def test_approval_with_problems_is_not_blocked_and_updates_the_check():
    at = open_tests_page("REQ-1: The password must be at least 8 characters long.\n")
    next(sb for sb in at.selectbox if sb.label == "Review status").set_value(ReviewStatus.APPROVED)
    next(b for b in at.button if b.label == "Save").click().run()
    assert not at.exception and not at.error
    saved = at.session_state["workspace"].test_cases[0]
    assert saved.review_status == ReviewStatus.APPROVED
    text = check(at)
    assert "Review of approved TC-001" in text and "Before approving" not in text
    assert "already Approved" in text and "Approval is not blocked" not in text
    assert "Critic problems:" in text  # findings stay visible, shown once
    assert "by Approved test cases: 50%." in text
    assert "Missing applicable scenarios: Boundary." in text
    assert "would cover" not in text


def test_review_mode_is_localized_and_other_statuses_keep_the_pre_approval_check():
    at = open_tests_page("REQ-1: The password must be at least 8 characters long.\n")
    next(sb for sb in at.selectbox if sb.label == "Review status").set_value(ReviewStatus.REVIEWED)
    next(b for b in at.button if b.label == "Save").click().run()
    assert at.session_state["workspace"].test_cases[0].review_status == ReviewStatus.REVIEWED
    assert "Before approving TC-001" in check(at) and "Approval is not blocked" in check(at)
    for lang, heading in (("uk", "Перегляд затвердженого TC-001"), ("ru", "Просмотр утверждённого TC-001")):
        assert t("approval.review_heading", lang, id="TC-001") == heading


def test_unknown_is_neither_a_problem_nor_coverage():
    at = open_tests_page("REQ-1: Fast and friendly login page.\n")
    text = check(at)
    problems, _, unknown = text.partition("Unknown — not enough data")
    assert "Requirement match" not in problems and "Requirement match" in unknown
    assert "Scenario coverage of REQ-1: Unknown" in text
    assert "Missing applicable scenarios" not in text
    assert "Unknown scenarios (counted neither as covered nor as missing): Happy Path." in text
