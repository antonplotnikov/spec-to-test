"""What the Grill page shows beside the interview, derived from the session only.

Nothing here is stored or guessed: requirements, rule findings, quality scores
and contradictions all come from the session (and the analyzed workspace when
the session runs on it), through the existing rule engine and quality score.
Assumptions stay assumptions: they are counted and listed apart from
confirmed answers everywhere.
"""

from dataclasses import dataclass, field

from spec_to_test.grill.conflicts import (
    CONFLICT_PREFIX,
    FOLLOWUP_PREFIX,
    Conflict,
    detect_conflicts,
    question_states,
)
from spec_to_test.grill.models import (
    ClarificationState,
    GrillSession,
    Question,
    RequirementsDraft,
)
from spec_to_test.grill.rules import RULE_QUESTION_PREFIX, requirement_findings
from spec_to_test.models import ClarificationStatus, Finding, FindingType, Requirement, Source, Workspace

# Finding types grouped the way a reviewer reads them.
AMBIGUITY_TYPES = frozenset({FindingType.AMBIGUOUS_WORDING})
MISSING_TYPES = frozenset({
    FindingType.MISSING_EXPECTED_RESULT, FindingType.MISSING_BOUNDARY, FindingType.MISSING_ERROR_HANDLING,
})
CONTRADICTION_TYPES = frozenset({FindingType.CONTRADICTION})


def session_requirements(session: GrillSession) -> list[Requirement]:
    """The requirements the interview is about (the draft's, else the loaded document's)."""
    if isinstance(session.draft, RequirementsDraft):
        return list(session.draft.requirements)
    return list(session.context_requirements)


def scope_findings(session: GrillSession, workspace: Workspace | None) -> list[Finding]:
    """Rule findings for the session's requirements.

    When every requirement is the analyzed document's own (same ID and text),
    the workspace's findings are used, so findings resolved there stay resolved.
    Otherwise the rule engine runs on the session's requirements.
    """
    requirements = session_requirements(session)
    if not requirements:
        return []
    ids = {r.id for r in requirements}
    if workspace is not None:
        known = {r.id: r.text for r in workspace.requirements}
        if all(known.get(r.id) == r.text for r in requirements):
            return [f for f in workspace.findings if f.requirement_id in ids]
    return [finding for _, finding in requirement_findings(requirements)]


def open_findings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.status == ClarificationStatus.NEEDS_CLARIFICATION]


@dataclass
class FindingGroups:
    ambiguities: list[Finding] = field(default_factory=list)
    missing: list[Finding] = field(default_factory=list)
    contradictions: list[Finding] = field(default_factory=list)


def group_findings(findings: list[Finding]) -> FindingGroups:
    """Open findings by kind; a contradiction reported on both sides is listed once."""
    groups = FindingGroups()
    seen_pairs: set[tuple[str, ...]] = set()
    for finding in open_findings(findings):
        if finding.type in AMBIGUITY_TYPES:
            groups.ambiguities.append(finding)
        elif finding.type in MISSING_TYPES:
            groups.missing.append(finding)
        elif finding.type in CONTRADICTION_TYPES:
            pair = tuple(sorted({finding.requirement_id, *finding.related_requirement_ids}))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                groups.contradictions.append(finding)
    return groups


def question_category(question: Question) -> str:
    """A short category for the question card (a translation key suffix).

    Rule questions carry their finding type in the ID (`rule.<type>.<REQ>`);
    follow-ups and conflict questions have their own prefixes.
    """
    qid = question.id
    if qid.startswith(CONFLICT_PREFIX) or qid.startswith(f"{RULE_QUESTION_PREFIX}contradiction."):
        return "contradiction"
    if qid.startswith(f"{FOLLOWUP_PREFIX}vague.") or qid.endswith(".vague"):
        return "clarity"
    if qid.startswith(f"{FOLLOWUP_PREFIX}limit."):
        return "boundary"
    if qid.startswith(RULE_QUESTION_PREFIX):
        kind = qid[len(RULE_QUESTION_PREFIX):].split(".", 1)[0]
        if kind in {t.value for t in FindingType}:
            return kind
    if question.origin == Source.AI:
        return "ai"
    return "field" if question.field else "clarification"


def focus_requirement(session: GrillSession, question: Question | None) -> Requirement | None:
    """The requirement the current step is about: the question's first linked one,
    else the one the draft links to."""
    by_id = {r.id: r for r in session_requirements(session)}
    if question is not None:
        for rid in question.requirement_ids:
            if rid in by_id:
                return by_id[rid]
    linked = getattr(session.draft, "requirement_id", "") or ""
    return by_id.get(linked.strip())


def related_requirements(
    session: GrillSession, requirement_id: str, findings: list[Finding], conflicts: list[Conflict] | None = None
) -> list[Requirement]:
    """Other requirements tied to `requirement_id` by a finding, a question or a contradiction."""
    by_id = {r.id: r for r in session_requirements(session)}
    related: list[str] = []

    def add(ids: list[str]) -> None:
        for rid in ids:
            if rid != requirement_id and rid in by_id and rid not in related:
                related.append(rid)

    for finding in findings:
        if finding.requirement_id == requirement_id:
            add(finding.related_requirement_ids)
        elif requirement_id in finding.related_requirement_ids:
            add([finding.requirement_id])
    for question in session.questions:
        if requirement_id in question.requirement_ids:
            add(question.requirement_ids)
    for conflict in conflicts if conflicts is not None else detect_conflicts(session):
        if requirement_id in conflict.requirement_ids:
            add(conflict.requirement_ids)
    return [by_id[rid] for rid in related]


@dataclass
class InterviewCounts:
    confirmed: int = 0
    assumptions: int = 0
    unknowns: int = 0
    open: int = 0
    conflicts: int = 0  # unresolved contradictions (source, answer vs requirement, answer vs answer)


def interview_counts(session: GrillSession, conflicts: list[Conflict] | None = None) -> InterviewCounts:
    states = question_states(session)
    conflicts = conflicts if conflicts is not None else detect_conflicts(session)
    values = list(states.values())
    return InterviewCounts(
        confirmed=values.count(ClarificationState.CONFIRMED),
        assumptions=values.count(ClarificationState.ASSUMPTION),
        unknowns=values.count(ClarificationState.UNKNOWN),
        open=values.count(ClarificationState.OPEN),
        conflicts=sum(not c.resolved for c in conflicts),
    )


def assumed_answers(session: GrillSession) -> list[tuple[Question, str]]:
    """(question, assumed value) for every answer accepted as an assumption, not confirmed."""
    states = question_states(session)
    return [
        (q, session.answers[q.id].value)
        for q in session.questions
        if states[q.id] == ClarificationState.ASSUMPTION
    ]


def unresolved(session: GrillSession) -> list[Question]:
    """Open or unknown questions, highest priority first."""
    states = question_states(session)
    waiting = (ClarificationState.OPEN, ClarificationState.UNKNOWN, ClarificationState.CONFLICT)
    return sorted((q for q in session.questions if states[q.id] in waiting), key=lambda q: q.rank)
