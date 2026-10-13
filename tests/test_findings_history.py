"""Resolving, reopening and undoing findings, with history; workspace schema migration."""

import json

import pytest

from spec_to_test import findings, storage
from spec_to_test.grill.integration import resolve_findings
from spec_to_test.grill.models import AnswerStatus, GrillKind, RequirementsDraft
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.input_parser import extract_requirements
from spec_to_test.migrations import MigrationError, migrate_workspace_data
from spec_to_test.models import WORKSPACE_SCHEMA_VERSION, ClarificationStatus, FindingChange, FindingType, Workspace
from spec_to_test.rule_engine import analyze_requirements

REQS = """REQ-1: The password must be at least 8 characters.
REQ-2: The password must be at least 10 characters.
REQ-3: The page should load fast."""
CONTRADICTION = "rule.contradiction.REQ-1+REQ-2"
VAGUE = "rule.ambiguous_wording.REQ-3"


def workspace() -> Workspace:
    result = analyze_requirements(extract_requirements(REQS))
    return Workspace(document_hash="doc1", requirements=result.requirements, findings=result.findings)


def confirmed(ws: Workspace):
    """Requirements Grill with both findings answered and confirmed, then finalized."""
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=ws.requirements))
    session = WF.answer(session, "REQ-2: The password must be at least 10 characters.")
    session = WF.answer(session, "Within 2 seconds on desktop.")
    session = WF.review(session)
    return WF.confirm(WF.request_confirmation(session, accept_unresolved=True))


def statuses(ws: Workspace) -> dict[str, ClarificationStatus]:
    return {f.key: f.status for f in ws.findings}


def contradiction_keys(ws: Workspace) -> list[str]:
    return [f.key for f in ws.findings if f.type == FindingType.CONTRADICTION]


def test_grill_resolution_is_recorded_as_one_action():
    ws = workspace()
    session = confirmed(ws)
    updated = resolve_findings(session, ws, [CONTRADICTION, VAGUE], reason="Agreed with the PO", at="2026-10-13T10:00:00+00:00")
    events = updated.finding_history
    assert {e.change for e in events} == {FindingChange.RESOLVED} and len({e.batch for e in events}) == 1
    assert all(e.via == "grill" and e.grill_session_id == session.id and e.reason == "Agreed with the PO" for e in events)
    clarifications = {e.clarification for e in events}
    assert clarifications == {"REQ-2: The password must be at least 10 characters.", "Within 2 seconds on desktop."}
    # Both sides of the contradiction are resolved together.
    assert {e.finding_key for e in events} >= set(contradiction_keys(ws))
    assert ws.finding_history == []  # the input is untouched


def test_reopen_with_reason_and_contradiction_twins_follow():
    ws = workspace()
    resolved = resolve_findings(confirmed(ws), ws, [CONTRADICTION])
    key = contradiction_keys(resolved)[0]
    reopened = findings.reopen(resolved, key, reason="  The   rule changed  ")
    assert all(reopened.findings[i].status == ClarificationStatus.NEEDS_CLARIFICATION
               for i, f in enumerate(reopened.findings) if f.type == FindingType.CONTRADICTION)
    last = reopened.finding_history[-1]
    assert (last.change, last.via, last.reason) == (FindingChange.REOPENED, "manual", "The rule changed")
    assert len(findings.history(reopened, key)) == 4  # two resolved + two reopened events
    with pytest.raises(findings.FindingError) as err:
        findings.reopen(reopened, key)
    assert err.value.code == "not_resolved"


def test_undo_reverts_the_last_action_and_is_recorded():
    ws = workspace()
    resolved = resolve_findings(confirmed(ws), ws, [CONTRADICTION, VAGUE])
    batch = findings.last_change(resolved)
    assert len(batch) == len(resolved.finding_history)  # the whole resolve action
    undone = findings.undo_last(resolved, reason="clicked by mistake")
    assert statuses(undone) == statuses(ws)
    undo_events = undone.finding_history[len(resolved.finding_history):]
    assert all(e.via == "undo" and e.change == FindingChange.REOPENED for e in undo_events)
    assert set(undo_events[0].undoes.split(",")) == {e.id for e in batch}
    # Undo again: the undo is itself the last change, so the findings are resolved again.
    redone = findings.undo_last(undone)
    assert statuses(redone) == statuses(resolved)


def test_undo_is_refused_when_nothing_can_be_undone():
    ws = workspace()
    with pytest.raises(findings.FindingError) as err:
        findings.undo_last(ws)
    assert err.value.code == "nothing_to_undo"
    resolved = resolve_findings(confirmed(ws), ws, [VAGUE])
    # A later edit outside the history (e.g. an older app version) makes the last change stale.
    stale = resolved.model_copy(deep=True)
    next(f for f in stale.findings if f.key == resolved.finding_history[-1].finding_key).status = ClarificationStatus.NEEDS_CLARIFICATION
    assert findings.last_change(stale) == []


def test_reasons_are_limited():
    ws = workspace()
    resolved = resolve_findings(confirmed(ws), ws, [VAGUE])
    with pytest.raises(findings.FindingError) as err:
        findings.reopen(resolved, resolved.finding_history[0].finding_key, reason="x" * 501)
    assert err.value.code == "reason_too_long"


def test_resolved_findings_list_shows_a_pair_once():
    ws = workspace()
    resolved = resolve_findings(confirmed(ws), ws, [CONTRADICTION, VAGUE])
    listed = findings.resolved_findings(resolved)
    assert sorted(f.type.value for f in listed) == ["ambiguous_wording", "contradiction"]


def test_assumed_clarifications_still_resolve_nothing():
    ws = workspace()
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=ws.requirements))
    session = WF.answer(session, "REQ-2: The password must be at least 10 characters.", AnswerStatus.ASSUMED)
    session = WF.answer(session, "Within 2 seconds", AnswerStatus.ASSUMED)
    session = WF.confirm(WF.request_confirmation(WF.review(session), accept_unresolved=True))
    from spec_to_test.grill.integration import IntegrationError

    with pytest.raises(IntegrationError):
        resolve_findings(session, ws, [CONTRADICTION])


# --- Workspace migration -----------------------------------------------------------------------

def old_workspace_json() -> dict:
    """A workspace saved before schema 2: no schema_version, no finding_history, one finding resolved."""
    data = json.loads(workspace().model_dump_json())
    data.pop("schema_version")
    data.pop("finding_history")
    data["findings"][0]["status"] = "resolved"
    return data


def test_old_workspace_files_open_and_keep_their_statuses():
    path = storage.data_dir() / "workspaces" / "doc1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(old_workspace_json()), encoding="utf-8")
    ws = storage.load_workspace("doc1")
    assert ws is not None and ws.schema_version == WORKSPACE_SCHEMA_VERSION
    assert ws.findings[0].status == ClarificationStatus.RESOLVED and ws.finding_history == []
    assert findings.history(ws, ws.findings[0].key) == []  # unknown history is not invented
    # A resolved finding without history can still be reopened.
    reopened = findings.reopen(ws, ws.findings[0].key)
    storage.save_workspace(reopened)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == WORKSPACE_SCHEMA_VERSION and len(saved["finding_history"]) >= 1


def test_newer_or_invalid_workspace_versions_are_refused():
    with pytest.raises(MigrationError):
        migrate_workspace_data({**old_workspace_json(), "schema_version": WORKSPACE_SCHEMA_VERSION + 1})
    with pytest.raises(MigrationError):
        migrate_workspace_data({**old_workspace_json(), "schema_version": "2"})
    path = storage.data_dir() / "workspaces" / "doc2.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**old_workspace_json(), "schema_version": 99}), encoding="utf-8")
    assert storage.load_workspace("doc2") is None
    assert migrate_workspace_data(old_workspace_json())["finding_history"] == []
