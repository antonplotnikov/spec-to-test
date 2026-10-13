"""The open interview follows finding status changes made on the analysis page (AppTest)."""

from test_grill_persistence_ui import analyzed
from test_grill_ui import click, grill, session_of

from conftest import goto
from spec_to_test import findings
from spec_to_test.grill.models import AuditAction, RetireReason
from spec_to_test.i18n import t

VAGUE = "rule.ambiguous_wording.REQ-3"


def interview_on_the_document():
    at = grill(analyzed())
    at = click(at, "grill_start")  # "use the analyzed document" is ticked by default
    assert VAGUE in {q.id for q in session_of(at).pending_questions}
    return at


def test_resolving_and_reopening_a_finding_updates_the_open_interview():
    at = interview_on_the_document()
    before = session_of(at)
    ws = at.session_state["workspace"]
    key = next(f.key for f in ws.findings if f.type.value == "ambiguous_wording")
    at.session_state["workspace"] = findings.resolve(ws, [key], clarification="Within 2 seconds")
    at.run()
    assert not at.exception
    session = session_of(at)
    assert session.settled_question_ids == [VAGUE]
    assert session.retired_question(VAGUE).reason == RetireReason.SETTLED
    assert session.current_question_id == before.current_question_id  # the question on screen stays
    assert any(i.value == t("grill.ui.findings_synced", resolved=1, reopened=0) for i in at.info)
    assert any(e.label.startswith(t("grill.ui.retired_heading", count=1)) for e in at.expander)

    # Reopened on the analysis page: back in the queue of the interview, same ID.
    goto(at, "analysis")
    at = click(at, "finding_reopen")
    at = grill(at, fresh=False)
    session = session_of(at)
    assert session.settled_question_ids == [] and not session.retired
    assert VAGUE in {q.id for q in session.pending_questions}
    assert [e.action for e in session.events].count(AuditAction.FINDINGS_SYNCED) == 2
    assert any(i.value == t("grill.ui.findings_synced", resolved=0, reopened=1) for i in at.info)
    # Saved: a reload shows the same queue.
    assert session_of(grill(fresh=False)).questions == session.questions


def test_an_interview_on_other_text_is_not_touched():
    at = analyzed()
    ws = at.session_state["workspace"]
    at = grill(at)
    at.checkbox(key="grill_use_analyzed").uncheck().run()
    at.text_area(key="grill_requirements_text").input("REQ-1: The page should load fast.").run()
    at = click(at, "grill_start")
    revision = session_of(at).revision
    key = next(f.key for f in ws.findings if f.type.value == "ambiguous_wording")
    at.session_state["workspace"] = findings.resolve(ws, [key])
    at.run()
    assert session_of(at).revision == revision and session_of(at).settled_question_ids == []
