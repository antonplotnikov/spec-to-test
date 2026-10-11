"""Pydantic data models shared across the app.

Every finding and test case keeps an explicit link to a requirement ID,
so coverage can be computed from real links instead of raw counts.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class Language(StrEnum):
    EN = "en"
    UK = "uk"
    RU = "ru"


class Requirement(BaseModel):
    id: str = Field(min_length=1)
    # Original wording from the source document. Never rewritten.
    text: str = Field(min_length=1)
    language: Language = Language.EN
    source_line: int | None = None
    has_explicit_id: bool = False


class FindingType(StrEnum):
    AMBIGUOUS_WORDING = "ambiguous_wording"
    MISSING_EXPECTED_RESULT = "missing_expected_result"
    MISSING_BOUNDARY = "missing_boundary"
    MISSING_ERROR_HANDLING = "missing_error_handling"
    CONTRADICTION = "contradiction"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Source(StrEnum):
    """Where a finding or test case came from. Shown to the user."""

    RULE = "rule"
    AI = "ai"


class ClarificationStatus(StrEnum):
    NEEDS_CLARIFICATION = "needs_clarification"
    RESOLVED = "resolved"


class Finding(BaseModel):
    requirement_id: str
    type: FindingType
    severity: Severity
    source: Source = Source.RULE
    # Words or phrases in the requirement that triggered the rule.
    matched_terms: list[str] = Field(default_factory=list)
    # Other requirements involved (used for contradictions).
    related_requirement_ids: list[str] = Field(default_factory=list)
    status: ClarificationStatus = ClarificationStatus.NEEDS_CLARIFICATION

    @property
    def key(self) -> str:
        """Stable identity used to link bug reports back to this finding."""
        related = ",".join(sorted(self.related_requirement_ids))
        return f"{self.requirement_id}|{self.type.value}|{related}"


class TestType(StrEnum):
    __test__ = False  # tell pytest this is not a test class

    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    EQUIVALENCE = "equivalence"
    DECISION_TABLE = "decision_table"
    ERROR_HANDLING = "error_handling"


class ReviewStatus(StrEnum):
    """Review workflow for test cases: Draft -> Reviewed -> Approved."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"


class TestCase(BaseModel):
    __test__ = False  # tell pytest this is not a test class

    id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    test_type: TestType
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    # Assumptions are NOT confirmed requirements; they must be reviewed.
    assumptions: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    source: Source = Source.RULE
    review_status: ReviewStatus = ReviewStatus.DRAFT
    reviewer_comment: str = ""


class RequirementStatus(StrEnum):
    CLEAR = "clear"
    NEEDS_CLARIFICATION = "needs_clarification"


class AnalysisResult(BaseModel):
    requirements: list[Requirement]
    findings: list[Finding] = Field(default_factory=list)

    def findings_for(self, requirement_id: str) -> list[Finding]:
        return [f for f in self.findings if f.requirement_id == requirement_id]

    def status_of(self, requirement_id: str) -> RequirementStatus:
        open_findings = [
            f
            for f in self.findings_for(requirement_id)
            if f.status == ClarificationStatus.NEEDS_CLARIFICATION
        ]
        if open_findings:
            return RequirementStatus.NEEDS_CLARIFICATION
        return RequirementStatus.CLEAR


class DefectReport(BaseModel):
    """An editable report about a problem in a requirement (not in the product)."""

    id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    severity: Severity
    description: str = ""
    expected_behavior: str = ""
    reproduction_context: str = ""
    source: Source = Source.RULE
    # Finding.key (or AISuggestion.id) the report was generated from.
    origin_key: str = ""


class AISuggestionType(StrEnum):
    AMBIGUITY = "ambiguity"
    CONTRADICTION = "contradiction"
    MISSING_SCENARIO = "missing_scenario"


class AISuggestion(BaseModel):
    """A suggestion produced by an LLM. Never treated as a confirmed fact."""

    id: str = Field(min_length=1)
    type: AISuggestionType
    requirement_ids: list[str] = Field(min_length=1)
    description: str = Field(min_length=1)
    # Exact text from the requirement the model points at.
    quote: str = ""
    # True only if `quote` was found verbatim in one of the linked requirements.
    quote_verified: bool = False
    question: str = ""
    source: Source = Source.AI


class Workspace(BaseModel):
    """Everything the user works on for one document. Persisted locally."""

    document_hash: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    test_cases: list[TestCase] = Field(default_factory=list)
    defects: list[DefectReport] = Field(default_factory=list)
    ai_suggestions: list[AISuggestion] = Field(default_factory=list)
    ai_model: str = ""

    @property
    def analysis(self) -> AnalysisResult:
        return AnalysisResult(requirements=self.requirements, findings=self.findings)

    def requirement(self, requirement_id: str) -> Requirement | None:
        return next((r for r in self.requirements if r.id == requirement_id), None)

    def tests_for(self, requirement_id: str) -> list[TestCase]:
        return [tc for tc in self.test_cases if tc.requirement_id == requirement_id]

    def defects_for(self, requirement_id: str) -> list[DefectReport]:
        return [d for d in self.defects if d.requirement_id == requirement_id]

    def open_findings_for(self, requirement_id: str) -> list[Finding]:
        return [
            f
            for f in self.findings
            if f.requirement_id == requirement_id
            and f.status == ClarificationStatus.NEEDS_CLARIFICATION
        ]
