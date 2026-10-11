"""Turn requirement findings into editable defect reports.

A report describes a problem in the *requirement* (ambiguity, gap,
contradiction), not a product bug. Every report keeps the requirement ID and
the evidence that produced it, so a reviewer can trace it back.
"""

import re

from spec_to_test.i18n import t
from spec_to_test.models import (
    AISuggestion,
    ClarificationStatus,
    DefectReport,
    Finding,
    FindingType,
    Severity,
    Source,
    Workspace,
)


def next_defect_id(existing: list[DefectReport]) -> str:
    numbers = [int(m.group(1)) for d in existing if (m := re.fullmatch(r"BUG-(\d+)", d.id))]
    return f"BUG-{max(numbers, default=0) + 1:03d}"


def origin_key(finding: Finding) -> str:
    """Both sides of a contradiction share one key, so they produce one report."""
    if finding.type == FindingType.CONTRADICTION:
        ids = sorted([finding.requirement_id, *finding.related_requirement_ids])
        return f"contradiction|{','.join(ids)}"
    return finding.key


def _terms(terms: list[str]) -> str:
    return ", ".join(f'"{term}"' for term in terms) or "—"


def defect_from_finding(
    finding: Finding, workspace: Workspace, report_id: str, lang: str = "en"
) -> DefectReport:
    req = workspace.requirement(finding.requirement_id)
    text = req.text if req else ""
    kind = finding.type.value
    context = [t("bug.context_requirement", lang, req=finding.requirement_id, text=text)]
    if req and req.source_line:
        context.append(t("bug.context_line", lang, line=req.source_line))
    if finding.matched_terms:
        context.append(t("bug.context_terms", lang, terms=_terms(finding.matched_terms)))
    for related_id in finding.related_requirement_ids:
        related = workspace.requirement(related_id)
        context.append(
            t("bug.context_related", lang, req=related_id, text=related.text if related else "—")
        )
    context.append(t("bug.context_detected_rule", lang))

    return DefectReport(
        id=report_id,
        requirement_id=finding.requirement_id,
        title=t("bug.title", lang, issue=t(f"finding.{kind}", lang), req=finding.requirement_id),
        severity=finding.severity,
        description=t(
            f"bug.description.{kind}",
            lang,
            req=finding.requirement_id,
            terms=_terms(finding.matched_terms),
            related=", ".join(finding.related_requirement_ids) or "—",
        ),
        expected_behavior=t(f"bug.expected.{kind}", lang),
        reproduction_context="\n".join(context),
        source=Source.RULE,
        origin_key=origin_key(finding),
    )


def defect_from_suggestion(
    suggestion: AISuggestion, workspace: Workspace, report_id: str, lang: str = "en"
) -> DefectReport:
    req_id = suggestion.requirement_ids[0]
    context = []
    for rid in suggestion.requirement_ids:
        req = workspace.requirement(rid)
        context.append(t("bug.context_requirement", lang, req=rid, text=req.text if req else "—"))
    if suggestion.quote:
        key = "bug.context_quote_verified" if suggestion.quote_verified else "bug.context_quote_unverified"
        context.append(t(key, lang, quote=suggestion.quote))
    context.append(t("bug.context_detected_ai", lang, model=workspace.ai_model or "AI"))
    return DefectReport(
        id=report_id,
        requirement_id=req_id,
        title=t("bug.title", lang, issue=t(f"ai_type.{suggestion.type.value}", lang), req=req_id),
        severity=Severity.MEDIUM,
        description=suggestion.description,
        expected_behavior=suggestion.question or t("bug.expected.ai", lang),
        reproduction_context="\n".join(context),
        source=Source.AI,
        origin_key=f"ai|{suggestion.id}",
    )


def generate_defects(workspace: Workspace, lang: str = "en") -> list[DefectReport]:
    """Create reports for open rule findings that do not have a report yet."""
    known = {d.origin_key for d in workspace.defects}
    created: list[DefectReport] = []
    for finding in workspace.findings:
        if finding.status != ClarificationStatus.NEEDS_CLARIFICATION:
            continue
        key = origin_key(finding)
        if key in known:
            continue
        known.add(key)
        created.append(
            defect_from_finding(finding, workspace, next_defect_id(workspace.defects + created), lang)
        )
    return created
