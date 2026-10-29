"""Confirmed decisions about the change impact: an explicit record per recommendation, kept apart from the documents.

A decision confirms a recommendation (Accept, Reject or Defer). It changes no test case: statuses are
still changed only by the explicit actions of the Test Cases page.

A decision stays current only while everything it was made from is unchanged: the wording of the
requirement in both versions, the test cases it concerns (their text and review status) and the whole
set of recommendations. Otherwise it is stale and is shown as such; a new decision then supersedes it.

Records live in their own file per project (`impact_decisions.json`), not in the documents, so saved
documents keep their format. Every change is a transaction under the file's lock (see filelock): the
latest saved file is read again, the record is added with the next free ID, and the file is written
back. A file that cannot be read or belongs to another format is never overwritten.
"""

import hashlib
import json
import threading
from collections.abc import Callable, Iterable, MutableMapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from spec_to_test import storage
from spec_to_test.change_impact import Recommendation
from spec_to_test.filelock import locked
from spec_to_test.models import ChangeImpact, TestCase, Workspace

FORMAT: Literal["spec-to-test/impact-decisions"] = "spec-to-test/impact-decisions"
FORMAT_VERSION = 1
MAX_DECISIONS = 500
COMMENT_MAX = 500


class Decision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class DecisionState(StrEnum):
    UNDECIDED = "undecided"
    CURRENT = "current"  # the decision still matches what it was made from
    STALE = "stale"  # something it depends on has changed: check again


class DecisionError(ValueError):
    """A decision cannot be recorded; `code` maps to impact.decision.error.<code>."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DecisionRecord(BaseModel):
    # Fields a newer version added are kept on save (as for runs and bug reports).
    model_config = ConfigDict(extra="allow")

    id: str = Field(pattern=r"^DEC-\d{3,}$")
    requirement_id: str = Field(min_length=1, max_length=64)
    # The requirement has no ID in the document: its ID is its position, not a stable identity.
    position_based: bool = False
    action: str = Field(min_length=1, max_length=20)
    change: str = Field(min_length=1, max_length=20)
    test_case_ids: list[str] = Field(default_factory=list, max_length=500)
    decision: Decision
    comment: str = Field(default="", max_length=COMMENT_MAX)
    decided_at: str = ""
    previous_document_hash: str = ""
    new_document_hash: str = ""
    impact_fingerprint: str
    requirement_fingerprint: str
    case_fingerprints: dict[str, str] = Field(default_factory=dict)
    supersedes: str = ""


class Snapshot(BaseModel):
    """What a recommendation is made of right now. A decision is current only if its snapshot is unchanged."""

    impact_fingerprint: str
    requirement_fingerprint: str
    case_fingerprints: dict[str, str]


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def requirement_fingerprint(old_text: str, new_text: str) -> str:
    """The wording of a requirement in the previous and in the new version (empty when a version lacks it)."""
    return _digest(f"{_norm(old_text)}\x1f{_norm(new_text)}")


def case_fingerprint(tc: TestCase | None) -> str:
    """A test case's title, steps, expected result and review status; "missing" when it is not in the version."""
    if tc is None:
        return "missing"
    return _digest("\x1f".join([tc.title, *tc.steps, tc.expected_result, tc.review_status.value]))


def impact_fingerprint(recommendations: Iterable[Recommendation], previous_hash: str, new_hash: str) -> str:
    """The whole set of recommendations of one comparison, and the two versions it compares."""
    rows = sorted(
        (r.requirement_id, r.action, r.change, sorted(r.test_case_ids)) for r in recommendations
    )
    return _digest(json.dumps({"previous": previous_hash, "new": new_hash, "rows": rows}, sort_keys=True))


def snapshot_of(recommendation: Recommendation, impact: ChangeImpact, previous: Workspace | None,
                impact_fp: str) -> Snapshot:
    """The snapshot of one recommendation: its requirement texts, and its test cases in the previous version."""
    change = next((c for c in impact.changes if (c.new_id or c.old_id) == recommendation.requirement_id), None)
    old_text = change.old_text if change else ""
    new_text = change.new_text if change else ""
    by_id = {tc.id: tc for tc in previous.test_cases} if previous is not None else {}
    cases = {
        tc_id: case_fingerprint(by_id.get(tc_id)) if previous is not None else "missing"
        for tc_id in recommendation.test_case_ids
    }
    return Snapshot(impact_fingerprint=impact_fp, requirement_fingerprint=requirement_fingerprint(old_text, new_text),
                    case_fingerprints=cases)


def state_of(record: DecisionRecord, snapshot: Snapshot) -> DecisionState:
    unchanged = (
        record.impact_fingerprint == snapshot.impact_fingerprint
        and record.requirement_fingerprint == snapshot.requirement_fingerprint
        and record.case_fingerprints == snapshot.case_fingerprints
    )
    return DecisionState.CURRENT if unchanged else DecisionState.STALE


def _number(decision_id: str) -> int:
    return int(decision_id.removeprefix("DEC-"))


def next_decision_id(records: list[DecisionRecord]) -> str:
    return f"DEC-{max((_number(r.id) for r in records), default=0) + 1:03d}"


def latest_for(records: Iterable[DecisionRecord], requirement_id: str) -> DecisionRecord | None:
    """The most recent decision about a requirement, current or stale."""
    own = [r for r in records if r.requirement_id == requirement_id]
    return max(own, key=lambda r: _number(r.id), default=None)


def status_of(records: Iterable[DecisionRecord], requirement_id: str,
              snapshot: Snapshot) -> tuple[DecisionState, DecisionRecord | None]:
    latest = latest_for(records, requirement_id)
    if latest is None:
        return DecisionState.UNDECIDED, None
    return state_of(latest, snapshot), latest


# --- Storage -------------------------------------------------------------------------------------
#
# Every change is a transaction (see execution.py for the same pattern): read the latest saved file under
# its lock, add the record with the next free ID, write back. Entries that cannot be read are kept.


def _to_data(records: list[DecisionRecord], kept: list[Any]) -> dict[str, Any]:
    return {"format": FORMAT, "format_version": FORMAT_VERSION,
            "decisions": [r.model_dump(mode="json") for r in records] + kept}


def _parse(data: Any) -> tuple[list[DecisionRecord], list[Any]]:
    if data is None:
        return [], []
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("format_version") != FORMAT_VERSION:
        raise DecisionError("unreadable")
    raw = data.get("decisions")
    records: list[DecisionRecord] = []
    kept: list[Any] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        try:
            record = DecisionRecord.model_validate(item)
        except ValidationError:
            kept.append(item)
            continue
        if record.id in seen:
            kept.append(item)
            continue
        seen.add(record.id)
        records.append(record)
    return records[:MAX_DECISIONS], kept


class DecisionStore(Protocol):
    def records(self, project_id: str) -> list[DecisionRecord]: ...
    def add(self, project_id: str, make: Callable[[list[DecisionRecord]], DecisionRecord]) -> DecisionRecord: ...
    def delete_project(self, project_id: str) -> None: ...


class _Store:
    def _read(self, project_id: str) -> Any:
        raise NotImplementedError

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def _lock(self, project_id: str) -> Any:
        raise NotImplementedError

    def _unreadable(self, project_id: str) -> bool:
        return False

    def records(self, project_id: str) -> list[DecisionRecord]:
        try:
            return _parse(self._read(project_id))[0]
        except DecisionError:
            return []  # shown as empty; reading never writes

    def add(self, project_id: str, make: Callable[[list[DecisionRecord]], DecisionRecord]) -> DecisionRecord:
        with self._lock(project_id):
            if self._unreadable(project_id):
                raise DecisionError("unreadable")
            records, kept = _parse(self._read(project_id))
            record = make(records)  # chooses the ID and the supersedes link from the latest records
            if len(records) >= MAX_DECISIONS:
                raise DecisionError("full")
            self._write(project_id, _to_data([*records, record], kept))
            return record


class SessionDecisionStore(_Store):
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._mutex = threading.Lock()

    def _read(self, project_id: str) -> Any:
        return self._data.get(project_id)

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        self._data[project_id] = data

    def _lock(self, project_id: str) -> Any:
        return self._mutex

    def delete_project(self, project_id: str) -> None:
        self._data.pop(project_id, None)


class DiskDecisionStore(_Store):
    def _read(self, project_id: str) -> Any:
        return storage.load_impact_decisions_data(project_id)

    def _write(self, project_id: str, data: dict[str, Any]) -> None:
        storage.save_impact_decisions_data(project_id, data)

    def _lock(self, project_id: str) -> Any:
        return locked(storage.impact_decisions_path(project_id))

    def _unreadable(self, project_id: str) -> bool:
        return (storage.load_impact_decisions_data(project_id) is None
                and storage.impact_decisions_path(project_id).exists())

    def delete_project(self, project_id: str) -> None:
        storage.impact_decisions_path(project_id).unlink(missing_ok=True)


def open_decision_store(session_state: MutableMapping[Any, Any]) -> DecisionStore:
    """The store for the current storage mode; the session one lives in `session_state`."""
    if storage.persistence_enabled():
        return DiskDecisionStore()
    store = session_state.get("impact_decision_store")
    if not isinstance(store, SessionDecisionStore):
        store = session_state["impact_decision_store"] = SessionDecisionStore()
    return store


def record_decision(store: DecisionStore, project_id: str, *, recommendation: Recommendation, snapshot: Snapshot,
                    decision: Decision, previous_hash: str, new_hash: str, position_based: bool,
                    comment: str) -> DecisionRecord:
    """Record a decision about one recommendation. Refused while a current final decision (accepted or
    rejected) already stands for it; a stale one is superseded. Deferred does not block a later decision."""
    decided_at = datetime.now(UTC).isoformat(timespec="seconds")

    def make(records: list[DecisionRecord]) -> DecisionRecord:
        blocking = [
            r for r in records
            if r.requirement_id == recommendation.requirement_id and r.decision != Decision.DEFERRED
            and state_of(r, snapshot) == DecisionState.CURRENT
        ]
        if blocking:
            raise DecisionError("already_decided")
        previous = latest_for(records, recommendation.requirement_id)
        return DecisionRecord(
            id=next_decision_id(records), requirement_id=recommendation.requirement_id,
            position_based=position_based, action=recommendation.action, change=recommendation.change,
            test_case_ids=list(recommendation.test_case_ids), decision=decision,
            comment=comment.strip()[:COMMENT_MAX], decided_at=decided_at, previous_document_hash=previous_hash,
            new_document_hash=new_hash, impact_fingerprint=snapshot.impact_fingerprint,
            requirement_fingerprint=snapshot.requirement_fingerprint, case_fingerprints=dict(snapshot.case_fingerprints),
            supersedes=previous.id if previous is not None else "",
        )

    return store.add(project_id, make)

