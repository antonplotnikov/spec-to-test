"""Saved interviews, the History tab and finding reopen/undo, driven through the real app (AppTest)."""

from test_grill_ui import REQS, choose, click, grill, new_app, session_of, start

from conftest import goto, home
from spec_to_test import findings
from spec_to_test.grill.models import AnswerStatus
from spec_to_test.i18n import t
from spec_to_test.models import ClarificationStatus, FindingChange

FIRST = "REQ-1: The password must be at least 8 characters."


def interviewing():
    """A requirements interview with one answer given."""
    at = start(grill(), "requirements", text_key="grill_requirements_text", text=REQS)
    return choose(at, FIRST)


def test_a_reload_reopens_the_unfinished_interview():
    at = interviewing()
    before = session_of(at)
    reloaded = grill(fresh=False)  # a new browser session, as after a page reload
    after = session_of(reloaded)
    assert after.id == before.id and after.answers == before.answers and after.history == before.history
    assert after.current_question_id == before.current_question_id
    assert any(i.value.startswith(t("grill.ui.restored", time="")[:30]) for i in reloaded.info)
    # It can be continued where it stopped.
    reloaded = click(reloaded, "grill_unknown")
    assert session_of(reloaded).answers[before.current_question_id].status == AnswerStatus.UNKNOWN


def test_close_resume_and_delete():
    at = click(interviewing(), "grill_close")
    assert "grill_session" not in at.session_state
    session_id = next(b.key for b in at.button if b.key.startswith("grill_resume_")).removeprefix("grill_resume_")
    at = click(at, f"grill_resume_{session_id}")
    assert session_of(at).id == session_id and len(session_of(at).answers) == 1
    at = click(at, "grill_close")
    # Closed on purpose: a reload does not reopen it, but it is still listed.
    reloaded = grill(fresh=False)
    assert "grill_session" not in reloaded.session_state
    assert any(b.key == f"grill_resume_{session_id}" for b in reloaded.button)
    reloaded = click(reloaded, f"grill_delete_{session_id}")
    assert not any(b.key.startswith("grill_resume_") for b in reloaded.button)


def test_session_mode_offers_files_instead_of_disk(monkeypatch):
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE")
    at = interviewing()
    assert "grill_export" in [b.key for b in at.get("download_button")]
    assert any(t("grill.ui.saved_in_session", time="")[:10] in m.value for m in at.markdown)
    at = click(at, "grill_close")
    assert any(c.value == t("grill.ui.saved_session") for c in at.caption)
    assert any(b.key.startswith("grill_resume_") for b in at.button)  # kept for this browser session
    assert "grill_session" not in grill(fresh=False).session_state  # nothing survives a reload


def test_history_tab_traces_each_decision():
    at = interviewing()
    labels = [tab.label for tab in at.tabs]
    assert t("grill.trace.tab") in labels
    text = "\n".join(str(m.value) for m in at.markdown)
    assert t("grill.trace.heading") in text and t("grill.audit.heading", count=len(session_of(at).events)) in text
    trace = [m.value for m in at.markdown if m.value.startswith(":green-badge[Confirmed]")]
    assert any("REQ-1" in line and "conflicts with REQ-2" in line for line in trace), trace
    captions = [c.value for c in at.caption]
    assert any(c.startswith(f"{t('grill.ui.column_answer')}: {FIRST}") for c in captions)
    assert any(t("grill.trace.origin.contradiction") in c for c in captions)
    audit = [m.value for m in at.markdown if t("grill.audit.action.answered") in m.value]
    assert audit and FIRST in audit[0]
    assert "grill_audit_download" in [b.key for b in at.get("download_button")]


def analyzed():
    at = new_app()
    home(at).text_area(key="requirements_text").input(REQS).run()
    home(at).button(key="analyze").click().run()
    return at


def test_reopen_and_undo_on_the_analysis_page():
    at = analyzed()
    ws = at.session_state["workspace"]
    key = next(f.key for f in ws.findings if f.type.value == "ambiguous_wording")
    at.session_state["workspace"] = findings.resolve(ws, [key], clarification="Within 2 seconds")
    goto(at, "analysis")
    assert not at.exception
    at.text_input(key="finding_reason").input("PO changed the target").run()
    at = click(at, "finding_reopen")
    ws = at.session_state["workspace"]
    assert findings.finding_by_key(ws, key).status == ClarificationStatus.NEEDS_CLARIFICATION
    event = ws.finding_history[-1]
    assert (event.change, event.reason) == (FindingChange.REOPENED, "PO changed the target")
    at = click(at, "finding_undo")
    ws = at.session_state["workspace"]
    assert findings.finding_by_key(ws, key).status == ClarificationStatus.RESOLVED
    assert ws.finding_history[-1].via == "undo"
    # The change survives: it was saved with the document.
    from spec_to_test.storage import load_workspace

    assert len(load_workspace(ws.document_hash).finding_history) == 3


def test_settled_findings_are_announced_and_skipped():
    at = analyzed()
    ws = at.session_state["workspace"]
    key = next(f.key for f in ws.findings if f.type.value == "ambiguous_wording")
    at.session_state["workspace"] = findings.resolve(ws, [key])
    at = grill(at)
    assert any(c.value == t("grill.ui.settled_note", count=1) for c in at.caption)
    at = click(at, "grill_start")
    assert "rule.ambiguous_wording.REQ-3" not in {q.id for q in session_of(at).questions}
    assert session_of(at).settled_question_ids == ["rule.ambiguous_wording.REQ-3"]


def test_new_screens_are_translated():
    from test_localization import raw_keys, visible_text

    for lang in ("uk", "ru"):
        at = grill()
        at.selectbox(key="language").select(lang).run()
        start_screen = visible_text(at)
        at = start(at, "requirements", text_key="grill_requirements_text", text=REQS)
        at = click(choose(at, FIRST), "grill_close")
        listed = visible_text(at)
        at = click(at, next(b.key for b in at.button if b.key.startswith("grill_resume_")))
        for texts in (start_screen, listed, visible_text(at)):
            assert not raw_keys(texts), raw_keys(texts)
            joined = "\n".join(texts)
            for english in ("Unfinished interviews", "Decision trace", "Audit log", "Save progress to a file"):
                assert english not in joined
