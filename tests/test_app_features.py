"""UI tests for the QA features (dashboard, RTM, editor, bugs, AI, export, persistence)."""

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT
from spec_to_test.models import ReviewStatus
from spec_to_test.storage import load_latest

APP_PATH = str(PROJECT_ROOT / "app.py")
TAB_LABELS = [
    "Requirements", "Findings", "Dashboard", "Traceability (RTM)", "Test cases",
    "Test design", "Bug reports", "AI analysis", "Automation", "Export",
]


def new_app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    return at


@pytest.fixture
def analyzed(example_text) -> AppTest:
    at = new_app()
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
    assert not at.exception
    return at


def table_with_column(at: AppTest, column: str):
    return next(df.value for df in at.table if column in df.value.columns)


def button(at: AppTest, key: str):
    return next(b for b in at.button if b.key == key)


def test_all_tabs_are_present(analyzed):
    assert [tab.label for tab in analyzed.tabs] == TAB_LABELS


def test_tabs_are_translated(analyzed):
    analyzed.sidebar.selectbox[0].select("uk").run()
    labels = [tab.label for tab in analyzed.tabs]
    assert "Дашборд" in labels and "Тест-кейси" in labels and "Аналіз ШІ" in labels
    analyzed.sidebar.selectbox[0].select("ru").run()
    assert not analyzed.exception
    assert "Баг-репорты" in [tab.label for tab in analyzed.tabs]


def test_requirements_show_quality_score(analyzed):
    requirements = table_with_column(analyzed, "Quality score")
    scores = dict(zip(requirements["ID"], requirements["Quality score"], strict=True))
    assert scores["REQ-2"] == 100
    assert scores["REQ-5"] < scores["REQ-2"]


def test_dashboard_metrics(analyzed):
    labels = {m.label: m.value for m in analyzed.metric}
    assert labels["Test cases"] != "0"
    assert labels["Coverage"] == "0%"  # nothing approved yet


def test_rtm_lists_every_requirement(analyzed):
    rtm = table_with_column(analyzed, "Approved tests")
    assert list(rtm["ID"]) == [f"REQ-{n}" for n in range(1, 10)]
    assert set(rtm["Coverage"]) == {"🟡 Partially covered"}


def test_edit_and_approve_test_case_updates_rtm_and_persists(analyzed):
    at = analyzed
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

    rtm = table_with_column(at, "Approved tests")
    row = rtm[rtm["ID"] == edited.requirement_id].iloc[0]
    assert edited.id in row["Approved tests"]
    assert row["Coverage"] == "✅ Covered"


def test_invalid_edit_is_rejected(analyzed):
    at = analyzed
    next(ti for ti in at.text_input if ti.label == "Title").input("   ")
    next(b for b in at.button if b.label == "Save").click().run()
    assert any("required" in e.value for e in at.error)


def test_add_and_delete_test_case(analyzed):
    at = analyzed
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
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
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


def test_work_is_restored_in_a_new_session(analyzed, example_text):
    button(analyzed, "bug_generate").click().run()
    at = new_app()  # simulates reopening the app
    assert any("Restored" in info.value for info in at.info)
    assert table_with_column(at, "Bug ID") is not None


def test_reanalyzing_same_document_keeps_edits(analyzed, example_text):
    button(analyzed, "bug_generate").click().run()
    count = len(load_latest().defects)
    analyzed.button[0].click().run()
    assert len(load_latest().defects) == count


# --- Regression tests for v1.0.0 fixes ---------------------------------------------------

def test_save_confirmation_survives_rerun(analyzed):
    at = analyzed
    next(ti for ti in at.text_input if ti.label == "Title").input("Renamed")
    next(b for b in at.button if b.label == "Save").click().run()
    assert any("saved" in toast.value for toast in at.toast)


def test_user_text_is_not_rendered_as_markdown():
    at = new_app()
    at.text_area[0].input("REQ-1: The system must show [help](http://x) and *all* items.").run()
    at.button[0].click().run()
    requirement = table_with_column(at, "Quality score")["Requirement"].iloc[0]
    assert requirement == r"The system must show \[help\](http://x) and \*all\* items."


def test_session_storage_mode_keeps_nothing_on_disk(example_text, monkeypatch, tmp_path):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "session")
    at = new_app()
    assert any("only for this browser session" in c.value for c in at.sidebar.caption)
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
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
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
    next(c for c in at.checkbox if c.key == "ai_consent").check().run()
    button(at, "ai_run").click().run()
    assert calls == [True]
    assert table_with_column(at, "Source quote") is not None
    assert next(c for c in at.checkbox if c.key == "ai_consent").value is False
    assert button(at, "ai_run").disabled


def test_ai_suggestion_to_bug_report_appears_immediately(example_text, monkeypatch):
    fake_ai(monkeypatch)
    at = new_app()
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
    next(c for c in at.checkbox if c.key == "ai_consent").check().run()
    button(at, "ai_run").click().run()
    button(at, "ai_to_bug").click().run()
    bugs = table_with_column(at, "Bug ID")
    assert list(bugs["Source"]) == ["AI suggestion"]
    assert load_latest().defects[0].origin_key == "ai|AI-001"


def test_new_document_resets_ai_consent(example_text, monkeypatch):
    fake_ai(monkeypatch)
    at = new_app()
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
    next(c for c in at.checkbox if c.key == "ai_consent").check().run()
    at.text_area[0].input("REQ-1: The system must save drafts.").run()
    at.button[0].click().run()
    assert next(c for c in at.checkbox if c.key == "ai_consent").value is False


def test_markdown_report_download_is_offered(analyzed):
    labels = [b.label for b in analyzed.get("download_button")]
    assert "QA report → Markdown" in labels
    assert len(labels) == 5


def test_version_is_shown(analyzed):
    from spec_to_test import __version__

    assert any(__version__ in c.value for c in analyzed.sidebar.caption)
