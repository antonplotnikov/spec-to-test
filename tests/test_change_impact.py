from pathlib import Path

from streamlit.testing.v1 import AppTest

from conftest import goto, home
from spec_to_test.change_impact import change_impact, compare_requirements, impact_on_tests
from spec_to_test.models import DocumentSummary, Requirement, ReviewStatus, TestCase, TestType, Workspace

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


def req(rid: str, text: str, explicit: bool = True) -> Requirement:
    return Requirement(id=rid, text=text, has_explicit_id=explicit)


def tc(n: int, rid: str, status: ReviewStatus = ReviewStatus.DRAFT) -> TestCase:
    return TestCase(id=f"TC-{n}", requirement_id=rid, title="t", test_type=TestType.POSITIVE,
                    steps=["s"], expected_result="e", review_status=status)


OLD = [req("REQ-1", "The password must be at least 8 characters."), req("REQ-2", "The user must log in.")]


def kinds(changes) -> list[tuple[str, str, str]]:
    return [(c.kind, c.old_id, c.new_id) for c in changes]


def test_no_changes():
    reformatted = [req("REQ-1", "The password  must be at least 8 characters."), OLD[1]]
    assert compare_requirements(OLD, reformatted) == []


def test_added_modified_and_removed_by_explicit_ids():
    new = [req("REQ-1", "The password must be at least 12 characters."), req("REQ-3", "The user can log out.")]
    assert kinds(compare_requirements(OLD, new)) == [
        ("modified", "REQ-1", "REQ-1"), ("added", "", "REQ-3"), ("removed", "REQ-2", ""),
    ]


def test_added_and_removed_without_ids_when_unambiguous():
    old = [req("REQ-1", "A must happen.", False), req("REQ-2", "B must happen.", False)]
    assert kinds(compare_requirements(old, [*old, req("REQ-3", "C must happen.", False)])) == [("added", "", "REQ-3")]
    assert kinds(compare_requirements(old, old[:1])) == [("removed", "REQ-2", "")]


def test_paraphrase_without_ids_is_a_probable_modification():
    old = [req("REQ-1", "The user must log in with email and password.", False), req("REQ-2", "A must happen.", False)]
    new = [req("REQ-1", "The user must sign in using email and password.", False), old[1]]
    [change] = compare_requirements(old, new)
    assert (change.kind, change.old_id, change.new_id) == ("modified", "REQ-1", "REQ-1")
    assert change.similarity >= 0.75


def test_unrelated_texts_without_ids_are_added_and_removed():
    old = [req("REQ-1", "The password must be at least 8 characters long.", False)]
    new = [req("REQ-1", "The system must export reports to PDF.", False)]
    assert kinds(compare_requirements(old, new)) == [("added", "", "REQ-1"), ("removed", "REQ-1", "")]


def test_ambiguous_similarity_stays_unknown_and_keeps_tests_for_review():
    old = [req("REQ-1", "The system must send a confirmation email.", False)]
    new = [req("REQ-1", "The system must send a confirmation email to admins.", False),
           req("REQ-2", "The system must send a confirmation email to users.", False)]
    changes = compare_requirements(old, new)
    assert {c.kind for c in changes} == {"unknown"}
    previous = Workspace(requirements=old, test_cases=[tc(1, "REQ-1", ReviewStatus.APPROVED)])
    [impact] = impact_on_tests(previous, changes)
    assert (impact.reason, impact.review_status) == ("unknown", ReviewStatus.APPROVED)


def test_affected_test_cases_are_listed_and_statuses_kept():
    previous = Workspace(requirements=OLD, test_cases=[
        tc(1, "REQ-1", ReviewStatus.APPROVED), tc(2, "REQ-2"), tc(3, "REQ-2", ReviewStatus.APPROVED),
    ])
    new = [req("REQ-1", "The password must be at least 12 characters.")]
    impacts = impact_on_tests(previous, compare_requirements(OLD, new))
    assert [(i.test_case_id, i.reason, i.review_status) for i in impacts] == [
        ("TC-1", "modified", ReviewStatus.APPROVED),
        ("TC-2", "removed", ReviewStatus.DRAFT),
        ("TC-3", "removed", ReviewStatus.APPROVED),
    ]
    assert previous.test_cases[0].review_status == ReviewStatus.APPROVED


def test_previous_version_is_found_by_title_or_unknown():
    previous = Workspace(document_hash="old", title="spec.md", created_at="2026-01-01T00:00", requirements=OLD,
                         test_cases=[tc(1, "REQ-2", ReviewStatus.APPROVED)])
    new = Workspace(document_hash="new", title="spec.md", requirements=OLD[:1])
    summary = DocumentSummary(document_hash="old", title="spec.md", created_at=previous.created_at)
    impact = change_impact(new, [summary], lambda h: previous if h == "old" else None)
    assert impact.status == "compared" and impact.previous_document_hash == "old"
    assert [t.test_case_id for t in impact.test_cases] == ["TC-1"]
    # A different document is not a new version.
    other = DocumentSummary(document_hash="old", title="other.md", created_at=previous.created_at)
    assert change_impact(new, [other], lambda h: previous) is None
    # Two equally recent candidates: the previous version is Unknown.
    twin = summary.model_copy(update={"document_hash": "old2"})
    assert change_impact(new, [summary, twin], lambda h: previous).status == "unknown"


def test_reupload_of_changed_document_shows_impact_without_changing_statuses():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    v1 = "# Spec\nREQ-1: The password must be at least 8 characters.\nREQ-2: The user must log in.\n"
    home(at).text_area(key="requirements_text").input(v1).run()
    home(at).button(key="analyze").click().run()
    old_ws = at.session_state["workspace"]
    home(at).text_area(key="requirements_text").input(v1.replace("8", "12")).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    goto(at, "analysis")
    warning = "\n".join(w.value for w in at.warning)
    assert "modified 1" in warning and "REQ-1: the requirement text changed" in warning
    assert "Review statuses were not changed" in warning
    assert all(tc.review_status == ReviewStatus.DRAFT for tc in old_ws.test_cases)
    assert at.session_state["workspace"].change_impact.changes[0].kind == "modified"
