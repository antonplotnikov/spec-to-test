"""Hand a finalized Grill result to the rest of the app.

- A test case becomes a Draft `TestCase` in the workspace, so it appears in the
  test list, the RTM, coverage and every existing export. It counts as covering
  its requirement only after someone approves it, like any other test case.
- A bug report linked to a real requirement, with a severity, becomes a
  `DefectReport`. Product-bug details (steps, actual result, environment, ...)
  are written into its text fields; unknown values are written as unknown.
- Any result can be downloaded as Markdown that keeps provenance and open items.
- Requirements Grill: rule findings the user clarified may be marked resolved,
  one by one and only on request (it changes quality scores and coverage views).

Nothing here works before the user confirmed the session (step FINALIZED), and
nothing is invented: a missing requirement link or severity stops the hand-over
instead of being filled in.
"""

from dataclasses import dataclass

from spec_to_test.bug_reports import next_defect_id
from spec_to_test.exports import _md_table
from spec_to_test.formatting import escape_markdown
from spec_to_test.grill.drafts import AnyDraft, editable_fields, field_is_empty
from spec_to_test.grill.models import (
    BugReportDraft,
    GrillSession,
    GrillStep,
    Provenance,
    RequirementsDraft,
    TestCaseDraft,
)
from spec_to_test.grill.rules import RULE_QUESTION_PREFIX, rule_question_id
from spec_to_test.grill.text import draft_rows, field_label, render_finding, render_question, value_text
from spec_to_test.i18n import t
from spec_to_test.models import ClarificationStatus, DefectReport, Source, TestCase, Workspace
from spec_to_test.test_generator import next_test_case_id

# Values the user did not confirm; they are carried over as assumptions.
_UNCONFIRMED = (Provenance.ASSUMPTION, Provenance.AI_SUGGESTION)


class IntegrationError(Exception):
    """The result cannot be handed over. `code` maps to grill.error.<code>."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def origin_key(session: GrillSession) -> str:
    """Links a bug report to the Grill session that produced it (one report per session)."""
    return f"grill|{session.id}"


# ---------------------------------------------------------------------------
# Workspace hand-over
# ---------------------------------------------------------------------------

def context_blocker(session: GrillSession, workspace: Workspace | None) -> str | None:
    """Why the session's document is not the workspace's document, or None if it is.

    A requirement ID alone does not identify a requirement: two documents can
    both have REQ-2. The session keeps a snapshot of the requirements it was
    started on, and the whole snapshot (IDs and texts) must equal the workspace's.
    """
    if workspace is None or not workspace.requirements:
        return None  # nothing to compare with; callers report "no_workspace"
    if not session.context_requirements:
        return "context_unknown"
    snapshot = [(r.id, r.text) for r in session.context_requirements]
    if snapshot != [(r.id, r.text) for r in workspace.requirements]:
        return "context_changed"
    return None


def add_blocker(session: GrillSession, workspace: Workspace | None) -> str | None:
    """Why this result cannot be added to the workspace, or None if it can."""
    if session.step != GrillStep.FINALIZED:
        return "not_finalized"
    draft = session.draft
    if isinstance(draft, RequirementsDraft) or draft is None:
        return "nothing_to_add"
    if workspace is None or not workspace.requirements:
        return "no_workspace"
    if (code := context_blocker(session, workspace)) is not None:
        return code
    if not draft.requirement_id:
        return "requirement_link_required"
    if workspace.requirement(draft.requirement_id) is None:
        return "requirement_not_in_workspace"
    if isinstance(draft, TestCaseDraft):
        if draft.test_type is None or not draft.title or not draft.steps or not draft.expected_result:
            return "incomplete_result"
        if any(_same_test(tc, draft) for tc in workspace.test_cases):
            return "already_added"
    else:
        if draft.severity is None:
            return "severity_required"
        if not draft.summary:
            return "incomplete_result"
        if any(d.origin_key == origin_key(session) for d in workspace.defects):
            return "already_added"
    return None


def add_to_workspace(
    session: GrillSession, workspace: Workspace | None, lang: str = "en"
) -> tuple[Workspace, str]:
    """Return a copy of the workspace with the result added, and the new item's ID."""
    if (code := add_blocker(session, workspace)) is not None:
        raise IntegrationError(code)
    assert workspace is not None
    updated = workspace.model_copy(deep=True)
    if isinstance(session.draft, TestCaseDraft):
        case = test_case_from_session(session, next_test_case_id(updated.test_cases), lang)
        updated.test_cases.append(case)
        return updated, case.id
    report = defect_from_session(session, next_defect_id(updated.defects), lang)
    updated.defects.append(report)
    return updated, report.id


def _same_test(case: TestCase, draft: TestCaseDraft) -> bool:
    return (case.requirement_id, case.title, case.steps, case.expected_result) == (
        draft.requirement_id, draft.title, draft.steps, draft.expected_result
    )


def _unconfirmed_values(draft: AnyDraft, lang: str) -> list[str]:
    """One line per field whose value is an assumption or an unconfirmed AI suggestion."""
    lines = []
    for field in editable_fields(draft):
        source = draft.provenance.get(field)
        if field == "assumptions" or source not in _UNCONFIRMED or field_is_empty(draft, field):
            continue
        value = "; ".join(value_text(draft, field, lang).splitlines())
        lines.append(f"{field_label(field, lang)}: {value} ({t(f'grill.provenance.{source}', lang)})")
    return lines


def open_questions(session: GrillSession, lang: str = "en") -> list[str]:
    """Questions left unanswered, skipped or answered "unknown", as text.

    A question whose field the user filled in later by editing the draft is
    no longer open.
    """
    draft = session.draft
    result = []
    for question in session.unresolved_questions:
        if (
            draft is not None and question.field
            and not field_is_empty(draft, question.field)
            and draft.provenance.get(question.field) != Provenance.UNKNOWN
        ):
            continue
        prompt = render_question(question, lang)[0]
        if prompt not in result:
            result.append(prompt)
    return result


def test_case_from_session(session: GrillSession, case_id: str, lang: str = "en") -> TestCase:
    """A Draft TestCase written by the user. Test data goes into the preconditions."""
    draft = session.draft
    if not isinstance(draft, TestCaseDraft) or draft.test_type is None:
        raise IntegrationError("incomplete_result")
    return TestCase(
        id=case_id,
        requirement_id=draft.requirement_id,
        title=draft.title,
        test_type=draft.test_type,
        preconditions=[
            *draft.preconditions,
            *(t("grill.export.test_data_item", lang, value=item) for item in draft.test_data),
        ],
        steps=list(draft.steps),
        expected_result=draft.expected_result,
        assumptions=[*draft.assumptions, *_unconfirmed_values(draft, lang)],
        clarification_questions=open_questions(session, lang),
        source=Source.USER,
    )


def _context_lines(draft: BugReportDraft, lang: str) -> list[str]:
    """Environment, preconditions, steps and evidence; unknown values are said to be unknown."""
    unknown = t("grill.provenance.unknown", lang)
    lines = []
    for field in ("environment", "app_version", "reproducibility", "priority"):
        value = value_text(draft, field, lang)
        if value or draft.provenance.get(field) == Provenance.UNKNOWN:
            lines.append(f"{field_label(field, lang)}: {value or unknown}")
    for field, numbered in (("preconditions", False), ("steps", True), ("evidence", False)):
        items: list[str] = getattr(draft, field)
        if not items and draft.provenance.get(field) != Provenance.UNKNOWN:
            continue
        lines.append(f"{field_label(field, lang)}:")
        if not items:
            lines.append(f"- {unknown}")
        lines += [f"{n}. {item}" if numbered else f"- {item}" for n, item in enumerate(items, start=1)]
    return lines


def defect_from_session(session: GrillSession, report_id: str, lang: str = "en") -> DefectReport:
    """A DefectReport written by the user, with the product-bug details kept as text."""
    draft = session.draft
    if not isinstance(draft, BugReportDraft) or draft.severity is None:
        raise IntegrationError("severity_required")
    context = _context_lines(draft, lang)
    notes = [*draft.assumptions, *_unconfirmed_values(draft, lang)]
    if notes:
        context += [f"{field_label('assumptions', lang)}:", *(f"- {note}" for note in notes)]
    if questions := open_questions(session, lang):
        context += [f"{t('grill.export.open_questions', lang)}:", *(f"- {q}" for q in questions)]
    context.append(t("grill.export.created_by_grill", lang))
    return DefectReport(
        id=report_id,
        requirement_id=draft.requirement_id,
        title=draft.summary,
        severity=draft.severity,
        description=draft.actual_result,
        expected_behavior=draft.expected_result,
        reproduction_context="\n".join(context),
        source=Source.USER,
        origin_key=origin_key(session),
    )


# ---------------------------------------------------------------------------
# Resolving requirement findings (opt-in)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Resolution:
    """Open workspace findings that one user-confirmed clarification answers."""

    question_id: str
    clarification: str
    requirement_ids: tuple[str, ...]
    finding_keys: tuple[str, ...]


def resolve_blocker(session: GrillSession, workspace: Workspace | None) -> str | None:
    """Why findings cannot be resolved from this session, or None if they can."""
    if session.step != GrillStep.FINALIZED:
        return "not_finalized"
    if not isinstance(session.draft, RequirementsDraft):
        return "nothing_to_add"
    if workspace is None or not workspace.requirements:
        return "no_workspace"
    # Clarifications only apply to the document they were made for.
    for requirement in session.draft.requirements:
        known = workspace.requirement(requirement.id)
        if known is None or known.text != requirement.text:
            return "requirements_not_in_workspace"
    return None


def resolutions(session: GrillSession, workspace: Workspace | None) -> list[Resolution]:
    """Clarifications the user confirmed that answer an open finding in the workspace.

    Assumptions never resolve anything: they are not confirmed.
    """
    if resolve_blocker(session, workspace) is not None:
        return []
    assert isinstance(session.draft, RequirementsDraft) and workspace is not None
    result = []
    for statement in session.draft.statements:
        if statement.provenance != Provenance.USER_CONFIRMED or not statement.origin.startswith(RULE_QUESTION_PREFIX):
            continue
        keys = tuple(
            f.key for f in workspace.findings
            if f.status == ClarificationStatus.NEEDS_CLARIFICATION and rule_question_id(f) == statement.origin
        )
        if keys:
            result.append(Resolution(statement.origin, statement.text, tuple(statement.requirement_ids), keys))
    return result


def resolve_findings(session: GrillSession, workspace: Workspace | None, question_ids: list[str]) -> Workspace:
    """Return a copy of the workspace with the chosen clarifications' findings resolved."""
    if (code := resolve_blocker(session, workspace)) is not None:
        raise IntegrationError(code)
    assert workspace is not None
    available = {r.question_id: r for r in resolutions(session, workspace)}
    if not question_ids or any(qid not in available for qid in question_ids):
        raise IntegrationError("nothing_selected")
    keys = {key for qid in question_ids for key in available[qid].finding_keys}
    updated = workspace.model_copy(deep=True)
    for finding in updated.findings:
        if finding.key in keys:
            finding.status = ClarificationStatus.RESOLVED
    return updated


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _md_items(items: list[str]) -> list[str]:
    return [f"- {escape_markdown(item)}" for item in items]


def result_markdown(session: GrillSession, lang: str = "en") -> str:
    """The confirmed result as Markdown, with origins, assumptions and open items."""
    if session.step != GrillStep.FINALIZED or session.draft is None:
        raise IntegrationError("not_finalized")
    draft = session.draft
    out = [f"# {t(f'grill.artifact.{session.artifact.value}', lang)}", "", f"_{t('grill.export.note', lang)}_", ""]
    origin = t("grill.ui.column_origin", lang)
    if isinstance(draft, RequirementsDraft):
        out += [f"## {field_label('requirements', lang)}", ""]
        out += _md_table(
            [t("column.id", lang), t("column.requirement", lang)], [[r.id, r.text] for r in draft.requirements]
        )
        out += ["", f"## {field_label('statements', lang)}", ""]
        if draft.statements:
            out += _md_table(
                [t("grill.ui.column_clarification", lang), t("grill.ui.column_requirements", lang), origin],
                [
                    [s.text, ", ".join(s.requirement_ids), t(f"grill.provenance.{s.provenance.value}", lang)]
                    for s in draft.statements
                ],
            )
        else:
            out.append(t("grill.ui.no_statements", lang))
    else:
        out += _md_table(
            [t("grill.ui.column_field", lang), t("grill.ui.column_value", lang), origin],
            [[label, value or "—", source] for label, value, source in draft_rows(draft, lang)],
        )
    if draft.assumptions and isinstance(draft, RequirementsDraft):
        out += ["", f"## {field_label('assumptions', lang)}", "", *_md_items(draft.assumptions)]
    if questions := open_questions(session, lang):
        out += ["", f"## {t('grill.export.open_questions', lang)}", "", *_md_items(questions)]
    if session.accepted_unresolved and session.warning_findings:
        out += ["", f"## {t('grill.export.accepted_findings', lang)}", ""]
        out += _md_items([render_finding(f, lang)[0] for f in session.warning_findings])
    return "\n".join(out) + "\n"


def markdown_file_name(session: GrillSession) -> str:
    return f"grill-{session.artifact.value.replace('_', '-')}-{session.id[:8]}.md"
