"""Grill Mode page, driven through Streamlit's AppTest (no browser, no AI)."""

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, home
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


def grill(at: AppTest | None = None, fresh: bool | None = None) -> AppTest:
    """Open the Grill page. In "local" storage mode a new browser session reopens the last
    unfinished interview; `fresh` (default: for a new app) closes it, keeping it saved."""
    fresh = at is None if fresh is None else fresh
    at = at or new_app()
    at.sidebar.radio(key="app_mode").set_value("grill").run()
    assert not at.exception
    if fresh and any(b.key == "grill_close" for b in at.button):
        at.button(key="grill_close").click().run()
    return at


def downloads(at: AppTest) -> list[str]:
    return [b.key for b in at.get("download_button")]


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

def test_app_starts_on_home():
    at = new_app()
    assert at.sidebar.radio(key="app_mode").value == "home"
    assert at.button(key="analyze").label == "Analyze"
    assert at.selectbox(key="language").label == t("sidebar.language")


def test_grill_mode_shows_workflow_choice_and_deterministic_label():
    at = grill()
    assert at.title[0].value == "Grill Mode"
    assert any(t("grill.ui.mode_deterministic") in info.value for info in at.info)
    assert at.radio(key="grill_kind").options == [
        "Clarify requirements", "Test case", "Bug report", "QA review",
    ]
    assert not any(b.label == "Analyze" for b in at.button)


def test_switching_back_restores_the_input_page():
    at = grill()
    at.sidebar.radio(key="app_mode").set_value("home").run()
    assert at.button(key="analyze").label == "Analyze" and not at.exception


# --- Requirements Grill ------------------------------------------------------------------

def test_requirements_grill_end_to_end_requires_explicit_confirmation():
    at = start(grill(), "requirements", text_key="grill_requirements_text", text=REQS)
    session = session_of(at)
    assert session.step == GrillStep.ASK_QUESTION
    assert any("Why it matters" in c.value for c in at.caption)
    assert any("> The password must be at least 8 characters." in m.value for m in at.markdown)  # current requirement
    assert any("REQ-2: The password must be at least 10 characters." in c.value for c in at.caption)  # also linked
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
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
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
    # No document: the essential feature question comes first, the free-text ID (low priority) later.
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
    assert session.current_question_id == "bug.expected_result"  # high priority before the version


def test_qa_review_blocks_confirmation_until_blocking_issues_are_fixed():
    at = start(grill(), "review", artifact="bug_report", text_key="grill_draft_text", text=BUG_DRAFT)
    session = session_of(at)
    assert session.step == GrillStep.REVIEW and session.blocking_findings
    assert at.button(key="grill_request_confirmation").disabled
    assert any(t("grill.ui.blocked") == e.value for e in at.error)
    assert len(at.table) >= 2  # findings and the draft view


def test_input_errors_are_translated():
    at = grill()
    at.selectbox(key="language").select("uk").run()
    start(at, "requirements")
    assert at.error[0].value == t("error.empty_input", "uk")
    assert "grill_session" not in at.session_state


# --- Session handling ------------------------------------------------------------------------

def test_session_survives_reruns_and_language_switches():
    at = start(grill(), "bug_report", mode="interview")
    before = session_of(at)
    at.run()
    at.selectbox(key="language").select("ru").run()
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


def test_browser_sessions_do_not_share_grill_state(monkeypatch):
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE")  # the default "session" mode of shared deployments
    first = start(grill(), "bug_report", mode="interview")
    second = grill(fresh=False)
    assert "grill_session" in first.session_state
    assert "grill_session" not in second.session_state
    assert not any(b.key.startswith("grill_resume_") for b in second.button)  # nothing listed either


def test_user_text_is_escaped_in_markdown():
    at = start(grill(), "requirements", text_key="grill_requirements_text",
               text="REQ-1: The [page](http://evil.example) should load fast.")
    texts = [c.value for c in at.caption] + [m.value for m in at.markdown]
    assert any(r"\[page\](http://evil.example)" in c or r"\[page\]\(http://evil.example\)" in c for c in texts)
    assert not any("[page](http://evil.example)" in c for c in texts)


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
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
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
    assert downloads(at).count("grill_download") == 1
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


OTHER_DOC = """REQ-1: The user must be able to log out.
REQ-2: The system must send a reset email within 5 minutes."""


def analyze_other_document(at: AppTest, document: str = OTHER_DOC) -> AppTest:
    """Leave Grill, analyze another document in Analysis mode and come back."""
    at.sidebar.radio(key="app_mode").set_value("analysis").run()
    home(at).text_area(key="requirements_text").input(document).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    return grill(at)


def test_changing_the_document_mid_session_does_not_move_the_result(example_text):
    at = analyzed(example_text)
    at = start(at, "review", artifact="test_case", text_key="grill_draft_text", text=TC_DRAFT)
    assert not [w for w in at.warning if w.value == t("grill.ui.context_changed")]
    at = analyze_other_document(at)  # same REQ-2, different document, session still open
    other = at.session_state["workspace"]
    assert other.requirement("REQ-2").text.startswith("The system must send a reset email")
    assert session_of(at) is not None
    assert t("grill.ui.context_changed") in [w.value for w in at.warning]  # said at once, not only at the end
    at = confirm(at)
    assert t("grill.ui.context_changed") in [w.value for w in at.warning]
    assert at.button(key="grill_add").disabled
    assert t("grill.error.context_changed") in [c.value for c in at.caption]
    assert downloads(at).count("grill_download") == 1  # the confirmed result is still available
    assert at.session_state["workspace"] == other  # nothing was moved into the new document
    assert not any(tc.source.value == "user" for tc in other.test_cases)
    click(at, "grill_new")
    assert t("grill.ui.context_changed") not in [w.value for w in at.warning]


def test_cancelled_session_gets_no_context_warning(example_text):
    at = analyzed(example_text)
    at = start(at, "review", artifact="test_case", text_key="grill_draft_text", text=TC_DRAFT)
    click(at, "grill_cancel")
    assert session_of(at).step == GrillStep.CANCELLED
    at = analyze_other_document(at)
    assert session_of(at).step == GrillStep.CANCELLED
    assert not [w for w in at.warning if w.value.startswith("The analyzed document changed")]
    assert not [w for w in at.warning if "Markdown" in w.value]  # nothing left to download


def test_session_started_without_a_document_warns_as_soon_as_one_is_analyzed(example_text):
    at = start(grill(), "review", artifact="test_case", text_key="grill_draft_text", text=TC_DRAFT)
    assert t("grill.ui.context_unknown") not in [w.value for w in at.warning]  # no document yet
    at = analyze_other_document(at, example_text)  # the document arrives after the session began
    assert session_of(at).step == GrillStep.REVIEW  # still mid-session, not finalized
    assert t("grill.ui.context_unknown") in [w.value for w in at.warning]
    at = confirm(at)
    assert t("grill.ui.context_unknown") in [w.value for w in at.warning]
    assert at.button(key="grill_add").disabled
    assert t("grill.error.context_unknown") in [c.value for c in at.caption]
    assert downloads(at).count("grill_download") == 1  # Markdown stays available


def test_interview_answers_survive_a_document_change_and_the_result_stays_out(example_text):
    at = analyzed(example_text)
    at = start(at, "test_case", mode="interview")
    choose(at, "REQ-2")
    answer_text(at, "Reset link is sent")
    answered = {qid: a.value for qid, a in session_of(at).answers.items()}
    assert answered["tc.title"] == "Reset link is sent"
    at = analyze_other_document(at)  # same REQ-2, other document, mid-interview
    session = session_of(at)
    assert session.step == GrillStep.ASK_QUESTION
    assert {qid: a.value for qid, a in session.answers.items()} == answered  # nothing was lost
    assert t("grill.ui.context_changed") in [w.value for w in at.warning]
    for question_id, value in (  # priority order: the optional objective comes last
        ("tc.test_type", "positive"), ("tc.steps", "Request a reset\nOpen the mailbox"),
        ("tc.expected_result", "A link arrives"), ("tc.objective", "Check the reset mail"),
    ):
        question = session_of(at).current_question
        while question is not None and question.id != question_id:  # optional questions are skipped
            click(at, "grill_skip")
            question = session_of(at).current_question
        assert question is not None
        if question.choices and not question.allow_free_text:
            choose(at, value)
        else:
            answer_text(at, value)
    while (question := session_of(at).current_question) is not None and session_of(at).step == GrillStep.ASK_QUESTION:
        assert not question.essential  # only optional questions are left
        click(at, "grill_skip")
    assert session_of(at).step == GrillStep.SHOW_DRAFT  # the last question handled opens the draft
    at = confirm(at)
    other = at.session_state["workspace"]
    assert session_of(at).draft.title == "Reset link is sent"
    assert at.button(key="grill_add").disabled
    assert t("grill.error.context_changed") in [c.value for c in at.caption]
    assert downloads(at).count("grill_download") == 1
    assert not any(tc.source.value == "user" for tc in other.test_cases)


def test_returning_to_the_original_document_makes_the_result_addable_again(example_text):
    at = analyzed(example_text)
    at = start(at, "review", artifact="test_case", text_key="grill_draft_text", text=TC_DRAFT)
    at = analyze_other_document(at)
    assert t("grill.ui.context_changed") in [w.value for w in at.warning]
    at = analyze_other_document(at, example_text)  # back to the document the session was started on
    assert t("grill.ui.context_changed") not in [w.value for w in at.warning]
    at = confirm(at)
    click(at, "grill_add")
    assert at.session_state["workspace"].test_cases[-1].requirement_id == "REQ-2"


def test_requirements_grill_on_pasted_text_still_resolves_findings(example_text):
    at = analyzed(example_text)
    at.radio(key="grill_kind").set_value("requirements").run()
    at.checkbox(key="grill_use_analyzed").uncheck().run()
    at.text_area(key="grill_requirements_text").input(example_text).run()  # typed in, so no context snapshot
    at = click(at, "grill_start")
    assert session_of(at).context_requirements == []
    assert session_of(at).current_question_id.startswith("rule.contradiction.")  # contradictions come first
    click(at, "grill_unknown")
    answer_text(at, "A reset email is sent and a confirmation message is shown")
    at = confirm(at)
    assert t("grill.ui.context_changed") not in [w.value for w in at.warning]
    boxes = [c for c in at.checkbox if c.key and "_resolve_" in c.key]
    assert len(boxes) == 1
    boxes[0].check().run()
    click(at, "grill_resolve")
    statuses = {f.key: f.status.value for f in at.session_state["workspace"].findings}
    assert statuses["REQ-1|missing_expected_result|"] == "resolved"


def test_result_without_a_document_can_only_be_downloaded():
    at = confirm(start(grill(), "review", artifact="test_case", text_key="grill_draft_text", text=TC_DRAFT))
    assert downloads(at).count("grill_download") == 1
    assert at.button(key="grill_add").disabled
    assert t("grill.error.no_workspace") in [c.value for c in at.caption]
    assert "workspace" not in at.session_state


def test_requirements_grill_resolves_only_ticked_findings(example_text):
    at = analyzed(example_text)
    at.radio(key="grill_kind").set_value("requirements").run()
    at = click(at, "grill_start")
    assert session_of(at).current_question_id == "rule.contradiction.REQ-4+REQ-7"  # contradictions come first
    click(at, "grill_unknown")
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
    at.selectbox(key="language").select(lang).run()
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
    other.selectbox(key="language").select(lang).run()
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
