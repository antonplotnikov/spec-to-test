"""Status changes of rule findings, with a change history.

A finding is resolved only from a clarification the user confirmed in Grill
Mode (grill.integration.resolve_findings, which calls `resolve` here). Any
resolved finding can be reopened, and the most recent change in a document can
be undone. Every change, including an undo, is appended to
`Workspace.finding_history` with its time, an optional reason, and where it
came from; nothing in the history is edited or removed.

A contradiction is reported on both requirements of the pair; both findings
always change together, so the pair never ends up half resolved.

Every function returns a changed copy of the workspace and leaves its input
untouched. Errors carry a `code` that maps to the findings.error.<code> text.
"""

from datetime import UTC, datetime
from uuid import uuid4

from spec_to_test.models import (
    MAX_REASON_LENGTH,
    ClarificationStatus,
    Finding,
    FindingChange,
    FindingEvent,
    FindingType,
    Workspace,
)

_STATUS_AFTER = {FindingChange.RESOLVED: ClarificationStatus.RESOLVED, FindingChange.REOPENED: ClarificationStatus.NEEDS_CLARIFICATION}
_OPPOSITE = {FindingChange.RESOLVED: FindingChange.REOPENED, FindingChange.REOPENED: FindingChange.RESOLVED}


class FindingError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def clean_reason(reason: str) -> str:
    cleaned = " ".join(reason.split())
    if len(cleaned) > MAX_REASON_LENGTH:
        raise FindingError("reason_too_long")
    return cleaned


def finding_by_key(workspace: Workspace, key: str) -> Finding | None:
    return next((f for f in workspace.findings if f.key == key), None)


def linked_keys(workspace: Workspace, key: str) -> list[str]:
    """`key` plus the other side of its contradiction, if any."""
    finding = finding_by_key(workspace, key)
    if finding is None:
        return []
    if finding.type != FindingType.CONTRADICTION:
        return [key]
    pair = {finding.requirement_id, *finding.related_requirement_ids}
    return [
        f.key for f in workspace.findings
        if f.type == FindingType.CONTRADICTION and {f.requirement_id, *f.related_requirement_ids} == pair
    ]


def history(workspace: Workspace, key: str) -> list[FindingEvent]:
    """Every recorded change of the finding (and its contradiction twin), oldest first."""
    keys = set(linked_keys(workspace, key)) or {key}
    return [e for e in workspace.finding_history if e.finding_key in keys]


def resolved_findings(workspace: Workspace) -> list[Finding]:
    """Resolved findings, one per contradiction pair."""
    seen: set[str] = set()
    result = []
    for finding in workspace.findings:
        if finding.status != ClarificationStatus.RESOLVED or finding.key in seen:
            continue
        seen.update(linked_keys(workspace, finding.key))
        result.append(finding)
    return result


def _apply(
    workspace: Workspace,
    keys: list[str],
    change: FindingChange,
    *,
    reason: str,
    via: str,
    at: str | None,
    grill_session_id: str = "",
    clarification: str = "",
    undoes: str = "",
    batch: str = "",
) -> Workspace:
    reason = clean_reason(reason)
    wanted_before = ClarificationStatus.NEEDS_CLARIFICATION if change == FindingChange.RESOLVED else ClarificationStatus.RESOLVED
    expanded = list(dict.fromkeys(k for key in keys for k in linked_keys(workspace, key)))
    targets = [k for k in expanded if (f := finding_by_key(workspace, k)) is not None and f.status == wanted_before]
    if not targets:
        raise FindingError("nothing_to_resolve" if change == FindingChange.RESOLVED else "not_resolved")
    updated = workspace.model_copy(deep=True)
    stamp = at or now()
    batch = batch or uuid4().hex[:12]
    by_key = {f.key: f for f in updated.findings}
    for key in targets:
        finding = by_key[key]
        finding.status = _STATUS_AFTER[change]
        updated.finding_history.append(FindingEvent(
            finding_key=key, requirement_id=finding.requirement_id, change=change, at=stamp, reason=reason,
            via=via, grill_session_id=grill_session_id, clarification=clarification, undoes=undoes,  # type: ignore[arg-type]
            batch=batch,
        ))
    return updated


def resolve(
    workspace: Workspace,
    keys: list[str],
    *,
    reason: str = "",
    grill_session_id: str = "",
    clarification: str = "",
    at: str | None = None,
    batch: str = "",
) -> Workspace:
    """Mark open findings resolved by a confirmed Grill clarification.

    Pass the same `batch` to several calls that make up one user action.
    """
    return _apply(
        workspace, keys, FindingChange.RESOLVED, reason=reason, via="grill", at=at,
        grill_session_id=grill_session_id, clarification=clarification, batch=batch,
    )


def new_batch() -> str:
    return uuid4().hex[:12]


def reopen(workspace: Workspace, key: str, *, reason: str = "", at: str | None = None) -> Workspace:
    """Put a resolved finding back to "needs clarification"."""
    return _apply(workspace, [key], FindingChange.REOPENED, reason=reason, via="manual", at=at)


def last_change(workspace: Workspace) -> list[FindingEvent]:
    """The events of the most recent action in the document, or [] if it cannot be undone.

    It can be undone only while every finding it touched still has the status it set.
    """
    if not workspace.finding_history:
        return []
    last = workspace.finding_history[-1]
    tail = [last]
    if last.batch:
        for event in reversed(workspace.finding_history[:-1]):
            if event.batch != last.batch:
                break
            tail.insert(0, event)
    for event in tail:
        finding = finding_by_key(workspace, event.finding_key)
        if finding is None or finding.status != _STATUS_AFTER[event.change]:
            return []
    return tail


def undo_last(workspace: Workspace, *, reason: str = "", at: str | None = None) -> Workspace:
    """Revert the most recent change (resolve or reopen); the undo is itself recorded."""
    events = last_change(workspace)
    if not events:
        raise FindingError("nothing_to_undo")
    change = _OPPOSITE[events[-1].change]
    return _apply(
        workspace, [e.finding_key for e in events], change, reason=reason, via="undo", at=at,
        undoes=",".join(e.id for e in events),
    )
