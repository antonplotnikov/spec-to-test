"""Unified interview on the Grill page without any API key: priority, requirement, testing impact,
states, unresolved issues, contradictions and the final report (AppTest)."""

import pytest
from test_grill_ui import answer_text, choose, click, grill, session_of, start

from spec_to_test.grill.models import GrillStep
from spec_to_test.i18n import LANGUAGES, t
from test_localization import raw_keys, visible_text

REQS = """REQ-1: The password must be at least 8 characters.
REQ-2: The password must be at least 10 characters.
REQ-3: Users can upload a profile photo."""


def started(lang: str = "en"):
    at = grill()
    if lang != "en":
        at.selectbox(key="language").select(lang).run()
    return start(at, "requirements", text_key="grill_requirements_text", text=REQS)


def captions(at) -> list[str]:
    return [c.value for c in at.caption]


def metrics(at) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def badges(at) -> str:
    return "\n".join(m.value for m in at.markdown if "-badge[" in m.value)


def issues(at):
    return next(e for e in at.expander if e.label.startswith(t("grill.ui.issues_heading", count=0).split("(")[0]))


def test_question_shows_priority_requirement_impact_and_progress_states():
    at = started()
    session = session_of(at)
    assert session.current_question.priority == "high"
    assert t("grill.ui.importance", level=t("grill.importance.high")) in badges(at)
    assert t("ui.grill.category.contradiction") in badges(at)  # the question category
    assert "REQ-1" in badges(at) and "REQ-2" in badges(at)  # the requirement IDs involved
    assert any(c.startswith("Why it matters for testing:") for c in captions(at))
    assert any("> The password must be at least 8 characters." in m.value for m in at.markdown)
    assert any(c.startswith("Requirement REQ-2:") for c in captions(at))  # the other side
    assert any(t("grill.ui.conflict_question") == w.value for w in at.warning)  # a source contradiction
    assert metrics(at) | {"Quality score": ""} == {
        "Confirmed": "0", "Assumptions": "0", "Unknowns": "0", "Conflicts": "1", "Quality score": "",
    }
    assert any(c.startswith(t("ui.grill.open_count", count=len(session.questions))) for c in captions(at))
    assert issues(at).label == t("grill.ui.issues_heading", count=len(session.questions))


def test_answers_update_states_issues_and_the_history():
    at = started()
    choose(at, "REQ-1: The password must be at least 8 characters.")  # the contradiction is decided
    session = session_of(at)
    assert session.current_question_id == "rule.missing_expected_result.REQ-3"
    answer_text(at, "Photos up to 5 MB are shown on the profile page.")
    session = session_of(at)
    # Adaptive: the new limit asks what happens beyond it, ahead of the remaining medium question.
    assert session.current_question_id == "followup.limit.rule.missing_expected_result.REQ-3"
    assert metrics(at)["Confirmed"] == "2" and metrics(at)["Conflicts"] == "0"
    history = next(table.value for table in at.table if t("grill.ui.column_answer") in table.value.columns)
    assert "✅ Confirmed" in history[t("grill.ui.column_state")].tolist()


def test_answer_contradicting_its_requirement_is_asked_about_without_ai():
    at = grill()
    at = start(at, "requirements", text_key="grill_requirements_text",
               text="REQ-3: Users can upload a profile photo of at most 5 MB.")
    assert session_of(at).current_question_id == "rule.missing_expected_result.REQ-3"
    answer_text(at, "Photos of at most 10 MB appear on the profile page.")
    session = session_of(at)
    question = session.current_question
    assert question.id.startswith("conflict.") and question.priority == "high"
    assert any(t("grill.ui.conflict_question") == w.value for w in at.warning)
    assert metrics(at)["Conflicts"] == "1"  # the contested answer
    assert at.button(key="grill_skip").disabled  # a contradiction must be decided or marked unknown
    choose(at, "REQ-3: Users can upload a profile photo of at most 5 MB.")
    session = session_of(at)
    assert not session.current_question_id or not session.current_question_id.startswith("conflict.")
    assert metrics(at)["Conflicts"] == "0"


def test_unresolved_contradiction_appears_in_issues_and_report():
    at = started()
    click(at, "grill_unknown")  # the source contradiction stays open
    assert any("⚔️" in str(table.value.to_string()) for table in at.table)
    click(at, "grill_to_draft")
    click(at, "grill_review_button")
    next(c for c in at.checkbox if c.key and "_accept_" in c.key).check().run()
    click(at, "grill_request_confirmation")
    click(at, "grill_confirm_button")
    assert session_of(at).step == GrillStep.FINALIZED
    assert any(t("grill.report.contradictions") in m.value for m in at.markdown)
    frames = [table.value.to_string() for table in at.table]
    assert any(t("grill.report.unresolved") in f and "REQ-2: The password must be at least 10" in f for f in frames)


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_unified_screens_are_translated(lang):
    at = started(lang)
    screens = [visible_text(at) + captions(at)]
    choose(at, "REQ-1: The password must be at least 8 characters.")
    answer_text(at, "Photos up to 5 MB are shown on the profile page.")
    screens.append(visible_text(at) + captions(at))
    for texts in screens:
        assert not raw_keys(texts), raw_keys(texts)
