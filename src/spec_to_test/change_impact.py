"""Requirement change impact: compare a new version of a document with the
previous one and find the test cases that need review.

The previous version is the most recent other document in the project with the
same title (file name or first line). If two candidates are equally recent, it
is Unknown which one is the previous version and nothing is compared.

Requirements are matched by ID only when every requirement in both versions
has an explicit ID in the source; otherwise only identical texts are matched,
because auto-numbered IDs follow position, not meaning. Requirements left over
are paired by text similarity: a clear, mutual best match is "modified" (a
likely rewording, with its similarity recorded), a requirement that resembles
some leftover without such a clear match is Unknown, and one that resembles
none is added or removed. Similarity is a hint, not proof: every test case of a
modified, removed or Unknown requirement is still listed for review.

Test case statuses are never changed: affected test cases are only listed with
the reason, so the reviewer decides.
"""

from collections.abc import Callable
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel

from spec_to_test.models import (
    ChangeImpact,
    DocumentSummary,
    Requirement,
    RequirementChange,
    ReviewStatus,
    TestCaseImpact,
    Workspace,
)
from spec_to_test.rule_engine import _normalize

# Text similarity (0-1) of two requirements without explicit IDs. A pair at or
# above CONFIDENT, ahead of every other candidate by MARGIN, is a likely
# rewording ("modified"); anything from RELATED up that is not such a pair stays
# Unknown. Below RELATED texts are treated as unrelated (added / removed).
CONFIDENT = 0.75
MARGIN = 0.1
RELATED = 0.6


def _same_text(text: str) -> str:
    return " ".join(_normalize(text).split())


def compare_requirements(old: list[Requirement], new: list[Requirement]) -> list[RequirementChange]:
    """Differences between two versions, in document order (removed/unknown old ones last)."""
    changes: list[RequirementChange] = []
    if all(r.has_explicit_id for r in old + new) and old and new:
        old_by_id = {r.id: r for r in old}
        new_ids = {r.id for r in new}
        for req in new:
            before = old_by_id.get(req.id)
            if before is None:
                changes.append(RequirementChange(kind="added", new_id=req.id, new_text=req.text))
            elif _same_text(before.text) != _same_text(req.text):
                changes.append(RequirementChange(kind="modified", old_id=req.id, new_id=req.id,
                                                 old_text=before.text, new_text=req.text))
        changes += [
            RequirementChange(kind="removed", old_id=r.id, old_text=r.text) for r in old if r.id not in new_ids
        ]
        return changes

    old_texts = {_same_text(r.text) for r in old}
    new_texts = {_same_text(r.text) for r in new}
    left_old = [r for r in old if _same_text(r.text) not in new_texts]
    left_new = [r for r in new if _same_text(r.text) not in old_texts]
    scores = {(o.id, n.id): _similarity(o.text, n.text) for o in left_old for n in left_new}
    paired = _confident_pairs(left_old, left_new, scores)
    old_by_id = {r.id: r for r in left_old}
    for r in left_new:
        if (old_id := paired.get(r.id)) is not None:
            before = old_by_id[old_id]
            changes.append(RequirementChange(kind="modified", old_id=old_id, new_id=r.id, old_text=before.text,
                                             new_text=r.text, similarity=scores[old_id, r.id]))
        else:
            related = any(scores[o.id, r.id] >= RELATED for o in left_old if o.id not in paired.values())
            changes.append(RequirementChange(kind="unknown" if related else "added", new_id=r.id, new_text=r.text))
    for r in left_old:
        if r.id not in paired.values():
            related = any(scores[r.id, n.id] >= RELATED for n in left_new if n.id not in paired)
            changes.append(RequirementChange(kind="unknown" if related else "removed", old_id=r.id, old_text=r.text))
    return changes


def _similarity(a: str, b: str) -> float:
    return round(SequenceMatcher(None, _same_text(a).lower(), _same_text(b).lower()).ratio(), 2)


def _confident_pairs(
    old: list[Requirement], new: list[Requirement], scores: dict[tuple[str, str], float]
) -> dict[str, str]:
    """New ID -> old ID for rewordings that are unambiguous: each is the other's clear best match."""
    pairs: dict[str, str] = {}
    for o in old:
        row = sorted(((scores[o.id, n.id], n.id) for n in new), reverse=True)
        if not row or row[0][0] < CONFIDENT:
            continue
        best, n_id = row[0]
        column = sorted((scores[x.id, n_id] for x in old), reverse=True)
        runner_up = max(row[1][0] if len(row) > 1 else 0.0, column[1] if len(column) > 1 else 0.0)
        if column[0] == best and best - runner_up >= MARGIN:
            pairs[n_id] = o.id
    return pairs


def impact_on_tests(previous: Workspace, changes: list[RequirementChange]) -> list[TestCaseImpact]:
    """Test cases of the previous version linked to a removed, modified or unknown requirement."""
    reasons = {c.old_id: c.kind for c in changes if c.old_id and c.kind in ("removed", "modified", "unknown")}
    return [
        TestCaseImpact(test_case_id=tc.id, requirement_id=tc.requirement_id,
                       review_status=tc.review_status, reason=reasons[tc.requirement_id])
        for tc in previous.test_cases
        if tc.requirement_id in reasons
    ]


def change_impact(
    workspace: Workspace,
    documents: list[DocumentSummary],
    load: Callable[[str], Workspace | None],
) -> ChangeImpact | None:
    """Impact of `workspace` against its previous version; None when it has none (a new document)."""
    candidates = [
        d for d in documents
        if workspace.title and d.title == workspace.title and d.document_hash != workspace.document_hash
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda d: d.created_at)
    tied = [d for d in candidates if d.created_at == latest.created_at]
    previous = load(latest.document_hash) if len(tied) == 1 and latest.created_at else None
    if previous is None:
        return ChangeImpact(status="unknown", previous_title=workspace.title)
    changes = compare_requirements(previous.requirements, workspace.requirements)
    return ChangeImpact(
        previous_document_hash=previous.document_hash,
        previous_title=previous.title,
        previous_created_at=previous.created_at,
        changes=changes,
        test_cases=impact_on_tests(previous, changes),
    )


# --- Recommendations ---------------------------------------------------------------------

RecommendedAction = Literal["keep", "update", "add", "remove", "review"]


class Recommendation(BaseModel):
    """What to do about one requirement after a change. A suggestion: nothing is applied."""

    requirement_id: str
    action: RecommendedAction
    change: Literal["added", "modified", "removed", "unknown", "unchanged"]
    # Test cases of the previous version that concern this requirement.
    test_case_ids: list[str] = []
    # True when an Approved test case concerns the requirement: it must be run again.
    regression: bool = False


def recommend(impact: ChangeImpact, requirement_ids: list[str]) -> list[Recommendation]:
    """Suggested action per changed requirement, and Keep for the unchanged ones.

    - added:    Add test cases; the requirement is new, so none exists yet.
    - modified: Update draft test cases; an Approved one must be reviewed again.
    - removed:  Remove its test cases; the requirement is gone.
    - unknown:  Review; the previous version has no reliable match.
    - others:   Keep.

    Statuses are never changed here: a reviewer decides, one suggestion at a time.
    """
    affected: dict[str, list[TestCaseImpact]] = {}
    for tc in impact.test_cases:
        affected.setdefault(tc.requirement_id, []).append(tc)
    recommendations: list[Recommendation] = []
    touched: set[str] = set()
    for change in impact.changes:
        requirement = change.new_id or change.old_id
        touched.add(requirement)
        if change.kind == "added":
            recommendations.append(Recommendation(requirement_id=requirement, action="add", change="added"))
            continue
        cases = affected.get(change.old_id, [])
        approved = any(tc.review_status == ReviewStatus.APPROVED for tc in cases)
        if change.kind == "modified":
            action: RecommendedAction = "review" if approved else "update"
        elif change.kind == "removed":
            action = "remove"
        else:
            action = "review"
        recommendations.append(Recommendation(
            requirement_id=requirement, action=action, change=change.kind,
            test_case_ids=[tc.test_case_id for tc in cases],
            regression=approved and change.kind in ("modified", "unknown"),
        ))
    recommendations += [
        Recommendation(requirement_id=rid, action="keep", change="unchanged")
        for rid in requirement_ids if rid not in touched
    ]
    return recommendations
