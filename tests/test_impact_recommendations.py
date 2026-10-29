import csv
import io

from spec_to_test.change_impact import recommend
from spec_to_test.exports import impact_csv, impact_markdown
from spec_to_test.models import ChangeImpact, RequirementChange, ReviewStatus, TestCaseImpact, Workspace


def impact(changes=(), cases=()) -> ChangeImpact:
    return ChangeImpact(previous_title="Spec", previous_created_at="2026-10-01T10:00", changes=list(changes),
                        test_cases=list(cases))


def case(test_id: str, requirement_id: str, status=ReviewStatus.DRAFT, reason: str = "modified") -> TestCaseImpact:
    return TestCaseImpact(test_case_id=test_id, requirement_id=requirement_id, review_status=status, reason=reason)


def by_requirement(recommendations):
    return {r.requirement_id: r for r in recommendations}


def test_a_new_requirement_gets_add():
    rec = by_requirement(recommend(
        impact([RequirementChange(kind="added", new_id="REQ-3", new_text="New rule.")]),
        ["REQ-1", "REQ-3"],
    ))
    assert (rec["REQ-3"].action, rec["REQ-3"].change, rec["REQ-3"].regression) == ("add", "added", False)


def test_a_changed_draft_is_updated_and_a_changed_approved_test_is_reviewed_again():
    draft = recommend(impact([RequirementChange(kind="modified", old_id="REQ-1", new_id="REQ-1")],
                             [case("TC-1", "REQ-1")]), [])
    approved = recommend(impact([RequirementChange(kind="modified", old_id="REQ-1", new_id="REQ-1")],
                                [case("TC-1", "REQ-1", ReviewStatus.APPROVED)]), [])
    assert (draft[0].action, draft[0].test_case_ids, draft[0].regression) == ("update", ["TC-1"], False)
    assert (approved[0].action, approved[0].test_case_ids, approved[0].regression) == ("review", ["TC-1"], True)


def test_a_removed_requirement_removes_its_test_cases():
    [rec] = recommend(impact([RequirementChange(kind="removed", old_id="REQ-2", old_text="Old.")],
                             [case("TC-2", "REQ-2", ReviewStatus.APPROVED, "removed")]), [])
    assert (rec.requirement_id, rec.action, rec.test_case_ids, rec.regression) == ("REQ-2", "remove", ["TC-2"], False)


def test_an_unknown_match_is_reviewed_and_an_approved_one_is_also_run_again():
    [draft] = recommend(impact([RequirementChange(kind="unknown", old_id="REQ-4", old_text="?")],
                               [case("TC-4", "REQ-4", reason="unknown")]), [])
    [approved] = recommend(impact([RequirementChange(kind="unknown", old_id="REQ-4", old_text="?")],
                                  [case("TC-4", "REQ-4", ReviewStatus.APPROVED, "unknown")]), [])
    assert (draft.action, draft.regression) == ("review", False)
    assert (approved.action, approved.regression) == ("review", True)


def test_unchanged_requirements_are_kept_and_nothing_else_is_suggested():
    recs = recommend(impact([RequirementChange(kind="added", new_id="REQ-3", new_text="New.")]),
                     ["REQ-1", "REQ-2", "REQ-3"])
    assert [(r.requirement_id, r.action) for r in recs] == [("REQ-3", "add"), ("REQ-1", "keep"), ("REQ-2", "keep")]


def test_suggestions_never_change_test_case_statuses():
    source = impact([RequirementChange(kind="modified", old_id="REQ-1", new_id="REQ-1")],
                    [case("TC-1", "REQ-1", ReviewStatus.APPROVED)])
    before = source.model_dump()
    recommend(source, ["REQ-1"])
    assert source.model_dump() == before
    assert source.test_cases[0].review_status == ReviewStatus.APPROVED


def test_the_report_and_the_csv_list_every_recommendation():
    source = impact([RequirementChange(kind="removed", old_id="REQ-2", old_text="Old."),
                     RequirementChange(kind="added", new_id="REQ-3", new_text="New.")],
                    [case("TC-2", "REQ-2", ReviewStatus.APPROVED, "removed")])
    recs = recommend(source, ["REQ-1", "REQ-3"])
    ws = Workspace(change_impact=source)
    report = impact_markdown(ws, recs, "en")
    assert "| REQ-2 | Remove | Removed | TC-2 | — |" in report
    assert "| REQ-3 | Add | Added | — | — |" in report
    assert "Nothing is applied" in report
    rows = list(csv.reader(io.StringIO(impact_csv(recs, "en"))))
    assert len(rows) == len(recs) + 1  # header + one row per requirement
    assert [row[0] for row in rows[1:]] == [r.requirement_id for r in recs]
