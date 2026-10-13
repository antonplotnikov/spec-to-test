"""Typed models of Autonomous QA: what discovery saw, the requirements drafted from it,
the test cases generated for them, and the session that ties them together.

Traceability runs through IDs only:

    Evidence (EV-…) → DraftRequirement (WEB-…) → AutoCase (AC-…)
        → workspace TestCase (TC-…) and plan case (QA-…) → CaseResult → BugReport

Everything discovery stores is page content, which is untrusted: it is kept as
plain, length-limited text and never interpreted as instructions or code.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from spec_to_test.models import TestType
from spec_to_test.qa_agent.models import PlanStep

SESSION_SCHEMA_VERSION = 1
MAX_SNIPPET = 300
MAX_DESCRIPTION = 1000
MAX_ANSWER = 500


class EvidenceKind(StrEnum):
    PAGE = "page"  # a page opened, with its HTTP status and title
    HEADING = "heading"
    NAVIGATION = "navigation"  # links inside <nav>
    LINK = "link"
    FORM = "form"
    FIELD = "field"
    BUTTON = "button"
    REDIRECT = "redirect"  # a redirect inside the allowed hosts
    BLOCKED = "blocked"  # a navigation or request the egress policy stopped


class Evidence(BaseModel):
    """One fact discovery observed, quoted from the page (never paraphrased)."""

    id: str = Field(pattern=r"^EV-\d{3,}$")
    kind: EvidenceKind
    url: str = Field(max_length=2048)
    text: str = Field(default="", max_length=MAX_SNIPPET)
    # Where on the page: a locator in the step language when one is known.
    locator: str = Field(default="", max_length=MAX_SNIPPET)
    detail: dict[str, str] = Field(default_factory=dict)


class FieldInfo(BaseModel):
    tag: str = "input"  # input | textarea | select
    type: str = ""
    name: str = ""
    label: str = ""
    placeholder: str = ""
    required: bool = False
    maxlength: int | None = None
    minlength: int | None = None
    options: list[str] = Field(default_factory=list)
    # A locator that finds exactly this field ("" when none was found).
    locator: str = ""
    evidence_id: str = ""

    @property
    def display(self) -> str:
        return self.label or self.placeholder or self.name or self.type or self.tag


class FormKind(StrEnum):
    LOGIN = "login"  # one password field
    SEARCH = "search"
    ACCOUNT = "account"  # several password fields: registration, password change
    GENERIC = "generic"


class FormInfo(BaseModel):
    id: str = Field(pattern=r"^F-\d{3,}$")
    page_url: str
    name: str = ""
    action: str = ""
    method: str = "get"
    kind: FormKind = FormKind.GENERIC
    fields: list[FieldInfo] = Field(default_factory=list)
    submit_label: str = ""
    submit_locator: str = ""
    # A destructive or consequential word in the submit button ("delete", "pay"): never submitted.
    destructive_term: str = ""
    evidence_id: str = ""

    @property
    def display(self) -> str:
        return self.name or self.submit_label or self.id


class LinkInfo(BaseModel):
    text: str = ""
    url: str
    in_nav: bool = False
    # Why discovery did not open it: "" (opened or queued), destructive, external, limit, depth, scheme.
    skipped: str = ""


class PageInfo(BaseModel):
    url: str  # as requested
    final_url: str = ""
    path: str = "/"
    depth: int = 0
    status: int = 0
    title: str = ""
    headings: list[str] = Field(default_factory=list)  # h1 first
    h1: str = ""
    links: list[LinkInfo] = Field(default_factory=list)
    form_ids: list[str] = Field(default_factory=list)
    buttons: list[str] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    blocked_requests: list[str] = Field(default_factory=list)
    redirected_from: str = ""
    # "" when the page was read; otherwise a qaauto.page_error.<code> suffix.
    error: str = ""
    linked_from: str = ""
    link_text: str = ""
    has_password: bool = False
    evidence_id: str = ""


class Basis(StrEnum):
    OBSERVED = "observed"  # directly supported by evidence
    INFERRED = "inferred"  # plausible, needs confirmation
    UNKNOWN = "unknown"  # cannot be established from the evidence


class Decision(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ReqOrigin(StrEnum):
    RULE = "rule"  # drafted by the rules in qa_agent.inference
    AI = "ai"  # proposed by the optional LLM, checked against the evidence
    USER = "user"


class DraftRequirement(BaseModel):
    id: str = Field(pattern=r"^WEB-\d{3,}$")
    # What the rule matched (template + subject); keeps IDs stable when drafting is repeated.
    key: str = Field(min_length=1, max_length=400)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION)
    basis: Basis
    confidence: int = Field(ge=0, le=100)
    url: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    # The reviewer's answer to the questions (for example the exact message the page should show).
    answer: str = Field(default="", max_length=MAX_ANSWER)
    decision: Decision = Decision.PROPOSED
    origin: ReqOrigin = ReqOrigin.RULE
    # Which test generator applies (qa_agent.autoplan); "" = none (reviewed and traced, not executed).
    template: str = ""
    params: dict[str, str] = Field(default_factory=dict)
    original_description: str = ""
    decided_at: str = ""

    @property
    def edited(self) -> bool:
        return bool(self.original_description) and self.description != self.original_description

    @property
    def confirmed(self) -> bool:
        """Observed, or the reviewer stated the expected behavior (answer or edit)."""
        return self.basis == Basis.OBSERVED or bool(self.answer.strip()) or self.edited


class AutoCase(BaseModel):
    id: str = Field(pattern=r"^AC-\d{3,}$")
    key: str = Field(min_length=1, max_length=400)
    requirement_id: str
    title: str = Field(min_length=1, max_length=300)
    test_type: TestType = TestType.POSITIVE
    steps: list[PlanStep] = Field(default_factory=list)
    expected_result: str = Field(default="", max_length=2000)
    risk: str = ""
    approved: bool = False
    # No longer generated (requirement rejected, answer removed) but kept for its links.
    retired: bool = False
    # Links into the workspace and the QA plan once the plan is approved.
    test_case_id: str = ""
    plan_case_id: str = ""


class DiscoveryState(StrEnum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    INTERRUPTED = "interrupted"  # stopped before the queue was empty (time, crash, restart)
    COMPLETED = "completed"
    FAILED = "failed"


class QueueItem(BaseModel):
    url: str
    depth: int = 0
    linked_from: str = ""
    link_text: str = ""


class AutoSession(BaseModel):
    schema_version: int = SESSION_SCHEMA_VERSION
    id: str = Field(pattern=r"^[0-9a-f]{16}$")
    target_url: str
    lang: str = "en"
    created_at: str = ""
    updated_at: str = ""
    # The person confirmed they may test this host (asked again before every run).
    authorized: bool = False
    state: DiscoveryState = DiscoveryState.NOT_STARTED
    error: str = ""
    browser: str = ""
    limits: dict[str, int] = Field(default_factory=dict)
    pages: list[PageInfo] = Field(default_factory=list)
    forms: list[FormInfo] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    queue: list[QueueItem] = Field(default_factory=list)
    requirements: list[DraftRequirement] = Field(default_factory=list)
    cases: list[AutoCase] = Field(default_factory=list)
    ai_model: str = ""
    # The workspace document the approved requirements were sent to, and the runs made.
    document_hash: str = ""
    run_ids: list[str] = Field(default_factory=list)

    def requirement(self, requirement_id: str) -> DraftRequirement | None:
        return next((r for r in self.requirements if r.id == requirement_id), None)

    def evidence_item(self, evidence_id: str) -> Evidence | None:
        return next((e for e in self.evidence if e.id == evidence_id), None)

    def form(self, form_id: str) -> FormInfo | None:
        return next((f for f in self.forms if f.id == form_id), None)

    def case(self, case_id: str) -> AutoCase | None:
        return next((c for c in self.cases if c.id == case_id), None)

    def page(self, url: str) -> PageInfo | None:
        return next((p for p in self.pages if p.url == url), None)
