"""Grill Mode page, driven through Streamlit's AppTest (no browser, no AI)."""

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT
from spec_to_test.grill.models import GrillStep, load_session
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW
from spec_to_test.grill.workflow import GrillError
from spec_to_test.i18n import LANGUAGES, t
from spec_to_test.storage import load_latest
from test_localization import raw_keys, visible_text

APP_PATH = str(PROJECT_ROOT / "app.py")
REQS = """REQ-1: The password must be at least 8 characters.
REQ-2: The password must be at least 10 characters.
REQ-3: The page should load fast."""
BUG_DRAFT = """Summary: Save crashes the editor
Environment: Chrome 140
Steps to reproduce:
1. Open a document
2. Click Save
Actual result: The editor closes
Note to self: check logs"""


def new_app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    return at


def grill(at: AppTest | None = None) -> AppTest:
    at = at or new_app()
    at.sidebar.radio(key="app_mode").set_value("grill").run()
    assert not at.exception
    return at


def session_of(at: AppTest):
    return load_session(at.session_state["grill_session"])


def click(at: AppTest, key: str) -> AppTest:
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


def answer_text(at: AppTest, value: str) -> AppTest:
    box = next(a for a in at.text_area if a.key and a.key.startswith("grill_") and "_text_" in a.key)
    box.input(value)
    return click(at, "grill_answer")


def choose(at: AppTest, value: str) -> AppTest:
    radio = next(r for r in at.radio if r.key and "_choice_" in r.key)
    radio.set_value(value)
    return click(at, "grill_answer")


def start(at: AppTest, kind: str, mode: str | None = None, artifact: str | None = None,
          text_key: str | None = None, text: str = "") -> AppTest:
    at.radio(key="grill_kind").set_value(kind).run()
    if mode:
        at.radio(key="grill_mode").set_value(mode).run()
    if artifact:
        at.radio(key="grill_artifact").set_value(artifact).run()
    if text_key:
        at.text_area(key=text_key).input(text).run()
    return click(at, "grill_start")


# --- Navigation and compatibility ------------------------------------------------------

def test_app_still_starts_in_analysis_mode():
    at = new_app()
    assert at.sidebar.radio(key="app_mode").value == "analysis"
    assert at.button[0].label == "Analyze"
    assert at.sidebar.selectbox[0].label == t("sidebar.language")


def test_grill_mode_shows_workflow_choice_and_deterministic_label():
    at = grill()
    assert at.subheader[0].value == "Grill Mode"
    assert any(t("grill.ui.mode_deterministic") in info.value for info in at.info)
    assert at.radio(key="grill_kind").options == [
        "Clarify requirements", "Test case", "Bug report", "QA review",
    ]
    assert not any(b.label == "Analyze" for b in at.button)


def test_switching_back_restores_the_analysis_page():
    at = grill()
    at.sidebar.radio(key="app_mode").set_value("analysis").run()
    assert at.button[0].label == "Analyze" and not at.exception


# --- Requirements Grill ------------------------------------------------------------------

def test_requirements_grill_end_to_end_requires_explicit_confirmation():
    at = start(grill(), "requirements", text_key="grill_requirements_text", text=REQS)
    session = session_of(at)
    assert session.step == GrillStep.ASK_QUESTION
    assert any("Why it matters" in c.value for c in at.caption)
    assert any("REQ-1: The password must be at least 8 characters." in c.value for c in at.caption)
    assert at.button(key="grill_skip").disabled  # contradictions are essential

    choose(at, "REQ-1: The password must be at least 8 characters.")
    assert not at.button(key="grill_skip").disabled
    click(at, "grill_unknown")
    assert session_of(at).step == GrillStep.SHOW_DRAFT

    click(at, "grill_review_button")
    session = session_of(at)
    assert session.step == GrillStep.REVIEW and session.warning_findings
    assert at.button(key="grill_request_confirmation").disabled  # warnings not accepted yet
    next(c for c in at.checkbox if c.key and "_accept_" in c.key).check().run()
    click(at, "grill_request_confirmation")
    assert session_of(at).step == GrillStep.AWAITING_CONFIRMATION
    assert any(t("grill.ui.confirm_body") in c.value for c in at.caption)

    click(at, "grill_confirm_button")
    assert session_of(at).step == GrillStep.FINALIZED
    assert at.success[0].value == t("grill.ui.finalized")
    click(at, "grill_new")
    assert "grill_session" not in at.session_state


def test_requirements_grill_can_use_the_analyzed_document(example_text):
    at = new_app()
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
    at = grill(at)
    at.radio(key="grill_kind").set_value("review").run()
    at.radio(key="grill_artifact").set_value("requirements").run()
    assert at.checkbox(key="grill_use_analyzed").value is True
    click(at, "grill_start")
    session = session_of(at)
    assert session.step == GrillStep.REVIEW and len(session.draft.requirements) == 9
    assert session.findings


# --- Test Case Grill ---------------------------------------------------------------------

def test_test_case_interview_validates_answers_and_supports_back():
    at = grill()
    at.radio(key="grill_kind").set_value("test_case").run()
    assert any(t("grill.ui.context_missing") == c.value for c in at.caption)  # no document analyzed
    at = start(at, "test_case", mode="interview")
    click(at, "grill_skip")  # optional requirement ID
    assert session_of(at).current_question_id == "tc.feature"
    click(at, "grill_answer")  # empty answer
    assert at.error[0].value == t("grill.error.empty_answer")
    answer_text(at, "Password reset")
    assert session_of(at).current_question_id == "tc.title"
    click(at, "grill_back")
    assert session_of(at).current_question_id == "tc.feature"
    box = next(a for a in at.text_area if a.key and "_text_" in a.key)
    assert box.value == "Password reset"  # previous answer is shown for editing


def test_test_case_interview_reaches_draft_and_edits_mark_user_values():
    at = start(grill(), "test_case", mode="interview")
    click(at, "grill_skip")
    answer_text(at, "Password reset")
    answer_text(at, "Reset link is sent")
    click(at, "grill_to_draft")
    session = session_of(at)
    assert session.step == GrillStep.SHOW_DRAFT
    field_key = f"grill_{session.id}_field_{session.draft_revision}_steps"
    # Form values are sent together with the submit click, as in the browser.
    at.text_area(key=field_key).input("Open the reset page\nSubmit the email")
    next(b for b in at.button if b.label == t("grill.ui.save_draft")).click().run()
    session = session_of(at)
    assert session.draft.steps == ["Open the reset page", "Submit the email"]
    assert session.draft.provenance["steps"].value == "user_confirmed"


# --- Bug Report Grill and QA Review ---------------------------------------------------------

def test_bug_draft_review_shows_unparsed_lines_and_asks_only_for_gaps():
    at = start(grill(), "bug_report", mode="review_draft", text_key="grill_draft_text", text=BUG_DRAFT)
    session = session_of(at)
    assert session.draft.summary == "Save crashes the editor"
    assert "bug.summary" not in [q.id for q in session.questions]
    assert any(t("grill.ui.unparsed") in w.value for w in at.warning)
    assert at.code[0].value == "Note to self: check logs"
    assert session.current_question_id == "bug.app_version"


def test_qa_review_blocks_confirmation_until_blocking_issues_are_fixed():
    at = start(grill(), "review", artifact="bug_report", text_key="grill_draft_text", text=BUG_DRAFT)
    session = session_of(at)
    assert session.step == GrillStep.REVIEW and session.blocking_findings
    assert at.button(key="grill_request_confirmation").disabled
    assert any(t("grill.ui.blocked") == e.value for e in at.error)
    assert len(at.table) >= 2  # findings and the draft view


def test_input_errors_are_translated():
    at = grill()
    at.sidebar.selectbox[0].select("uk").run()
    start(at, "requirements")
    assert at.error[0].value == t("error.empty_input", "uk")
    assert "grill_session" not in at.session_state


# --- Session handling ------------------------------------------------------------------------

def test_session_survives_reruns_and_language_switches():
    at = start(grill(), "bug_report", mode="interview")
    before = session_of(at)
    at.run()
    at.sidebar.selectbox[0].select("ru").run()
    assert session_of(at) == before
    assert any(b.label == t("grill.ui.answer", "ru") for b in at.button)


def test_cancel_needs_a_second_click_and_discards_the_session():
    at = start(grill(), "bug_report", mode="interview")
    click(at, "grill_cancel")
    assert session_of(at).step == GrillStep.CANCELLED
    assert any(info.value == t("grill.ui.cancelled") for info in at.info)
    click(at, "grill_new")
    assert at.radio(key="grill_kind") is not None


def test_broken_state_is_reset_with_a_message():
    at = grill()
    at.session_state["grill_session"] = {"schema_version": 1, "kind": "nonsense"}
    at.run()
    assert not at.exception
    assert at.error[0].value == t("grill.ui.restore_failed")
    assert "grill_session" not in at.session_state


def test_double_click_from_an_outdated_page_is_rejected():
    at = start(grill(), "bug_report", mode="interview")
    revision = session_of(at).revision
    answer_text(at, "Crash on save")
    # The page passes the revision it was rendered with; an old one is refused.
    with pytest.raises(GrillError, match="stale_session"):
        DETERMINISTIC_WORKFLOW.answer(session_of(at), "again", expected_revision=revision)


def test_browser_sessions_do_not_share_grill_state():
    first = start(grill(), "bug_report", mode="interview")
    second = grill()
    assert "grill_session" in first.session_state
    assert "grill_session" not in second.session_state


def test_user_text_is_escaped_in_markdown():
    at = start(grill(), "requirements", text_key="grill_requirements_text",
               text="REQ-1: The [page](http://evil.example) should load fast.")
    captions = [c.value for c in at.caption]
    assert any(r"\[page\](http://evil.example)" in c or r"\[page\]\(http://evil.example\)" in c for c in captions)


# --- Using the finalized result ------------------------------------------------------------

TC_DRAFT = """Title: Reset link is sent
Requirement ID: REQ-2
Test type: positive
Steps:
1. Request a reset
2. Open the mailbox
Expected result: A reset link arrives in the mailbox"""


def analyzed(example_text: str) -> AppTest:
    at = new_app()
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
    return grill(at)


def confirm(at: AppTest) -> AppTest:
    """Review (if needed), accept open warnings and confirm."""
    if session_of(at).step != GrillStep.REVIEW:
        click(at, "grill_review_button")
    if accept := [c for c in at.checkbox if c.key and "_accept_" in c.key]:
        accept[0].check().run()
    click(at, "grill_request_confirmation")
    click(at, "grill_confirm_button")
    assert session_of(at).step == GrillStep.FINALIZED
    return at


def test_confirmed_test_case_is_added_to_the_analyzed_workspace(example_text):
    at = analyzed(example_text)
    before = len(at.session_state["workspace"].test_cases)
    at = confirm(start(at, "review", artifact="test_case", text_key="grill_draft_text", text=TC_DRAFT))
    assert len(at.get("download_button")) == 1
    click(at, "grill_add")
    workspace = at.session_state["workspace"]
    case = workspace.test_cases[-1]
    assert len(workspace.test_cases) == before + 1
    assert (case.title, case.requirement_id, case.source.value, case.review_status.value) == (
        "Reset link is sent", "REQ-2", "user", "draft")
    assert any(case.id in s.value for s in at.success)
    assert at.button(key="grill_add").disabled  # added once
    assert t("grill.error.already_added") in [c.value for c in at.caption]
    assert load_latest() == workspace  # saved like any other edit
    at.sidebar.radio(key="app_mode").set_value("analysis").run()
    assert not at.exception


def test_result_without_a_document_can_only_be_downloaded():
    at = confirm(start(grill(), "review", artifact="test_case", text_key="grill_draft_text", text=TC_DRAFT))
    assert len(at.get("download_button")) == 1
    assert at.button(key="grill_add").disabled
    assert t("grill.error.no_workspace") in [c.value for c in at.caption]
    assert "workspace" not in at.session_state


def test_requirements_grill_resolves_only_ticked_findings(example_text):
    at = analyzed(example_text)
    at.radio(key="grill_kind").set_value("requirements").run()
    at = click(at, "grill_start")
    assert session_of(at).current_question_id == "rule.missing_expected_result.REQ-1"
    answer_text(at, "A reset email is sent and a confirmation message is shown")
    at = confirm(at)
    boxes = [c for c in at.checkbox if c.key and "_resolve_" in c.key]
    assert len(boxes) == 1 and boxes[0].value is False  # opt-in, nothing ticked
    assert at.button(key="grill_resolve").disabled
    boxes[0].check().run()
    click(at, "grill_resolve")
    statuses = {f.key: f.status.value for f in at.session_state["workspace"].findings}
    assert statuses["REQ-1|missing_expected_result|"] == "resolved"
    assert statuses["REQ-1|missing_error_handling|"] == "needs_clarification"
    assert any(t("grill.ui.resolved", count=1) == s.value for s in at.success)
    assert t("grill.ui.no_resolutions") in [c.value for c in at.caption]


# --- Localization -------------------------------------------------------------------------------

def walk(lang: str) -> list[AppTest]:
    """Visit every Grill screen in one language."""
    at = grill()
    at.sidebar.selectbox[0].select(lang).run()
    screens = [at]
    start(at, "requirements", text_key="grill_requirements_text", text=REQS)
    screens.append(at)
    choose(at, "REQ-1: The password must be at least 8 characters.")
    click(at, "grill_to_draft")
    click(at, "grill_review_button")
    screens.append(at)
    next(c for c in at.checkbox if c.key and "_accept_" in c.key).check().run()
    click(at, "grill_request_confirmation")
    screens.append(at)
    click(at, "grill_confirm_button")
    screens.append(at)  # the finalized result with its download and hand-over options
    other = start(grill(), "test_case", mode="review_draft", text_key="grill_draft_text", text="Title: X")
    other.sidebar.selectbox[0].select(lang).run()
    click(other, "grill_to_draft")
    click(other, "grill_review_button")
    screens.append(other)
    return screens


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_every_grill_screen_is_translated(lang):
    for at in walk(lang):
        texts = visible_text(at) + [str(r.label) for r in at.radio] + [str(o) for r in at.radio for o in r.options]
        assert not raw_keys(texts), raw_keys(texts)
        if lang != "en":
            joined = "\n".join(texts)
            for english in ("Why it matters", "Save answer", "Run review", "Review findings", "Your answers"):
                assert english not in joined
