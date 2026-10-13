"""Final report of a Grill session: what is known, what is assumed, what is open, what to test.

The report keeps four kinds of statements apart and never merges them:
- confirmed decisions: the source requirements, what the author wrote in
  their own draft, and replies the author confirmed;
- assumptions: replies the author accepted without confirming them, and
  values suggested by AI that nobody confirmed;
- unresolved questions: answered "unknown", skipped, or never answered;
- contradictions (`grill.conflicts`): resolved ones with their decision,
  open ones as open. A reply that is contested by an open contradiction, or
  that lost a resolved one, is listed there and not as a decision.

Suggested test cases come from the built-in rule-based generator (always) and,
on request, from an AI model (`grill.ai.suggest_test_cases`). Each one names
the requirement it traces to and its basis (requirement, confirmed reply or
assumption), so a test that rests on an assumption is visible as such.

Nothing here works before the user confirmed the session (step FINALIZED).
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from spec_to_test.exports import _md_table
from spec_to_test.formatting import escape_markdown
from spec_to_test.grill.conflicts import ConflictKind, contested, detect_conflicts
from spec_to_test.grill.drafts import editable_fields, field_is_empty
from spec_to_test.grill.integration import IntegrationError
from spec_to_test.grill.models import (
    AnswerStatus,
    ArtifactType,
    GrillSession,
    GrillStep,
    Provenance,
    RequirementsDraft,
)
from spec_to_test.grill.text import field_label, render_finding, render_question, value_text
from spec_to_test.i18n import t
from spec_to_test.models import Requirement, Source, TestType, Workspace
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.test_generator import generate_test_cases

_CONFIRMED = (Provenance.SOURCE, Provenance.USER_CONFIRMED)
_UNCONFIRMED = (Provenance.ASSUMPTION, Provenance.AI_SUGGESTION)


class Basis(StrEnum):
    """What a suggested test case's expected result rests on."""

    REQUIREMENT = "requirement"
    CONFIRMED = "confirmed"
    ASSUMPTION = "assumption"


class ReportItem(BaseModel):
    text: str
    # Where it came from: a Provenance value, or an open question's status.
    origin: str
    where: str = ""  # field label or the question that produced it
    requirement_ids: list[str] = Field(default_factory=list)


class ClarifiedRequirement(BaseModel):
    id: str
    text: str  # verbatim from the source
    confirmed: list[str] = Field(default_factory=list)
    assumed: list[str] = Field(default_factory=list)
    open: list[str] = Field(default_factory=list)


class SuggestedTestCase(BaseModel):
    title: str
    requirement_ids: list[str]
    test_type: TestType
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str]
    expected_result: str
    basis: Basis
    basis_quote: str = ""
    open_questions: list[str] = Field(default_factory=list)
    origin: Source


class ContradictionItem(BaseModel):
    kind: ConflictKind
    requirement_ids: list[str]
    statements: list[str]  # verbatim
    resolved: bool
    resolution: str = ""  # the author's decision, verbatim ("" while open)


class GrillReport(BaseModel):
    artifact: ArtifactType
    clarified_requirements: list[ClarifiedRequirement]
    confirmed: list[ReportItem]
    assumptions: list[ReportItem]
    unknowns: list[ReportItem]
    suggested_tests: list[SuggestedTestCase]
    accepted_findings: list[str] = Field(default_factory=list)
    contradictions: list[ContradictionItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# What the session knows
# ---------------------------------------------------------------------------

def linked_requirements(session: GrillSession) -> list[Requirement]:
    """Requirements the session is about: all of them for a requirements draft,
    otherwise only the one the draft links to (if it is in the document)."""
    draft = session.draft
    if isinstance(draft, RequirementsDraft):
        return list(draft.requirements)
    requirement_id = getattr(draft, "requirement_id", "").strip()
    return [r for r in session.context_requirements if r.id == requirement_id]


def _field_items(session: GrillSession, lang: str, sources: tuple[Provenance, ...]) -> list[ReportItem]:
    draft = session.draft
    assert draft is not None and not isinstance(draft, RequirementsDraft)
    links = [draft.requirement_id] if draft.requirement_id else []
    excluded = contested(session)[1]
    items = []
    for field in editable_fields(draft):
        if field == "assumptions" or field_is_empty(draft, field) or field in excluded:
            continue
        # A value without a recorded origin was in the author's own input.
        source = draft.provenance.get(field, Provenance.SOURCE)
        if source in sources:
            items.append(ReportItem(
                text=value_text(draft, field, lang), origin=source.value, where=field_label(field, lang),
                requirement_ids=links,
            ))
    return items


def _statement_items(session: GrillSession, lang: str, sources: tuple[Provenance, ...]) -> list[ReportItem]:
    draft = session.draft
    assert isinstance(draft, RequirementsDraft)
    excluded = contested(session)[0]
    items = []
    for statement in draft.statements:
        if statement.provenance in sources and statement.origin not in excluded:
            question = session.question(statement.origin)
            items.append(ReportItem(
                text=statement.text, origin=statement.provenance.value,
                where=render_question(question, lang)[0] if question else "",
                requirement_ids=list(statement.requirement_ids),
            ))
    return items


def confirmed_items(session: GrillSession, lang: str = "en") -> list[ReportItem]:
    if isinstance(session.draft, RequirementsDraft):
        return _statement_items(session, lang, _CONFIRMED)
    return _field_items(session, lang, _CONFIRMED)


def assumption_items(session: GrillSession, lang: str = "en") -> list[ReportItem]:
    draft = session.draft
    assert draft is not None
    if isinstance(draft, RequirementsDraft):
        items = _statement_items(session, lang, _UNCONFIRMED)
    else:
        items = _field_items(session, lang, _UNCONFIRMED)
    items += [ReportItem(text=a, origin=Provenance.ASSUMPTION.value) for a in draft.assumptions]
    return items


def unknown_items(session: GrillSession, lang: str = "en") -> list[ReportItem]:
    """Questions answered "unknown", skipped, or not answered yet.

    A question whose field the user filled in later by editing the draft is no
    longer open (the same rule as the Markdown result and the workspace hand-over).
    """
    draft = session.draft
    items: list[ReportItem] = []
    seen: set[str] = set()
    for question in session.unresolved_questions:
        if (
            draft is not None and question.field
            and not field_is_empty(draft, question.field)
            and draft.provenance.get(question.field) != Provenance.UNKNOWN
        ):
            continue
        prompt = render_question(question, lang)[0]
        if prompt in seen:
            continue
        seen.add(prompt)
        answer = session.answers.get(question.id)
        items.append(ReportItem(
            text=prompt, origin=answer.status.value if answer else "pending",
            where=field_label(question.field, lang), requirement_ids=list(question.requirement_ids),
        ))
    return items


def fact_texts(session: GrillSession) -> dict[Basis, list[str]]:
    """Texts a suggested test case may rest on, by kind (used to check AI quotes)."""
    draft = session.draft
    assert draft is not None
    texts: dict[Basis, list[str]] = {
        Basis.REQUIREMENT: [r.text for r in linked_requirements(session)],
        Basis.CONFIRMED: [],
        Basis.ASSUMPTION: list(draft.assumptions),
    }
    for item in confirmed_items(session):
        texts[Basis.CONFIRMED].append(item.text)
    for item in assumption_items(session):
        texts[Basis.ASSUMPTION].append(item.text)
    excluded = contested(session)[0]
    for answer in session.answers.values():
        if answer.question_id in excluded:
            continue
        if answer.status == AnswerStatus.ANSWERED:
            texts[Basis.CONFIRMED].append(answer.value)
        elif answer.status == AnswerStatus.ASSUMED:
            texts[Basis.ASSUMPTION].append(answer.value)
    return texts


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def rule_based_tests(session: GrillSession, lang: str = "en") -> list[SuggestedTestCase]:
    """Test cases from the built-in generator for the session's requirements (no AI)."""
    requirements = linked_requirements(session)
    if not requirements:
        return []
    scratch = Workspace(requirements=requirements, findings=analyze_requirements(requirements).findings)
    return [
        SuggestedTestCase(
            title=case.title,
            requirement_ids=[case.requirement_id],
            test_type=case.test_type,
            preconditions=list(case.preconditions),
            steps=list(case.steps),
            expected_result=case.expected_result,
            basis=Basis.REQUIREMENT,
            open_questions=list(case.clarification_questions),
            origin=Source.RULE,
        )
        for case in generate_test_cases(scratch, lang)
    ]


def build_report(
    session: GrillSession, lang: str = "en", ai_tests: list[SuggestedTestCase] | None = None
) -> GrillReport:
    if session.step != GrillStep.FINALIZED or session.draft is None:
        raise IntegrationError("not_finalized")
    draft = session.draft
    confirmed = confirmed_items(session, lang)
    assumptions = assumption_items(session, lang)
    unknowns = unknown_items(session, lang)
    clarified = []
    for requirement in linked_requirements(session):
        def linked(items: list[ReportItem], rid: str = requirement.id) -> list[str]:
            return [i.text for i in items if rid in i.requirement_ids]

        statements = isinstance(draft, RequirementsDraft)
        clarified.append(ClarifiedRequirement(
            id=requirement.id,
            text=requirement.text,
            confirmed=linked(confirmed) if statements else [],
            assumed=linked(assumptions) if statements else [],
            open=linked(unknowns),
        ))
    accepted = []
    if session.accepted_unresolved:
        accepted = [render_finding(f, lang)[0] for f in session.warning_findings]
    contradictions = [
        ContradictionItem(
            kind=c.kind, requirement_ids=c.requirement_ids, statements=c.statements,
            resolved=c.resolved, resolution=c.resolution,
        )
        for c in detect_conflicts(session)
    ]
    return GrillReport(
        artifact=session.artifact,
        clarified_requirements=clarified,
        confirmed=confirmed,
        assumptions=assumptions,
        unknowns=unknowns,
        suggested_tests=[*rule_based_tests(session, lang), *(ai_tests or [])],
        accepted_findings=accepted,
        contradictions=contradictions,
    )


def origin_label(origin: str, lang: str = "en") -> str:
    """Label for a ReportItem origin (a provenance or an open question's status)."""
    if origin == "pending":
        return t("grill.ui.pending", lang)
    if origin in {s.value for s in AnswerStatus}:
        return t(f"grill.answer_status.{origin}", lang)
    return t(f"grill.provenance.{origin}", lang)


def case_label(case: SuggestedTestCase, lang: str = "en") -> str:
    """Type · basis · source, e.g. "Negative · Requirement · Rule-based"."""
    return " · ".join([
        t(f"test_type.{case.test_type.value}", lang),
        t(f"grill.report.basis.{case.basis.value}", lang),
        t(f"source.{case.origin.value}", lang),
    ])



def contradiction_status(item: ContradictionItem, lang: str = "en") -> str:
    """The decision, or that the contradiction is still open."""
    if item.resolved:
        return t("grill.report.resolved", lang, decision=item.resolution)
    return t("grill.report.unresolved", lang)


def _md_items(items: list[str]) -> list[str]:
    return [f"- {escape_markdown(item)}" for item in items]


def report_markdown(report: GrillReport, lang: str = "en") -> str:
    out = [
        f"# {t('grill.report.title', lang)}: {t(f'grill.artifact.{report.artifact.value}', lang)}", "",
        f"_{t('grill.report.note', lang)}_", "",
    ]
    if report.clarified_requirements:
        out += [f"## {t('grill.report.clarified', lang)}", ""]
        out += _md_table(
            [t("column.id", lang), t("column.requirement", lang), t("grill.report.col_confirmed", lang),
             t("grill.report.col_assumed", lang), t("grill.report.col_open", lang)],
            [[r.id, r.text, "; ".join(r.confirmed) or "—", "; ".join(r.assumed) or "—", "; ".join(r.open) or "—"]
             for r in report.clarified_requirements],
        )
        out.append("")
    sections = (
        ("grill.report.confirmed", report.confirmed),
        ("grill.report.assumptions", report.assumptions),
        ("grill.report.unknowns", report.unknowns),
    )
    for key, items in sections:
        out += [f"## {t(key, lang)}", ""]
        if items:
            out += _md_table(
                [t("grill.report.col_statement", lang), t("grill.ui.column_origin", lang),
                 t("grill.ui.column_where", lang), t("grill.ui.column_requirements", lang)],
                [[i.text, origin_label(i.origin, lang), i.where or "—", ", ".join(i.requirement_ids) or "—"]
                 for i in items],
            )
        else:
            out.append(t("grill.report.none", lang))
        out.append("")
    out += [f"## {t('grill.report.contradictions', lang)}", ""]
    if report.contradictions:
        out += _md_table(
            [t("grill.report.col_conflicting", lang), t("grill.ui.column_requirements", lang),
             t("grill.report.col_decision", lang)],
            [[" ⟷ ".join(c.statements), ", ".join(c.requirement_ids) or "—", contradiction_status(c, lang)]
             for c in report.contradictions],
        )
    else:
        out.append(t("grill.report.none", lang))
    out.append("")
    if report.accepted_findings:
        out += [f"## {t('grill.export.accepted_findings', lang)}", "", *_md_items(report.accepted_findings), ""]
    out += [f"## {t('grill.report.tests', lang)}", ""]
    if not report.suggested_tests:
        out.append(t("grill.report.no_tests", lang))
    for number, case in enumerate(report.suggested_tests, start=1):
        out += [
            f"### {number}. {escape_markdown(case.title)}", "",
            f"_{escape_markdown(case_label(case, lang))} · {escape_markdown(', '.join(case.requirement_ids))}_", "",
        ]
        if case.preconditions:
            out += [f"**{t('grill.field.preconditions', lang)}**", "", *_md_items(case.preconditions), ""]
        out += [f"**{t('grill.field.steps', lang)}**", ""]
        out += [f"{n}. {escape_markdown(step)}" for n, step in enumerate(case.steps, start=1)]
        out += ["", f"**{t('grill.field.expected_result', lang)}:** {escape_markdown(case.expected_result)}", ""]
        if case.basis_quote:
            out += [f"{t('grill.report.basis_quote', lang)}: “{escape_markdown(case.basis_quote)}”", ""]
        if case.open_questions:
            out += [f"**{t('grill.export.open_questions', lang)}**", "", *_md_items(case.open_questions), ""]
    return "\n".join(out).rstrip() + "\n"
