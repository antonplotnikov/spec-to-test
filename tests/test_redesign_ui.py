"""The redesigned shell and pages, driven through AppTest: navigation, the Grill
analysis panel built from real data, and validation messages."""

from test_grill_ui import click, grill, new_app, session_of, start

from conftest import goto, home
from spec_to_test.grill.insights import interview_counts
from spec_to_test.i18n import t
from spec_to_test.quality import average_score, score_all

REQS = """REQ-1: The password must be at least 8 characters.
REQ-2: The password must be at least 10 characters.
REQ-3: The page should load fast."""


def analyzed(text: str = REQS):
    at = new_app()
    home(at).text_area(key="requirements_text").input(text).run()
    at.button(key="analyze").click().run()
    assert not at.exception
    return at


def markdown(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def metric(at, label: str) -> str:
    return next(m.value for m in at.metric if m.label == label)


# --- Navigation -------------------------------------------------------------------------------

def test_analysis_offers_grill_mode_on_the_analyzed_document():
    at = analyzed()
    at.button(key="analysis_launch_grill").click().run()
    assert at.sidebar.radio(key="app_mode").value == "grill"
    assert at.checkbox(key="grill_use_analyzed").value is True
    click(at, "grill_start")
    assert len(session_of(at).draft.requirements) == 3


def test_home_shows_the_open_document_with_quick_actions():
    at = goto(analyzed(), "home")
    assert metric(at, "Requirements") == "3"
    for page in ("analysis", "grill", "tests", "export"):
        assert any(b.key == f"home_open_{page}" for b in at.button)
    at.button(key="home_open_tests").click().run()
    assert at.sidebar.radio(key="app_mode").value == "tests"


def test_requirements_analysis_shows_the_real_average_quality():
    at = analyzed()
    ws = at.session_state["workspace"]
    expected = average_score(score_all(ws.requirements, ws.findings).values())
    assert metric(at, "Quality score") == f"{expected}/100"
    assert metric(at, "Avg. quality") == str(expected)


# --- Grill Mode -------------------------------------------------------------------------------

def test_grill_panel_is_built_from_the_session():
    at = start(grill(), "requirements", text_key="grill_requirements_text", text=REQS)
    labels = [tab.label for tab in at.tabs]
    assert labels == ["Analysis", "Findings", "Report", "History"]
    text = markdown(at)
    assert "Ambiguities: 1" in text and "Contradictions: 1" in text
    assert "REQ-2" in text  # related to the current requirement REQ-1
    assert any(t("ui.grill.related_to", id="REQ-1") == c.value for c in at.caption)
    # The score shown is the rule engine's score for exactly these requirements.
    session = session_of(at)
    from spec_to_test.grill.insights import scope_findings, session_requirements

    reqs = session_requirements(session)
    expected = average_score(score_all(reqs, scope_findings(session, None)).values())
    assert metric(at, "Quality score") == f"{expected}/100"


def test_an_assumption_is_never_shown_as_confirmed():
    at = start(grill(), "requirements", text_key="grill_requirements_text", text=REQS)
    radio = next(r for r in at.radio if r.key and "_choice_" in r.key)
    radio.set_value("REQ-1: The password must be at least 8 characters.")
    click(at, "grill_assume")
    assert (metric(at, "Confirmed"), metric(at, "Assumptions")) == ("0", "1")
    counts = interview_counts(session_of(at))
    assert (counts.confirmed, counts.assumptions) == (0, 1)
    text = markdown(at)
    assert t("ui.grill.active_assumptions", count=1) in text
    assert t("ui.grill.confirmed", count=0) in text  # the Report tab lists no confirmed fact
    assert ":orange-badge[Assumption] :blue-badge[REQ-1] :blue-badge[REQ-2] REQ-1: The password" in text
    assert ":green-badge[Confirmed]" not in text


def test_grill_actions_and_previous_questions():
    at = start(grill(), "requirements", text_key="grill_requirements_text", text=REQS)
    labels = {b.key: b.label for b in at.button}
    assert labels["grill_answer"] == "Submit answer"
    assert labels["grill_assume"] == "Mark as assumption"
    assert labels["grill_unknown"] == "Mark as unknown"
    assert labels["grill_skip"] == "Skip"
    click(at, "grill_unknown")
    assert metric(at, "Unknowns") == "1"
    assert t("ui.grill.previous", count=1) in markdown(at)
    assert any(b.key == "grill_edit_answer" for b in at.button)


# --- Other pages --------------------------------------------------------------------------------

def test_export_warns_when_nothing_would_be_exported():
    at = goto(analyzed(), "export")
    assert not at.warning
    at.checkbox(key="export_only_approved").check().run()
    assert any(t("ui.export.nothing_approved") == w.value for w in at.warning)
    assert t("ui.export.cases", count=0) in markdown(at)


def test_dashboard_lists_unresolved_issues_highest_severity_first():
    at = goto(analyzed(), "dashboard")
    table = next(tb.value for tb in at.table if "Clarification question" in tb.value.columns or "Question" in tb.value.columns)
    severities = list(table[table.columns[2]])
    order = {"🔴 High": 0, "🟠 Medium": 1, "🟡 Low": 2}
    assert [order[s] for s in severities] == sorted(order[s] for s in severities)


def test_test_case_detail_shows_steps_and_requirement_link():
    at = goto(analyzed(), "tests")
    ws = at.session_state["workspace"]
    first = ws.test_cases[0]
    text = markdown(at)
    assert f"#### {first.id} · " in text
    assert f":material/link: {first.requirement_id}" in text
    assert "1. " in text  # numbered steps


def test_findings_say_what_the_interview_decided_without_resolving_them():
    at = start(grill(), "requirements", text_key="grill_requirements_text", text=REQS)
    radio = next(r for r in at.radio if r.key and "_choice_" in r.key)
    radio.set_value("REQ-1: The password must be at least 8 characters.")
    click(at, "grill_assume")
    text = markdown(at)
    # Still listed: the source finding is resolved only by the opt-in step after confirmation.
    assert t("ui.grill.contradictions", count=1) in text
    assert t("ui.grill.in_interview", state=t("grill.state.assumption")) in text
