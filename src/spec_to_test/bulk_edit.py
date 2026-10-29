"""Search, filters and bulk actions over a document's test cases.

Every action changes only the test cases it is given, and says how many it changed. Deleting is
never done without the caller's confirmation (the page asks for it); nothing is inferred or
generated here.
"""

from collections.abc import Iterable

from spec_to_test.models import ReviewStatus, TestCase, Workspace


def matches(tc: TestCase, query: str) -> bool:
    """True when every word of the query appears in the case's ID, title, requirement, preconditions, steps or result."""
    words = query.strip().lower().split()
    if not words:
        return True
    text = " ".join([tc.id, tc.title, tc.requirement_id, *tc.preconditions, *tc.steps, tc.expected_result]).lower()
    return all(word in text for word in words)


def filter_cases(cases: Iterable[TestCase], query: str = "", statuses: set[ReviewStatus] | None = None) -> list[TestCase]:
    """The cases that match the search text and, when given, have one of the review statuses."""
    return [
        tc for tc in cases
        if matches(tc, query) and (not statuses or tc.review_status in statuses)
    ]


def set_review_status(workspace: Workspace, case_ids: Iterable[str], status: ReviewStatus) -> int:
    """Set the review status of the given cases. Returns how many changed (already-set cases do not count)."""
    wanted = set(case_ids)
    changed = 0
    for tc in workspace.test_cases:
        if tc.id in wanted and tc.review_status != status:
            tc.review_status = status
            changed += 1
    return changed


def delete_cases(workspace: Workspace, case_ids: Iterable[str]) -> int:
    """Remove the given cases from the document. Returns how many were removed.

    Results of test runs that name these cases are kept in the runs file; they show as removed.
    """
    wanted = set(case_ids)
    before = len(workspace.test_cases)
    workspace.test_cases = [tc for tc in workspace.test_cases if tc.id not in wanted]
    return before - len(workspace.test_cases)
