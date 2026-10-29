"""A product bug report built from a free-text description, and what it still lacks.

An empty field means "not stated in the description": it is shown and exported
as "Needs clarification", never filled with a guess. Severity and priority are
preliminary: `*_source` says whether a rule or Claude suggested them (`*_basis`
names the words they are based on) or a person stated them.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from spec_to_test.bug_generator.translations import NEEDS_CLARIFICATION
from spec_to_test.grill.models import Priority
from spec_to_test.llm.claude_code import GenerationUsage
from spec_to_test.models import Severity, Source

MAX_DESCRIPTION_CHARS = 10_000
MAX_FIELD_CHARS = 2_000
MAX_ITEMS = 50
ID_PATTERN = r"^BR-\d{3,}$"

# Fields in the order of the report (and of the editor and the export).
TEXT_FIELDS = ("title", "what", "where", "when", "actual_result", "expected_result")
LIST_FIELDS = ("preconditions", "steps", "environment")


class ProductBugReport(BaseModel):
    # Fields this version does not know are kept on save: a file written by a newer version is not trimmed.
    model_config = ConfigDict(extra="allow")

    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(default="", max_length=MAX_FIELD_CHARS)
    # WWW: what goes wrong, where in the product, when (trigger, frequency, since when).
    what: str = Field(default="", max_length=MAX_FIELD_CHARS)
    where: str = Field(default="", max_length=MAX_FIELD_CHARS)
    when: str = Field(default="", max_length=MAX_FIELD_CHARS)
    preconditions: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    steps: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    actual_result: str = Field(default="", max_length=MAX_FIELD_CHARS)
    expected_result: str = Field(default="", max_length=MAX_FIELD_CHARS)
    # Browser, OS, device, app version, test environment: as written in the description.
    environment: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    severity: Severity | None = None
    severity_source: Source = Source.RULE
    severity_basis: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    priority: Priority | None = None
    priority_source: Source = Source.RULE
    # Rule codes ("follows_severity", "lowered_intermittent", ...) or the reporter's own word.
    priority_basis: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    # The reporter's description, verbatim, and the parts of it no field took.
    description: str = Field(default="", max_length=MAX_DESCRIPTION_CHARS)
    unassigned: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    # RULE / AI: generated and not edited yet; USER: saved from the editor.
    source: Source = Source.RULE
    # What generated the report: "rules" (local) or "claude_code" (Claude through Claude Code).
    generated_by: Literal["rules", "claude_code"] = "rules"
    # Claude Code only: tokens of the generation and the plan's limits before and after it.
    generation_usage: GenerationUsage | None = None
    created_at: str = ""
    updated_at: str = ""


def next_report_id(existing: list[ProductBugReport]) -> str:
    numbers = [int(m.group(1)) for r in existing if (m := re.fullmatch(r"BR-(\d+)", r.id))]
    return f"BR-{max(numbers, default=0) + 1:03d}"


# --- Missing Information --------------------------------------------------------------

_PLATFORM = re.compile(
    r"\b(chrome|chromium|firefox|safari|edge|opera|brave|yandex|яндекс|samsung internet|windows|macos|mac os|os x|"
    r"ios|ipados|android|linux|ubuntu|debian|fedora|chromeos|iphone|ipad|pixel|galaxy|xiaomi|huawei|oneplus|"
    r"macbook|desktop|mobile|tablet|десктоп|мобильн\w*|мобільн\w*|планшет\w*)\b",
    re.I,
)
_VERSION = re.compile(
    r"(\bv\d+(?:\.\d+)+|\b(?:version|ver\.?|build|release|версия|версии|версію|версія|версії|сборка|сборки|"
    r"збірка|збірки|релиз|реліз)\s*[:#]?\s*\d|\b(?:staging|stage|production|prod|preprod|pre-prod|uat|sandbox|"
    r"dev|test|стейдж\w*|стейджинг\w*|продакшн\w*|продакшен\w*|прод|стенд\w*|тестов\w*)\b)",
    re.I,
)
FREQUENCY = re.compile(
    r"(\b(?:every time|each time|always|consistently|sometimes|occasionally|intermittent(?:ly)?|randomly|"
    r"from time to time|once|rarely|often|not always|not reproducible|cannot reproduce)\b|\b\d+\s*(?:out of|of|/|из|з)\s*\d+|"
    r"кажд\w+ раз|всегда|постоянно|иногда|периодически|время от времени|редко|часто|один раз|однажды|не всегда|"
    r"щоразу|кожного разу|завжди|постійно|іноді|інколи|періодично|час від часу|рідко|один раз|одного разу|"
    r"не завжди|не воспроизводится|не відтворюється)",
    re.I,
)
_EVIDENCE = re.compile(
    r"(screenshot|screen recording|video|recording|\blogs?\b|har file|\bhar\b|console|stack ?trace|attach\w*|"
    r"скриншот\w*|скрін\w*|видео|відео|запис\w* (?:экрана|екрана)|\bлог(?:и|ов|ах|ів)?\b|консол\w*|вложени\w*|"
    r"вкладенн\w*)",
    re.I,
)

# Missing Information codes, in report order (translated as bugreport.missing.<code>).
MISSING_CODES = (
    "title", "what", "where", "when", "frequency", "preconditions", "steps", "steps_one", "actual_result",
    "expected_result", "actual_equals_expected", "environment", "env_platform", "env_version", "severity",
    "priority", "evidence",
)


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold().rstrip(".!")


def missing_information(report: ProductBugReport) -> list[str]:
    """What a developer would still have to ask about, as codes (see MISSING_CODES)."""
    missing: list[str] = []
    for field in ("title", "what", "where", "when"):
        if not getattr(report, field).strip():
            missing.append(field)
    if report.when.strip() and not FREQUENCY.search(report.when):
        missing.append("frequency")
    if not report.preconditions:
        missing.append("preconditions")
    if not report.steps:
        missing.append("steps")
    elif len(report.steps) == 1:
        missing.append("steps_one")
    for field in ("actual_result", "expected_result"):
        if not getattr(report, field).strip():
            missing.append(field)
    if report.actual_result.strip() and _norm(report.actual_result) == _norm(report.expected_result):
        missing.append("actual_equals_expected")
    environment = "\n".join(report.environment)
    if not environment.strip():
        missing.append("environment")
    else:
        if not _PLATFORM.search(environment):
            missing.append("env_platform")
        if not _VERSION.search(environment):
            missing.append("env_version")
    if report.severity is None:
        missing.append("severity")
    if report.priority is None:
        missing.append("priority")
    if not _EVIDENCE.search(report.description):
        missing.append("evidence")
    return missing


# --- Editing ----------------------------------------------------------------------------

_MARKERS = {_norm(text) for text in NEEDS_CLARIFICATION.values()} | {"needs clarification", "tbd", "n/a"}
_ITEM_BULLET = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+")


def _clean_text(value: str) -> str:
    value = value.strip()[:MAX_FIELD_CHARS]
    return "" if _norm(value) in _MARKERS else value


def _clean_items(value: str) -> list[str]:
    items = [_ITEM_BULLET.sub("", line).strip()[:MAX_FIELD_CHARS] for line in value.splitlines()]
    return [item for item in items if item and _norm(item) not in _MARKERS][:MAX_ITEMS]


def edited_report(
    report: ProductBugReport,
    text: dict[str, str],
    severity: Severity | None,
    priority: Priority | None,
    updated_at: str,
) -> ProductBugReport:
    """The report with the editor's values: `text` holds every text field and the list
    fields as one item per line. A "Needs clarification" marker typed into a field
    counts as empty, so a marker is never saved as if it were a fact."""
    update: dict[str, object] = {name: _clean_text(text.get(name, "")) for name in TEXT_FIELDS}
    update |= {name: _clean_items(text.get(name, "")) for name in LIST_FIELDS}
    update["unassigned"] = _clean_items(text.get("unassigned", ""))
    if severity != report.severity:
        update |= {"severity": severity, "severity_source": Source.USER, "severity_basis": []}
    if priority != report.priority:
        update |= {"priority": priority, "priority_source": Source.USER, "priority_basis": []}
    changed = any(getattr(report, name) != value for name, value in update.items())
    if changed:
        update |= {"source": Source.USER, "updated_at": updated_at}
    return ProductBugReport.model_validate({**report.model_dump(), **update})
