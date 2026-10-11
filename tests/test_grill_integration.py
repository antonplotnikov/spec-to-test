"""Finalized Grill results in the workspace, coverage, exports and Markdown."""

import pytest

from spec_to_test import exports
from spec_to_test.exports import jira_defects_csv, jira_test_cases_csv, markdown_report, rtm_csv
from spec_to_test.grill.integration import (
    IntegrationError,
    add_blocker,
    add_to_workspace,
    context_blocker,
    markdown_file_name,
    open_questions,
    resolutions,
    resolve_blocker,
    resolve_findings,
    result_markdown,
)
from spec_to_test.grill.models import (
    AnswerStatus,
    ArtifactType,
    BugReportDraft,
    GrillKind,
    GrillSession,
    GrillStep,
    Provenance,
    RequirementsDraft,
    TestCaseDraft,
)
from spec_to_test.grill.planner import DETERMINISTIC_WORKFLOW as WF
from spec_to_test.grill.text import render_question
from spec_to_test.i18n import LANGUAGES, t
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import (
    ClarificationStatus,
    Requirement,
    ReviewStatus,
    Severity,
    Source,
    TestType,
    Workspace,
)
from spec_to_test.quality import score_all
from spec_to_test.rtm import Coverage, build_rtm, coverage_of
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.storage import load_workspace, save_workspace
from spec_to_test.test_generator import generate_test_cases

REQS = """REQ-1: The password must be at least 8 characters.
REQ-2: The password must be at least 10 characters.
REQ-3: The page should load fast."""
CONTRADICTION = "rule.contradiction.REQ-1+REQ-2"
VAGUE = "rule.ambiguous_wording.REQ-3"


def workspace(text: str = REQS) -> Workspace:
    result = analyze_requirements(extract_requirements(text))
    ws = Workspace(document_hash="doc", requirements=result.requirements, findings=result.findings)
    ws.test_cases = generate_test_cases(ws)
    return ws


def tc_draft(**changes) -> TestCaseDraft:
    values = dict(
        title="Password of 8 characters is accepted", requirement_id="REQ-1", test_type=TestType.POSITIVE,
        preconditions=["The sign-up page is open"], test_data=["Passw0rd"],
        steps=["Enter the password", "Submit the form"], expected_result="The password is accepted",
    )
    return TestCaseDraft(**{**values, **changes})


def bug_draft(**changes) -> BugReportDraft:
    values = dict(
        summary="Save crashes the editor", requirement_id="REQ-1", environment="Chrome 140",
        steps=["Open a document", "Click Save"], actual_result="The editor closes",
        expected_result="The document is saved", severity=Severity.HIGH,
    )
    return BugReportDraft(**{**values, **changes})


def finalize(session: GrillSession) -> GrillSession:
    if session.step == GrillStep.ASK_QUESTION:
        session = WF.proceed_to_draft(session)
    if session.step != GrillStep.REVIEW:
        session = WF.review(session)
    assert not session.blocking_findings, session.blocking_findings
    session = WF.request_confirmation(session, accept_unresolved=True)
    return WF.confirm(session)


def reviewed(draft: TestCaseDraft | BugReportDraft, ws: Workspace | None = None) -> GrillSession:
    """A QA Review session for the draft, confirmed by the user."""
    context = ws.requirements if ws else []
    start = WF.start(GrillKind.REVIEW, artifact=ArtifactType(draft.draft_type), context_requirements=context)
    return finalize(WF.submit_input(start, draft))


def clarified(ws: Workspace, contradiction: AnswerStatus = AnswerStatus.ANSWERED) -> GrillSession:
    """Requirements Grill on the workspace document: the contradiction is answered, REQ-3 is assumed."""
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=ws.requirements))
    assert session.current_question_id == CONTRADICTION
    session = WF.answer(session, "REQ-2: The password must be at least 10 characters.", contradiction)
    assert session.current_question_id == VAGUE
    session = WF.answer(session, "Within 2 seconds", AnswerStatus.ASSUMED)
    return finalize(session)


# --- Test cases ----------------------------------------------------------------------

def test_confirmed_test_case_becomes_a_draft_user_test_case():
    ws = workspace()
    draft = tc_draft(provenance={"expected_result": Provenance.ASSUMPTION})
    updated, case_id = add_to_workspace(reviewed(draft, ws), ws)
    case = next(tc for tc in updated.test_cases if tc.id == case_id)
    assert case_id == f"TC-{len(ws.test_cases) + 1:03d}"
    assert case.source == Source.USER and case.review_status == ReviewStatus.DRAFT
    assert case.requirement_id == "REQ-1" and case.steps == draft.steps
    assert case.preconditions == ["The sign-up page is open", "Test data: Passw0rd"]
    # An assumed value is kept as an assumption, never as a confirmed fact.
    assert case.assumptions == ["Expected result: The password is accepted (Assumption (not confirmed))"]
    assert len(ws.test_cases) == len(updated.test_cases) - 1  # the input is not modified


def test_added_test_case_reaches_rtm_coverage_and_every_export():
    ws = Workspace(requirements=workspace().requirements, findings=workspace().findings)
    updated, case_id = add_to_workspace(reviewed(tc_draft(), ws), ws)
    assert coverage_of(ws, "REQ-1") == Coverage.NOT_COVERED
    assert coverage_of(updated, "REQ-1") == Coverage.PARTIAL  # Draft: not covered until approved
    rows = build_rtm(updated)
    assert rows[0].test_case_ids == [case_id]
    for export in (jira_test_cases_csv(updated), rtm_csv(rows), markdown_report(updated, rows)):
        assert case_id in export
    for export in (jira_test_cases_csv(updated), exports.testrail_csv(updated), markdown_report(updated, rows)):
        assert "Password of 8 characters is accepted" in export
    assert "Test data: Passw0rd" in jira_test_cases_csv(updated)
    updated.test_cases[0].review_status = ReviewStatus.APPROVED
    assert coverage_of(updated, "REQ-1") == Coverage.COVERED


def test_test_case_is_added_only_once():
    ws = workspace()
    session = reviewed(tc_draft(), ws)
    updated, _ = add_to_workspace(session, ws)
    assert add_blocker(session, updated) == "already_added"
    with pytest.raises(IntegrationError) as error:
        add_to_workspace(session, updated)
    assert error.value.code == "already_added"


def test_open_questions_travel_with_the_test_case():
    ws = workspace()
    session = WF.submit_input(WF.start(GrillKind.TEST_CASE, context_requirements=ws.requirements), tc_draft(objective=""))
    assert session.current_question_id == "tc.objective"
    session = finalize(WF.answer(session, "", AnswerStatus.UNKNOWN))
    question = session.question("tc.objective")
    assert question is not None
    expected = render_question(question)[0]
    assert open_questions(session) == [expected]
    assert add_to_workspace(session, ws)[0].test_cases[-1].clarification_questions == [expected]


@pytest.mark.parametrize(
    ("draft", "context", "code"),
    [
        (tc_draft(), None, "no_workspace"),
        (tc_draft(requirement_id="", feature="Sign-up"), "ws", "requirement_link_required"),
        (tc_draft(requirement_id="REQ-9"), "other", "context_changed"),
    ],
)
def test_test_case_that_cannot_be_linked_is_not_added(draft, context, code):
    ws = workspace()
    other = Workspace(requirements=[Requirement(id="REQ-9", text="The password must be at least 8 characters.")])
    session = reviewed(draft, {"ws": ws, "other": other}.get(context))
    target = None if context is None else ws
    assert add_blocker(session, target) == code
    with pytest.raises(IntegrationError):
        add_to_workspace(session, target)


def test_unconfirmed_session_cannot_be_added_or_exported():
    ws = workspace()
    session = WF.submit_input(WF.start(GrillKind.REVIEW, artifact=ArtifactType.TEST_CASE), tc_draft())
    assert add_blocker(session, ws) == "not_finalized"
    with pytest.raises(IntegrationError):
        result_markdown(session)
    cancelled = WF.cancel(session)
    assert add_blocker(cancelled, ws) == "not_finalized"


# --- Bug reports ------------------------------------------------------------------------

def test_confirmed_bug_becomes_a_defect_report_without_invented_details():
    ws = workspace()
    draft = bug_draft(provenance={"app_version": Provenance.UNKNOWN}, evidence=["console.log"])
    session = reviewed(draft, ws)
    updated, bug_id = add_to_workspace(session, ws)
    report = next(d for d in updated.defects if d.id == bug_id)
    assert bug_id == "BUG-001" and report.source == Source.USER
    assert (report.title, report.severity, report.requirement_id) == ("Save crashes the editor", Severity.HIGH, "REQ-1")
    assert report.description == "The editor closes"
    assert report.expected_behavior == "The document is saved"
    context = report.reproduction_context.splitlines()
    assert "Environment: Chrome 140" in context
    assert "Application version: Unknown" in context  # said to be unknown, not guessed
    assert context[context.index("Steps:") + 1:context.index("Steps:") + 3] == ["1. Open a document", "2. Click Save"]
    assert "- console.log" in context
    assert not any(line.startswith(("Reproducibility", "Priority")) for line in context)  # never filled in
    assert add_blocker(session, updated) == "already_added"


def test_added_bug_reaches_rtm_and_bug_exports():
    ws = workspace()
    updated, bug_id = add_to_workspace(reviewed(bug_draft(), ws), ws)
    rows = build_rtm(updated)
    assert rows[0].defect_ids == [bug_id]
    for export in (jira_defects_csv(updated.defects), markdown_report(updated, rows), rtm_csv(rows)):
        assert bug_id in export
    assert "Save crashes the editor" in jira_defects_csv(updated.defects)


@pytest.mark.parametrize(
    ("changes", "code"),
    [({"severity": None}, "severity_required"), ({"requirement_id": ""}, "requirement_link_required")],
)
def test_bug_without_severity_or_requirement_stays_out_of_the_workspace(changes, code):
    ws = workspace()
    session = reviewed(bug_draft(**changes), ws)
    assert add_blocker(session, ws) == code
    assert "Save crashes the editor" in result_markdown(session)  # still available as Markdown


# --- Same requirement ID in another document ---------------------------------------------

OTHER_DOC = """REQ-1: The user must be able to log out.
REQ-2: The system must send a reset email within 5 minutes."""


def reset_tc(**changes) -> TestCaseDraft:
    return tc_draft(
        title="Reset email arrives", requirement_id="REQ-2", test_data=[],
        steps=["Request a reset"], expected_result="An email arrives", **changes,
    )


def test_same_requirement_id_in_another_document_is_not_linked():
    doc_a, doc_b = workspace(), workspace(OTHER_DOC)
    assert doc_a.requirement("REQ-2") and doc_b.requirement("REQ-2")  # the ID alone matches
    for draft in (reset_tc(), bug_draft(requirement_id="REQ-2")):
        session = reviewed(draft, doc_a)
        assert add_blocker(session, doc_a) is None  # fine on its own document
        assert context_blocker(session, doc_b) == "context_changed"
        assert add_blocker(session, doc_b) == "context_changed"
        before = doc_b.model_dump()
        with pytest.raises(IntegrationError) as error:
            add_to_workspace(session, doc_b)
        assert error.value.code == "context_changed"
        assert doc_b.model_dump() == before  # the refused call left the workspace untouched
        assert not any(tc.source == Source.USER for tc in doc_b.test_cases) and not doc_b.defects
        added, _ = add_to_workspace(session, doc_a)  # the same result does go to its own document
        assert added.model_dump() != doc_a.model_dump()
        assert result_markdown(session)  # still downloadable


def test_whole_context_is_compared_not_just_the_linked_requirement():
    doc_a = workspace()
    edited = workspace(REQS.replace("load fast", "load in 2 seconds"))  # REQ-2 identical, REQ-3 differs
    session = reviewed(reset_tc(), doc_a)
    assert doc_a.requirement("REQ-2") == edited.requirement("REQ-2")
    assert add_blocker(session, edited) == "context_changed"


def test_reanalyzing_the_same_document_keeps_the_session_valid():
    session = reviewed(reset_tc(), workspace())
    again = workspace()  # an independent analysis of the same text
    assert context_blocker(session, again) is None
    updated, item_id = add_to_workspace(session, again)
    case = next(tc for tc in updated.test_cases if tc.id == item_id)
    assert (case.source, case.review_status, case.requirement_id) == (Source.USER, ReviewStatus.DRAFT, "REQ-2")


def test_session_without_a_document_snapshot_is_not_linked_to_a_later_document():
    ws = workspace()
    session = reviewed(reset_tc())  # started before any document was analyzed
    assert add_blocker(session, ws) == "context_unknown"
    assert add_blocker(session, None) == "no_workspace"


def test_added_and_approved_test_case_still_covers_its_requirement():
    ws = workspace()
    updated, item_id = add_to_workspace(reviewed(reset_tc(), ws), ws)
    approved = updated.model_copy(deep=True)
    next(tc for tc in approved.test_cases if tc.id == item_id).review_status = ReviewStatus.APPROVED
    assert coverage_of(approved, "REQ-2") != coverage_of(updated, "REQ-2")


def test_requirements_grill_on_pasted_text_has_no_snapshot_and_still_resolves():
    ws = workspace()
    pasted = [r for r in ws.requirements if r.id in ("REQ-1", "REQ-2")]  # text pasted by hand, same wording
    session = WF.submit_input(WF.start(GrillKind.REQUIREMENTS), RequirementsDraft(requirements=pasted))
    assert session.context_requirements == []
    session = finalize(WF.answer(session, "REQ-2 wins: at least 10 characters.", AnswerStatus.ANSWERED))
    assert resolve_blocker(session, ws) is None
    assert [r.question_id for r in resolutions(session, ws)] == [CONTRADICTION]
    assert any(f.status == ClarificationStatus.RESOLVED for f in resolve_findings(session, ws, [CONTRADICTION]).findings)
    assert add_blocker(session, ws) == "nothing_to_add"  # unchanged: requirements results are not items


def test_resolve_still_compares_requirement_text_not_the_whole_context():
    ws = workspace()
    session = clarified(ws)
    same_requirements_other_tail = workspace(REQS + "\nREQ-4: Sessions must expire after 30 minutes.")
    assert resolve_blocker(session, same_requirements_other_tail) is None  # compatibility kept on purpose


# --- Resolving requirement findings ------------------------------------------------------

def test_only_confirmed_clarifications_can_resolve_findings():
    ws = workspace()
    options = resolutions(clarified(ws), ws)
    assert [o.question_id for o in options] == [CONTRADICTION]  # REQ-3 was only assumed
    assert set(options[0].finding_keys) == {"REQ-1|contradiction|REQ-2", "REQ-2|contradiction|REQ-1"}
    assert resolutions(clarified(ws, AnswerStatus.UNKNOWN), ws) == []


def test_resolving_is_explicit_and_updates_quality_and_rtm():
    ws = workspace()
    session = clarified(ws)
    with pytest.raises(IntegrationError) as error:
        resolve_findings(session, ws, [])
    assert error.value.code == "nothing_selected"
    with pytest.raises(IntegrationError):
        resolve_findings(session, ws, [VAGUE])  # assumed, not confirmed
    updated = resolve_findings(session, ws, [CONTRADICTION])
    assert [f.status for f in ws.findings].count(ClarificationStatus.RESOLVED) == 0  # input untouched
    statuses = {f.key: f.status for f in updated.findings}
    assert statuses["REQ-1|contradiction|REQ-2"] == statuses["REQ-2|contradiction|REQ-1"] == ClarificationStatus.RESOLVED
    assert statuses["REQ-3|ambiguous_wording|"] == ClarificationStatus.NEEDS_CLARIFICATION
    before, after = score_all(ws.requirements, ws.findings), score_all(updated.requirements, updated.findings)
    assert after["REQ-1"].score > before["REQ-1"].score
    assert build_rtm(updated)[0].open_issues == []
    assert resolutions(session, updated) == []  # nothing left to resolve


def test_findings_of_another_document_are_not_resolved():
    ws = workspace()
    session = clarified(ws)
    edited = workspace(REQS.replace("10 characters", "12 characters"))
    assert resolve_blocker(session, edited) == "requirements_not_in_workspace"
    assert resolve_blocker(session, None) == "no_workspace"
    assert resolutions(session, edited) == []
    with pytest.raises(IntegrationError):
        resolve_findings(session, edited, [CONTRADICTION])


def test_requirements_results_are_not_added_as_items():
    ws = workspace()
    assert add_blocker(clarified(ws), ws) == "nothing_to_add"


# --- Markdown and storage ---------------------------------------------------------------

def test_markdown_keeps_origins_open_items_and_escapes_text():
    ws = workspace()
    draft = tc_draft(title="Use **bold** | pipes", provenance={"expected_result": Provenance.ASSUMPTION})
    session = reviewed(draft, ws)
    md = result_markdown(session)
    assert md.startswith("# Test case\n")
    assert r"Use \*\*bold\*\* \| pipes" in md
    assert "Assumption (not confirmed)" in md
    assert "Review findings accepted as unresolved" in md
    assert markdown_file_name(session) == f"grill-test-case-{session.id[:8]}.md"


def test_requirements_markdown_separates_source_from_clarifications():
    ws = workspace()
    md = result_markdown(clarified(ws))
    source, clarifications = md.split("## Clarifications")
    assert "REQ-3" in source and "The page should load fast." in source
    assert "Within 2 seconds" in clarifications and "Assumption (not confirmed)" in clarifications
    assert "Confirmed by you" in clarifications


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_markdown_and_added_items_are_localized(lang):
    ws = workspace()
    md = result_markdown(reviewed(tc_draft(), ws), lang)
    assert md.startswith(f"# {t('grill.artifact.test_case', lang)}") and t("grill.export.note", lang) in md
    case = add_to_workspace(reviewed(tc_draft(), ws), ws, lang)[0].test_cases[-1]
    assert case.preconditions[-1] == t("grill.export.test_data_item", lang, value="Passw0rd")
    report = add_to_workspace(reviewed(bug_draft(), ws), ws, lang)[0].defects[-1]
    assert report.reproduction_context.endswith(t("grill.export.created_by_grill", lang))


def test_workspace_with_grill_items_is_saved_and_loaded():
    ws = workspace()
    updated, case_id = add_to_workspace(reviewed(tc_draft(), ws), ws)
    updated, bug_id = add_to_workspace(reviewed(bug_draft(), updated), updated)
    updated = resolve_findings(clarified(updated), updated, [CONTRADICTION])
    save_workspace(updated)
    restored = load_workspace("doc")
    assert restored == updated
    assert restored.test_cases[-1].source == Source.USER and restored.defects[-1].origin_key.startswith("grill|")
