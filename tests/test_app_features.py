"""UI tests for the QA features (dashboard, RTM, editor, bugs, AI, export, persistence)."""

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto, home
from spec_to_test.models import ReviewStatus
from spec_to_test.storage import load_latest, load_pointer, save_workspace

APP_PATH = str(PROJECT_ROOT / "app.py")
PAGES = [
    "Home", "Requirements Analysis", "Grill Mode", "Test Cases", "QA Agent", "Traceability (RTM)",
    "Dashboard", "Export", "Settings",
]
ANALYSIS_TABS = ["Requirements", "Findings", "Traceability gaps", "Test design", "Bug reports", "AI analysis"]


def new_app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    return at


@pytest.fixture
def analyzed(example_text) -> AppTest:
    at = new_app()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    return at


def table_with_column(at: AppTest, column: str):
    return next(df.value for df in at.table if column in df.value.columns)


def button(at: AppTest, key: str):
    return next(b for b in at.button if b.key == key)


def nav_labels(at: AppTest) -> list[str]:
    # Options carry a Material icon before the name: ":material/x: Name".
    return [option.split(": ", 1)[1] for option in at.sidebar.radio(key="app_mode").options]


def test_analyze_opens_the_analysis_page(analyzed):
    assert analyzed.sidebar.radio(key="app_mode").value == "analysis"
    assert analyzed.title[0].value == "Requirements Analysis"


def test_every_page_and_tab_is_present(analyzed):
    assert nav_labels(analyzed) == PAGES
    assert [tab.label for tab in analyzed.tabs] == ANALYSIS_TABS
    assert [tab.label for tab in goto(analyzed, "tests").tabs] == ["Test cases", "Test suites", "Automation"]
    for page in ("rtm", "dashboard", "export", "settings", "grill", "home"):
        assert not goto(analyzed, page).exception


def test_pages_and_tabs_are_translated(analyzed):
    analyzed.selectbox(key="language").select("uk").run()
    assert "Дашборд" in nav_labels(analyzed) and "Тест-кейси" in nav_labels(analyzed)
    assert "Аналіз ШІ" in [tab.label for tab in analyzed.tabs]
    analyzed.selectbox(key="language").select("ru").run()
    assert not analyzed.exception
    assert "Баг-репорты" in [tab.label for tab in analyzed.tabs]


def test_pages_without_a_document_lead_to_home():
    at = new_app()
    for page in ("analysis", "tests", "rtm", "dashboard", "export"):
        goto(at, page)
        assert not at.exception
        assert any(b.key == f"{page}_go_home" for b in at.button)
    next(b for b in at.button if b.key == "export_go_home").click().run()
    assert at.sidebar.radio(key="app_mode").value == "home"


def test_header_settings_shortcut_opens_settings(analyzed):
    button(analyzed, "header_settings").click().run()
    assert analyzed.sidebar.radio(key="app_mode").value == "settings"
    assert button(analyzed, "header_settings").disabled


def test_requirements_show_quality_score(analyzed):
    requirements = table_with_column(analyzed, "Quality score")
    scores = dict(zip(requirements["ID"], requirements["Quality score"], strict=True))
    assert scores["REQ-2"] == 100
    assert scores["REQ-5"] < scores["REQ-2"]


def test_dashboard_metrics(analyzed):
    goto(analyzed, "dashboard")
    labels = {m.label: m.value for m in analyzed.metric}
    assert labels["Test cases"] != "0"
    assert labels["Coverage"] == "0%"  # nothing approved yet


def test_rtm_lists_every_requirement(analyzed):
    goto(analyzed, "rtm")
    rtm = table_with_column(analyzed, "Approved tests")
    assert list(rtm["ID"]) == [f"REQ-{n}" for n in range(1, 10)]
    assert set(rtm["Coverage"]) == {"🟡 Partially covered"}


def test_edit_and_approve_test_case_updates_rtm_and_persists(analyzed):
    at = goto(analyzed, "tests")
    form_inputs = [ti for ti in at.text_input if ti.label == "Title"]
    form_inputs[0].input("My edited title")
    review = next(sb for sb in at.selectbox if sb.label == "Review status")
    assert "Approved" in review.options
    review.set_value(ReviewStatus.APPROVED)
    form_submit = next(b for b in at.button if b.label == "Save")
    form_submit.click().run()
    assert not at.exception

    saved = load_latest()
    edited = next(tc for tc in saved.test_cases if tc.title == "My edited title")
    assert edited.review_status.value == "approved"

    rtm = table_with_column(goto(at, "rtm"), "Approved tests")
    row = rtm[rtm["ID"] == edited.requirement_id].iloc[0]
    assert edited.id in row["Approved tests"]
    assert row["Coverage"] == "✅ Covered"


def test_an_edit_does_not_overwrite_a_change_saved_elsewhere(analyzed):
    at = goto(analyzed, "tests")
    elsewhere = load_latest()  # e.g. the QA on-change run with --allow-write
    approved = elsewhere.test_cases[0].id
    elsewhere.test_cases[0].review_status = ReviewStatus.APPROVED
    save_workspace(elsewhere, load_pointer()[0], remember=False)
    count = len(elsewhere.test_cases)

    button(at, "tc_add").click().run()  # the app still holds the older copy
    assert not at.exception
    assert any("changed elsewhere" in toast.value for toast in at.toast)
    saved = load_latest()
    assert len(saved.test_cases) == count
    assert saved.test_cases[0].review_status == ReviewStatus.APPROVED
    # The app now shows the saved version, so the next edit keeps the change.
    button(at, "tc_add").click().run()
    saved = load_latest()
    assert len(saved.test_cases) == count + 1
    assert next(tc for tc in saved.test_cases if tc.id == approved).review_status == ReviewStatus.APPROVED


def test_invalid_edit_is_rejected(analyzed):
    at = goto(analyzed, "tests")
    next(ti for ti in at.text_input if ti.label == "Title").input("   ")
    next(b for b in at.button if b.label == "Save").click().run()
    assert any("required" in e.value for e in at.error)


def test_add_and_delete_test_case(analyzed):
    at = goto(analyzed, "tests")
    before = len(load_latest().test_cases)
    button(at, "tc_add").click().run()
    after_add = load_latest().test_cases
    assert len(after_add) == before + 1
    new_id = after_add[-1].id

    confirm = next(cb for cb in at.checkbox if cb.key == f"tc_confirm_{new_id}")
    assert button(at, f"tc_delete_{new_id}").disabled
    confirm.check().run()
    button(at, f"tc_delete_{new_id}").click().run()
    assert new_id not in {tc.id for tc in load_latest().test_cases}
    assert not at.exception


def test_generate_bug_reports(analyzed):
    at = analyzed
    button(at, "bug_generate").click().run()
    defects = load_latest().defects
    assert defects and defects[0].id == "BUG-001"
    bugs = table_with_column(at, "Bug ID")
    assert list(bugs["Bug ID"]) == [d.id for d in defects]
    # Generating again does not duplicate.
    button(at, "bug_generate").click().run()
    assert len(load_latest().defects) == len(defects)


def test_ai_tab_without_key_explains_setup(analyzed):
    assert any("AI is not configured" in info.value for info in analyzed.info)
    assert not any(b.key == "ai_run" for b in analyzed.button)


def test_ai_run_requires_consent(example_text, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    at = new_app()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    assert button(at, "ai_run").disabled
    assert not any("test-key-123" in str(el.value) for el in at.markdown)


def test_test_design_tab_shows_boundaries(analyzed):
    at = analyzed
    design = next(sb for sb in at.selectbox if sb.key == "design_req")
    design.select("REQ-4").run()
    assert any("Boundary value analysis" in md.value for md in at.markdown)
    design.select("REQ-8").run()
    assert any("Decision table" in md.value for md in at.markdown)
    assert any("no outcome" in w.value for w in at.warning)


PARTIAL_DESIGN = (
    "Partial check: only “at least 8 characters” is varied. REQ-4 also states other conditions that these values "
    "do not check: “contain one digit”. Each test value must meet them, otherwise the expectation above does not apply."
)


def test_test_design_marks_values_that_check_part_of_the_requirement(analyzed):
    at = analyzed
    design = next(sb for sb in at.selectbox if sb.key == "design_req")
    # REQ-4: "at least 8 characters long and contain one digit". Before: the length values with no caveat,
    # while its boundary and equivalence test cases already carried the partial-check assumption.
    design.select("REQ-4").run()
    warnings = [w.value.replace("\\", "") for w in at.warning]
    assert warnings.count(PARTIAL_DESIGN) == 2  # under the boundary values and under the classes
    # REQ-7: "at least 10 characters long" has nothing else to check.
    design.select("REQ-7").run()
    assert any("Boundary value analysis" in md.value for md in at.markdown)
    assert not any("Partial check" in w.value for w in at.warning)


def test_rtm_names_the_condition_no_test_case_names(analyzed):
    rtm = table_with_column(goto(analyzed, "rtm"), "Conditions no test case names")
    unchecked = dict(zip(rtm["ID"], rtm["Conditions no test case names"], strict=True))
    assert unchecked == {**{f"REQ-{n}": "—" for n in range(1, 10)}, "REQ-4": "“contain one digit”"}
    # Statuses stay as they were.
    assert set(rtm["Coverage"]) == {"🟡 Partially covered"}


def test_work_is_restored_in_a_new_session(analyzed, example_text):
    button(analyzed, "bug_generate").click().run()
    at = new_app()  # simulates reopening the app
    assert any("Restored" in info.value for info in at.info)
    assert table_with_column(goto(at, "analysis"), "Bug ID") is not None


def test_reanalyzing_same_document_keeps_edits(analyzed, example_text):
    button(analyzed, "bug_generate").click().run()
    count = len(load_latest().defects)
    home(analyzed).button(key="analyze").click().run()
    assert len(load_latest().defects) == count


# --- Regression tests for v1.0.0 fixes ---------------------------------------------------

def test_save_confirmation_survives_rerun(analyzed):
    at = goto(analyzed, "tests")
    next(ti for ti in at.text_input if ti.label == "Title").input("Renamed")
    next(b for b in at.button if b.label == "Save").click().run()
    assert any("saved" in toast.value for toast in at.toast)


def test_user_text_is_not_rendered_as_markdown():
    at = new_app()
    home(at).text_area(key="requirements_text").input("REQ-1: The system must show [help](http://x) and *all* items.").run()
    home(at).button(key="analyze").click().run()
    requirement = table_with_column(at, "Quality score")["Requirement"].iloc[0]
    assert requirement == r"The system must show \[help\](http://x) and \*all\* items."


def test_session_storage_mode_keeps_nothing_on_disk(example_text, monkeypatch, tmp_path):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "session")
    at = new_app()
    assert any("only for this browser session" in c.value for c in at.sidebar.caption)
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    assert not (tmp_path / "data").exists()
    assert not any("Restored" in info.value for info in new_app().info)


def fake_ai(monkeypatch):
    from spec_to_test import ai_analysis
    from spec_to_test.models import AISuggestion, AISuggestionType

    calls = []

    def fake_run(requirements, config, consent, lang="en", **kwargs):
        calls.append(consent)
        return [
            AISuggestion(id="AI-001", type=AISuggestionType.AMBIGUITY, requirement_ids=["REQ-5"],
                         description="'fast' is not measurable.", quote="load fast", quote_verified=True)
        ]

    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    monkeypatch.setattr(ai_analysis, "run_ai_analysis", fake_run)
    return calls


def test_ai_consent_is_required_again_for_every_run(example_text, monkeypatch):
    calls = fake_ai(monkeypatch)
    at = new_app()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    next(c for c in at.checkbox if c.key == "ai_consent").check().run()
    button(at, "ai_run").click().run()
    assert calls == [True]
    assert table_with_column(at, "Source quote") is not None
    assert next(c for c in at.checkbox if c.key == "ai_consent").value is False
    assert button(at, "ai_run").disabled


def test_ai_suggestion_to_bug_report_appears_immediately(example_text, monkeypatch):
    fake_ai(monkeypatch)
    at = new_app()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    next(c for c in at.checkbox if c.key == "ai_consent").check().run()
    button(at, "ai_run").click().run()
    button(at, "ai_to_bug").click().run()
    bugs = table_with_column(at, "Bug ID")
    assert list(bugs["Source"]) == ["AI suggestion"]
    assert load_latest().defects[0].origin_key == "ai|AI-001"


def test_new_document_resets_ai_consent(example_text, monkeypatch):
    fake_ai(monkeypatch)
    at = new_app()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    next(c for c in at.checkbox if c.key == "ai_consent").check().run()
    home(at).text_area(key="requirements_text").input("REQ-1: The system must save drafts.").run()
    home(at).button(key="analyze").click().run()
    assert next(c for c in at.checkbox if c.key == "ai_consent").value is False


def test_markdown_report_download_is_offered(analyzed):
    goto(analyzed, "export")
    labels = [b.label for b in analyzed.get("download_button")]
    assert "QA report → Markdown" in labels
    assert len(labels) == 5


def test_version_is_shown(analyzed):
    from spec_to_test import __version__

    assert any(__version__ in c.value for c in analyzed.sidebar.caption)
