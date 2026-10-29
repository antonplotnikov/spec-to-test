"""Confirmed decisions about the change impact: currency, staleness, one current decision, storage."""

import json
import threading

import pytest

from spec_to_test import filelock, storage
from spec_to_test.change_impact import Recommendation
from spec_to_test.exports import impact_csv
from spec_to_test.impact_decisions import (
    Decision,
    DecisionError,
    DecisionState,
    DiskDecisionStore,
    SessionDecisionStore,
    impact_fingerprint,
    record_decision,
    snapshot_of,
    state_of,
    status_of,
)
from spec_to_test.models import (
    ChangeImpact,
    Requirement,
    RequirementChange,
    ReviewStatus,
    TestCase,
    TestCaseImpact,
    TestType,
    Workspace,
)

OLD_TEXT = "The session must expire after 30 minutes."
NEW_TEXT = "The session must expire after 15 minutes."


def previous_workspace(steps=("Log in and wait 30 minutes.",), status=ReviewStatus.DRAFT) -> Workspace:
    tc = TestCase(id="TC-2", requirement_id="REQ-2", title="Session expires", test_type=TestType.POSITIVE,
                  steps=list(steps), expected_result="The session is closed.", review_status=status)
    return Workspace(document_hash="prev1", title="Spec", requirements=[Requirement(id="REQ-2", text=OLD_TEXT)],
                     test_cases=[tc])


def modified_impact(new_text: str = NEW_TEXT, extra: tuple = ()) -> ChangeImpact:
    return ChangeImpact(
        previous_document_hash="prev1", previous_title="Spec",
        changes=[RequirementChange(kind="modified", old_id="REQ-2", new_id="REQ-2", old_text=OLD_TEXT,
                                   new_text=new_text), *extra],
        test_cases=[TestCaseImpact(test_case_id="TC-2", requirement_id="REQ-2",
                                   review_status=ReviewStatus.DRAFT, reason="modified")],
    )


def recommendation() -> Recommendation:
    return Recommendation(requirement_id="REQ-2", action="update", change="modified", test_case_ids=["TC-2"])


_DEFAULT = object()


def snapshot(previous=_DEFAULT, impact=None, recs=None):
    impact = impact or modified_impact()
    recs = recs or [recommendation()]
    if previous is _DEFAULT:
        previous = previous_workspace()  # None means: the previous version is gone
    fp = impact_fingerprint(recs, impact.previous_document_hash, "new1")
    return snapshot_of(recs[0], impact, previous, fp)


def decide(store, snap, decision=Decision.ACCEPTED, comment="", position_based=False):
    return record_decision(store, "default", recommendation=recommendation(), snapshot=snap, decision=decision,
                           previous_hash="prev1", new_hash="new1", position_based=position_based, comment=comment)


# --- Currency and staleness ---------------------------------------------------------------------

def test_a_decision_stays_current_while_nothing_it_depends_on_changed():
    store = SessionDecisionStore()
    record = decide(store, snapshot())
    assert state_of(record, snapshot()) == DecisionState.CURRENT


def test_the_requirement_wording_is_compared_loosely_but_a_real_change_makes_it_stale():
    store = SessionDecisionStore()
    record = decide(store, snapshot())
    same_wording = snapshot(impact=modified_impact(new_text="the session  must expire after 15 minutes."))
    assert state_of(record, same_wording) == DecisionState.CURRENT  # case and spacing do not matter
    changed = snapshot(impact=modified_impact(new_text="The session must expire after 5 minutes."))
    assert state_of(record, changed) == DecisionState.STALE


def test_a_changed_test_case_or_review_status_makes_the_decision_stale():
    store = SessionDecisionStore()
    record = decide(store, snapshot())
    edited_steps = snapshot(previous=previous_workspace(steps=("Log in and wait 40 minutes.",)))
    assert state_of(record, edited_steps) == DecisionState.STALE
    approved = snapshot(previous=previous_workspace(status=ReviewStatus.APPROVED))
    assert state_of(record, approved) == DecisionState.STALE


def test_a_missing_previous_version_makes_the_decision_stale():
    store = SessionDecisionStore()
    record = decide(store, snapshot())
    assert state_of(record, snapshot(previous=None)) == DecisionState.STALE


def test_a_changed_set_of_recommendations_makes_every_decision_stale():
    store = SessionDecisionStore()
    record = decide(store, snapshot())
    extra = (RequirementChange(kind="added", new_id="REQ-3", new_text="A new rule."),)
    more = modified_impact(extra=extra)
    more_recs = [recommendation(), Recommendation(requirement_id="REQ-3", action="add", change="added")]
    assert state_of(record, snapshot(impact=more, recs=more_recs)) == DecisionState.STALE


# --- One current decision per recommendation ----------------------------------------------------

def test_a_second_final_decision_on_a_current_recommendation_is_refused():
    store = SessionDecisionStore()
    decide(store, snapshot())
    with pytest.raises(DecisionError) as error:
        decide(store, snapshot(), Decision.REJECTED)
    assert error.value.code == "already_decided"
    assert len(store.records("default")) == 1


def test_a_deferred_decision_does_not_block_a_later_one():
    store = SessionDecisionStore()
    decide(store, snapshot(), Decision.DEFERRED)
    later = decide(store, snapshot(), Decision.ACCEPTED)
    assert later.decision == Decision.ACCEPTED
    assert later.supersedes == "DEC-001"


def test_a_stale_decision_is_superseded_and_kept():
    store = SessionDecisionStore()
    first = decide(store, snapshot())
    changed = snapshot(impact=modified_impact(new_text="The session must expire after 5 minutes."))
    second = decide(store, changed, Decision.REJECTED)
    assert second.supersedes == first.id
    assert [r.id for r in store.records("default")] == [first.id, second.id]
    state, latest = status_of(store.records("default"), "REQ-2", changed)
    assert (state, latest.id) == (DecisionState.CURRENT, second.id)


def test_decisions_recorded_at_the_same_time_from_several_tabs_give_one_decision(tmp_path):
    store = DiskDecisionStore()
    results, refused = [], []
    mutex = threading.Lock()

    def confirm():
        try:
            record = decide(store, snapshot())
            with mutex:
                results.append(record.id)
        except DecisionError as error:
            with mutex:
                refused.append(error.code)

    threads = [threading.Thread(target=confirm) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert len(results) == 1
    assert refused == ["already_decided"] * 7
    assert [r.id for r in store.records("default")] == results


def test_ids_are_never_reused_when_decisions_are_added():
    store = SessionDecisionStore()
    first = decide(store, snapshot())
    second = decide(store, snapshot(impact=modified_impact(new_text="5 minutes.")), Decision.REJECTED)
    assert (first.id, second.id) == ("DEC-001", "DEC-002")


# --- Storage: unreadable files, kept entries, busy lock -----------------------------------------

def test_an_unreadable_file_is_never_overwritten():
    path = storage.impact_decisions_path("default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    store = DiskDecisionStore()
    with pytest.raises(DecisionError) as error:
        decide(store, snapshot())
    assert error.value.code == "unreadable"
    assert path.read_text(encoding="utf-8") == "{not json"
    assert store.records("default") == []  # reading shows nothing and writes nothing


def test_a_file_of_another_format_is_never_overwritten():
    path = storage.impact_decisions_path("default")
    path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"format": "someone-else", "format_version": 4, "decisions": []})
    path.write_text(original, encoding="utf-8")
    with pytest.raises(DecisionError):
        decide(DiskDecisionStore(), snapshot())
    assert path.read_text(encoding="utf-8") == original


def test_entries_that_cannot_be_read_and_unknown_fields_are_kept_on_write():
    store = DiskDecisionStore()
    decide(store, snapshot())
    path = storage.impact_decisions_path("default")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["decisions"].append({"id": "not-a-decision", "from": "a newer version"})
    data["decisions"][0]["reviewer_tag"] = "added later"
    path.write_text(json.dumps(data), encoding="utf-8")
    decide(store, snapshot(impact=modified_impact(new_text="5 minutes.")), Decision.REJECTED)
    kept = json.loads(path.read_text(encoding="utf-8"))["decisions"]
    assert {"id": "not-a-decision", "from": "a newer version"} in kept
    assert kept[0]["reviewer_tag"] == "added later"


def test_a_busy_file_is_reported_and_nothing_changes(monkeypatch):
    store = DiskDecisionStore()
    decide(store, snapshot())
    monkeypatch.setattr(filelock, "LOCK_TIMEOUT_S", 0.05)
    with filelock.locked(storage.impact_decisions_path("default")):
        with pytest.raises(OSError):
            decide(store, snapshot(impact=modified_impact(new_text="5 minutes.")), Decision.REJECTED)
    assert [r.id for r in store.records("default")] == ["DEC-001"]


def test_a_requirement_without_an_id_in_the_document_is_marked_position_based():
    store = SessionDecisionStore()
    record = decide(store, snapshot(), position_based=True)
    assert record.position_based is True


# --- Invariants ----------------------------------------------------------------------------------

def test_recording_a_decision_changes_no_test_case_status():
    before = previous_workspace()
    dump = before.model_dump()
    store = SessionDecisionStore()
    decide(store, snapshot(previous=before), Decision.ACCEPTED)
    with pytest.raises(DecisionError):
        decide(store, snapshot(previous=before), Decision.REJECTED)  # refused, changes nothing
    assert before.model_dump() == dump
    assert before.test_cases[0].review_status == ReviewStatus.DRAFT


def test_the_export_has_a_decision_column_only_when_decisions_are_given():
    recs = [recommendation()]
    plain = impact_csv(recs, "en")
    assert "Decision" not in plain.splitlines()[0]
    with_decisions = impact_csv(recs, "en", decisions={"REQ-2": "Accepted"})
    header = with_decisions.splitlines()[0]
    assert header.endswith("Decision")
    assert with_decisions.splitlines()[1].endswith("Accepted")
