"""Run the QA task agent when a requirements document changes.

The trigger is a new version of a requirements document: a CI job, a git hook
or a person runs this after the file changed.

    python -m spec_to_test.qa_agent.on_change --document docs/spec.md \\
        --previous old-spec.md --out qa-runs

    SPEC_TO_TEST_STORAGE=local python -m spec_to_test.qa_agent.on_change \\
        --document docs/spec.md --project <project id> --out qa-runs

The document is analyzed the way the Analysis page does it (or, with
--project, its saved copy is opened, with the test cases reviewed in the app).
Change Impact compares it with --previous, or with the project's previous
version of the same title. Then the QA task agent (spec_to_test.qa_agent.tasks)
runs the task, by default a full check with all its tools.

With --ai the AI review (spec_to_test.qa_agent.ai_review) runs as well: the
AI_PROVIDER model reads the document, its test cases and the Change Impact, and
its checked findings are added to the report as one more step. Passing --ai is
the consent to send the document to that provider. When AI is not configured or
the request fails, the report says why and the rule-based result is kept.

Permissions:
- automatic: reading the files and the project, the analysis, the report and
  the journal in --out. Nothing else is written.
- only with --allow-write: a status change the task asks for ("approve TC-003")
  is applied to the project's saved document. It is refused when the analysis
  did not finish, the critic found problems in those test cases or the document
  is not saved in the project. Without the flag it stays pending in the report.

Every run is a line in <out>/journal.jsonl. A run whose inputs (document
content, previous version, task, project, --allow-write) match an earlier
finished run is skipped; --force runs it again. One run per --out folder at a
time (<out>/.run.lock; a lock older than 15 minutes is treated as left over
unless its process still runs on this machine).

The report and the journal compare the problems with the previous finished run
of the same document, project and task in this --out folder (its result.json):
resolved, still open and new (tasks.compare_problems).

Exit code: 0 the analysis finished or was skipped as a repeat, 1 it failed in
part or whole or a permitted change was not applied, 2 a usage or input error
or another run in progress.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from spec_to_test import __version__, storage
from spec_to_test.change_impact import change_impact, compare_requirements, impact_on_tests
from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import t
from spec_to_test.input_parser import MAX_FILE_SIZE_BYTES, InputError, extract_requirements, read_uploaded_file
from spec_to_test.llm.providers import AIError, StructuredProvider, load_provider
from spec_to_test.models import ChangeImpact, Workspace
from spec_to_test.projects import DEFAULT_PROJECT_ID, document_title, now
from spec_to_test.qa_agent.ai_review import add_ai_step, ai_review, failed_step
from spec_to_test.qa_agent.store import new_run_id
from spec_to_test.qa_agent.tasks import (
    MAX_TASK_LENGTH,
    AgentResult,
    Item,
    ProblemComparison,
    apply_action,
    compare_problems,
    next_step_lines,
    reference_lines,
    run_task,
    shown_ids,
)
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.test_generator import generate_test_cases

TRIGGER = "document_changed"
DEFAULT_TASK = "Full check"
JOURNAL_FILE = "journal.jsonl"
LOCK_FILE = ".run.lock"
STALE_LOCK_SECONDS = 15 * 60
# Journals larger than this are not searched for repeats (the run goes ahead).
MAX_JOURNAL_BYTES = 20_000_000

Status = Literal["done", "partial", "unsupported", "error", "skipped", "input_error", "crashed"]
ActionState = Literal["none", "pending_approval", "applied", "unchanged", "refused", "failed"]
# Statuses that make a repeat with the same inputs pointless.
FINISHED: frozenset[str] = frozenset({"done", "unsupported"})


class SourceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RunLocked(Exception):
    """Another run holds the lock of this --out folder."""


@dataclass(frozen=True)
class Request:
    document: Path
    previous: Path | None = None
    project_id: str | None = None
    task: str = DEFAULT_TASK
    out: Path = Path("qa-runs")
    lang: str = "en"
    allow_write: bool = False
    force: bool = False
    ai: bool = False


class JournalEntry(BaseModel):
    run_id: str
    trigger: str = TRIGGER
    started_at: str
    finished_at: str = ""
    version: str = __version__
    document: str
    document_hash: str = ""
    previous_hash: str = ""
    project_id: str = ""
    task: str
    allow_write: bool = False
    # With --ai: the provider and model ("Claude (Anthropic) · claude-opus-5-5"), and why the AI step failed.
    ai: str = ""
    ai_error: str = ""
    key: str = ""
    status: Status = "crashed"
    error: str = ""  # a translation key, an input error code or an exception type; no details
    duplicate_of: str = ""
    problems: int = 0
    unknowns: int = 0
    recommendations: int = 0
    action: ActionState = "none"
    action_reason: str = ""
    action_test_case_ids: list[str] = Field(default_factory=list)
    action_status: str = ""
    changed_test_case_ids: list[str] = Field(default_factory=list)
    # The previous run of the same document, project and task, and its problems now (tasks.compare_problems).
    compared_with: str = ""
    compared_at: str = ""
    # Counted per requirement or test case of a line (tasks.ProblemComparison).
    resolved: int = 0
    still_open: int = 0
    new_problems: int = 0
    # Problems of test cases that cannot be told apart, in the previous run and in this one.
    unmatched_before: int = 0
    unmatched_now: int = 0
    report: str = ""


# ---------------------------------------------------------------------------
# Journal and lock
# ---------------------------------------------------------------------------

class Journal:
    def __init__(self, out: Path) -> None:
        self.path = out / JOURNAL_FILE

    def entries(self) -> list[JournalEntry]:
        """Readable entries, oldest first; damaged lines are left out."""
        try:
            if self.path.stat().st_size > MAX_JOURNAL_BYTES:
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries = []
        for line in lines:
            try:
                entries.append(JournalEntry.model_validate_json(line))
            except ValidationError:
                continue
        return entries

    def finished(self, key: str) -> JournalEntry | None:
        return next((e for e in reversed(self.entries()) if e.key == key and e.status in FINISHED), None)

    def previous_run(self, out: Path, entry: JournalEntry) -> tuple[JournalEntry, AgentResult] | None:
        """The latest run of the same document, project and task that left a readable result."""
        document = os.path.normpath(entry.document)
        for earlier in reversed(self.entries()):
            if (earlier.status not in ("done", "partial") or os.path.normpath(earlier.document) != document
                    or earlier.project_id != entry.project_id or earlier.task != entry.task):
                continue
            try:
                result = (out / "runs" / earlier.run_id / "result.json").read_text(encoding="utf-8")
                return earlier, AgentResult.model_validate_json(result)
            except (OSError, ValueError):
                continue  # removed or damaged: try an older one
        return None

    def append(self, entry: JournalEntry) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")


def _lock_holder_running(path: Path) -> bool:
    """Whether the process named in the lock still runs on this machine (unknown: False)."""
    try:
        pid = int(path.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return False
    if pid <= 0 or os.name != "posix":  # os.kill(pid, 0) would end the process on Windows
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True  # runs under another user
    except OSError:
        return False
    return True


@contextmanager
def run_lock(out: Path) -> Iterator[None]:
    path = out / LOCK_FILE
    owner = f"{os.getpid()} {now()} {new_run_id()}\n"
    fd = -1
    for attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            try:
                stale = time.time() - path.stat().st_mtime > STALE_LOCK_SECONDS and not _lock_holder_running(path)
            except FileNotFoundError:
                stale = True  # released meanwhile
            if attempt or not stale:
                raise RunLocked(str(path)) from None
            path.unlink(missing_ok=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(owner)
        yield
    finally:
        # Remove only our own lock: a run that took over a left-over lock keeps its own.
        try:
            if path.read_text(encoding="utf-8") == owner:
                path.unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# The document and its previous version
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            raise InputError("file_too_large", max_mb=MAX_FILE_SIZE_BYTES // (1024 * 1024))
        return read_uploaded_file(path.name, path.read_bytes())
    except FileNotFoundError:
        raise SourceError("not_found") from None
    except IsADirectoryError:
        raise SourceError("not_a_file") from None
    except OSError:
        raise SourceError("read_failed") from None


def build_workspace(source: str, title: str, lang: str) -> Workspace:
    """A new document's workspace, built as on the Analysis page."""
    result = analyze_requirements(extract_requirements(source))
    workspace = Workspace(
        document_hash=storage.document_hash(source.strip()), title=title, created_at=now(),
        requirements=result.requirements, findings=result.findings,
    )
    workspace.test_cases = generate_test_cases(workspace, lang)
    return workspace


def _impact_against(previous: Workspace, workspace: Workspace) -> ChangeImpact:
    changes = compare_requirements(previous.requirements, workspace.requirements)
    return ChangeImpact(previous_document_hash=previous.document_hash, previous_title=previous.title,
                        changes=changes, test_cases=impact_on_tests(previous, changes))


def load_document(request: Request) -> tuple[Workspace, bool]:
    """(workspace with its Change Impact, whether it is the project's saved copy). Writes nothing."""
    source = _read(request.document)
    title = document_title(source, request.document.name)
    if request.project_id is None:
        workspace = build_workspace(source, title, request.lang)
        if request.previous is not None:
            previous_source = _read(request.previous)
            previous = build_workspace(previous_source, document_title(previous_source, request.previous.name),
                                       request.lang)
            workspace.change_impact = _impact_against(previous, workspace)
        return workspace, False

    project_id = request.project_id
    if not storage.persistence_enabled():
        raise SourceError("storage_disabled")
    if not (project_id.isascii() and project_id.isalnum()):
        raise SourceError("invalid_project")
    if project_id != DEFAULT_PROJECT_ID and storage.load_project(project_id) is None:
        raise SourceError("unknown_project")
    saved = storage.load_workspace(storage.document_hash(source.strip()), project_id)
    if saved is not None:
        return saved, True
    workspace = build_workspace(source, title, request.lang)
    workspace.change_impact = change_impact(
        workspace, storage.list_documents(project_id), lambda h: storage.load_workspace(h, project_id),
    )
    return workspace, False


def run_key(request: Request, workspace: Workspace, ai: str = "") -> str:
    """Same key = same inputs: document content (incl. reviews), previous version, task, permissions, AI model."""
    content = workspace.model_dump(mode="json", exclude={"created_at"})
    if content.get("change_impact"):
        content["change_impact"].pop("previous_created_at", None)
    data = {
        "version": __version__, "task": request.task.strip(), "project": request.project_id or "",
        "allow_write": request.allow_write, "lang": request.lang, "workspace": content,
    }
    if ai:
        data["ai"] = ai
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# The proposed change (the only write outside --out)
# ---------------------------------------------------------------------------

def handle_action(request: Request, result: AgentResult, saved: bool) -> tuple[ActionState, str, list[str]]:
    """(state, reason, changed test case IDs). Applies the change only when every condition holds."""
    action = result.action
    if action is None:
        return "none", "", []
    if not request.allow_write:
        return "pending_approval", "", []
    if result.status != "done":
        return "refused", "analysis_incomplete", []
    if not saved or request.project_id is None:
        return "refused", "not_saved", []
    critic = next((s for s in result.steps if s.tool == "critic"), None)
    if critic is not None and any(item.mentions & set(action.test_case_ids) for item in critic.problems):
        return "refused", "critic_problems", []
    # Reload right before the change so edits made in the app since the analysis are kept.
    current = storage.load_workspace(result.document_hash, request.project_id)
    if current is None:
        return "refused", "not_saved", []
    try:
        changed = apply_action(current, action)
    except ValueError:
        return "refused", "missing_test_cases", []
    if not changed:
        return "unchanged", "", []
    try:
        storage.save_workspace(current, request.project_id, remember=False)
    except (OSError, ValueError) as error:
        return "failed", type(error).__name__, []
    return "applied", "", changed


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _text(lang: str, item: Item) -> str:
    params: dict[str, object] = dict(item.params)
    if "ids" in params:
        params["ids"] = shown_ids(lang, item, item.params["ids"])
    if item.terms:
        params["names"] = ", ".join(t(term, lang) for term in item.terms)
    try:
        return t(item.key, lang, **params)
    except (KeyError, IndexError, ValueError):
        return t(item.key, lang)


def _line(lang: str, item: Item) -> str:
    ids = shown_ids(lang, item, ", ".join(item.ids))
    head = " · ".join(part for part in (ids, t(item.topic, lang) if item.topic else "") if part)
    text = escape_markdown(_text(lang, item))
    return f"- **{escape_markdown(head)}**: {text}" if head else f"- {text}"


_ACTION_NOTES = {
    "pending_approval": "Pending approval: not applied. Re-run with --project and --allow-write to apply it.",
    "applied": "Applied to the project's saved document: {ids}.",
    "unchanged": "Not changed: these test cases already have this status.",
    "refused": "Not applied ({reason}).",
    "failed": "Not applied: saving failed ({reason}).",
}


def _previous_lines(lang: str, entry: JournalEntry, comparison: ProblemComparison, items: list[Item]) -> list[str]:
    """Lines of the previous run, each with the title its test cases had then."""
    lines = []
    for item in items:
        lines.append(_line(lang, item))
        for i in item.ids:
            if (title := comparison.previous_titles.get(i)) is not None:
                text = t("qatask.compare.previous_test_case", lang, id=i, run=entry.compared_with, text=title)
                lines.append(f"  - {escape_markdown(text)}")
    return lines


def _comparison_lines(lang: str, entry: JournalEntry, comparison: ProblemComparison) -> list[str]:
    lines = [f"## {t('qatask.compare.heading', lang)}", "",
             escape_markdown(t("qatask.compare.summary", lang, run=entry.compared_with, at=entry.compared_at,
                               resolved=comparison.resolved_count, open=comparison.still_open,
                               new=comparison.new_count))]
    if comparison.resolved:
        lines += ["", f"### {t('qatask.compare.resolved', lang, count=comparison.resolved_count)}", ""]
        lines += _previous_lines(lang, entry, comparison, comparison.resolved)
    if comparison.new:
        lines += ["", f"### {t('qatask.compare.new', lang, count=comparison.new_count)}", ""]
        lines += [_line(lang, i) for i in comparison.new]
    if comparison.unmatched_before or comparison.unmatched_now:
        heading = t("qatask.compare.unmatched", lang, before=comparison.unmatched_before_count,
                    run=entry.compared_with, now=comparison.unmatched_now_count)
        lines += ["", f"### {heading}", "", f"_{t('qatask.compare.unmatched_why', lang)}_", ""]
        lines += _previous_lines(lang, entry, comparison, comparison.unmatched_before)
        for item in comparison.unmatched_now:
            lines.append(_line(lang, item))
            lines += [f"  - {escape_markdown(t('qatask.compare.current_test_case', lang, id=i, text=title))}"
                      for i in item.ids if (title := comparison.current_titles.get(i)) is not None]
    if comparison.not_compared:
        names = ", ".join(t(f"qatask.tool.{tool}", lang) for tool in comparison.not_compared)
        lines += ["", f"_{t('qatask.compare.not_compared', lang, names=names)}_"]
    return lines


def markdown_report(entry: JournalEntry, workspace: Workspace, result: AgentResult, lang: str,
                    comparison: ProblemComparison | None = None) -> str:
    impact = workspace.change_impact
    previous = (f"{escape_markdown(impact.previous_title)} ({impact.previous_document_hash or 'unknown'})"
                if impact is not None else "none")
    lines = [
        f"# QA analysis: {escape_markdown(workspace.title or entry.document)}",
        "",
        f"- Trigger: requirements document changed (run {entry.run_id}, {entry.started_at})",
        f"- Document: {escape_markdown(entry.document)} ({entry.document_hash})",
        f"- Previous version: {previous}",
        f"- Task: {escape_markdown(entry.task)}",
        *([f"- AI review: {escape_markdown(entry.ai or 'requested, not available')}"] if entry.ai or entry.ai_error
          else []),
        f"- Status: {entry.status}" + (f" ({entry.error})" if entry.error else ""),
        "",
    ]
    if result.status == "error" and not result.steps:
        ids = ", ".join(result.plan.unknown_ids) if result.plan else ""
        return "\n".join([*lines, escape_markdown(t(result.error, lang, max=MAX_TASK_LENGTH, ids=ids)), ""])
    if result.status == "unsupported":
        return "\n".join([*lines, t("qatask.unsupported", lang), ""])

    lines += [f"## {t('qatask.heading.conclusions', lang)}", ""]
    for step in result.steps:
        name = t(f"qatask.tool.{step.tool}", lang)
        if step.status == "error" and step.summary is not None:  # the AI step says why it failed
            lines.append(f"- **{name}**: {escape_markdown(_text(lang, step.summary))}")
        elif step.status == "error":
            lines.append(f"- {t('qatask.step_failed', lang, tool=name, error=step.error)}")
        elif step.summary is not None:
            lines.append(f"- **{name}**: {escape_markdown(_text(lang, step.summary))}")
    if comparison is not None:
        lines += ["", *_comparison_lines(lang, entry, comparison)]
    problems, unknowns, recommendations = result.problems, result.unknowns, result.recommendations
    lines += ["", f"## {t('qatask.heading.problems', lang, count=len(problems))}", ""]
    lines += [line for i in problems
              for line in (_line(lang, i), *reference_lines(lang, i, workspace), *next_step_lines(lang, i))] or [
        t("qatask.no_problems", lang)]
    if unknowns:
        lines += ["", f"## {t('qatask.heading.unknowns', lang, count=len(unknowns))}", ""]
        lines += [line for i in unknowns for line in (_line(lang, i), *reference_lines(lang, i, workspace))]
    if result.approval is not None:
        lines += ["", f"## {t('qatask.heading.approval', lang)}", "", escape_markdown(_text(lang, result.approval))]
    lines += ["", f"## {t('qatask.heading.recommendations', lang)}", ""]
    lines += [_line(lang, i) for i in recommendations] or [t("qatask.no_recommendations", lang)]
    if result.plan is not None and result.plan.action_conflicts:
        lines += ["", escape_markdown(t("qatask.action_conflicts", lang, ids=", ".join(result.plan.action_conflicts)))]
    if result.action is not None:
        describe = t("qatask.action.describe", lang, ids=escape_markdown(", ".join(result.action.test_case_ids)),
                     status=t(f"review.{result.action.status.value}", lang))
        note = _ACTION_NOTES.get(entry.action, "").format(ids=", ".join(entry.changed_test_case_ids),
                                                          reason=entry.action_reason)
        lines += ["", f"## {t('qatask.heading.action', lang)}", "", describe, "", note]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def run_on_change(request: Request) -> JournalEntry:
    """Analyze the changed document once and journal the run.

    Raises RunLocked when another run uses the same --out folder, OSError when
    --out or the journal cannot be written.
    """
    request.out.mkdir(parents=True, exist_ok=True)
    with run_lock(request.out):
        journal = Journal(request.out)
        entry = JournalEntry(
            run_id=new_run_id(), started_at=now(), document=str(request.document),
            project_id=request.project_id or "", task=request.task.strip()[:MAX_TASK_LENGTH],
            allow_write=request.allow_write,
        )
        try:
            _run(request, journal, entry)
        except InputError as error:
            entry.status, entry.error = "input_error", error.code
        except SourceError as error:
            entry.status, entry.error = "input_error", error.code
        except Exception as error:  # noqa: BLE001 - every run ends up in the journal
            entry.status, entry.error = "crashed", type(error).__name__
        entry.finished_at = now()
        journal.append(entry)
    return entry


def _run(request: Request, journal: Journal, entry: JournalEntry) -> None:
    workspace, saved = load_document(request)
    entry.document_hash = workspace.document_hash
    if workspace.change_impact is not None:
        entry.previous_hash = workspace.change_impact.previous_document_hash
    provider: StructuredProvider | None = None
    if request.ai:
        try:
            provider = load_provider()
            entry.ai = provider.label
        except AIError as error:
            entry.ai_error = error.code
    entry.key = run_key(request, workspace, entry.ai or ("unavailable" if request.ai else ""))
    if not request.force and (earlier := journal.finished(entry.key)) is not None:
        entry.status, entry.duplicate_of = "skipped", earlier.run_id
        return

    result = run_task(request.task, workspace)
    if request.ai and result.status in ("done", "partial"):
        step = ai_review(workspace, provider, request.lang) if provider else failed_step(entry.ai_error)
        add_ai_step(result, step)
        entry.ai_error = step.error
    entry.status, entry.error = result.status, result.error
    entry.problems, entry.unknowns = len(result.problems), len(result.unknowns)
    entry.recommendations = len(result.recommendations)
    if result.action is not None:
        entry.action_test_case_ids = list(result.action.test_case_ids)
        entry.action_status = result.action.status.value
    entry.action, entry.action_reason, entry.changed_test_case_ids = handle_action(request, result, saved)
    comparison = None
    if result.status in ("done", "partial") and (last := journal.previous_run(request.out, entry)) is not None:
        last_entry, last_result = last
        comparison = compare_problems(last_result, result)
        entry.compared_with, entry.compared_at = last_entry.run_id, last_entry.started_at
        entry.resolved, entry.still_open = comparison.resolved_count, comparison.still_open
        entry.new_problems = comparison.new_count
        entry.unmatched_before, entry.unmatched_now = comparison.unmatched_before_count, comparison.unmatched_now_count

    run_dir = request.out / "runs" / entry.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(result.model_dump_json(indent=1), encoding="utf-8")
    report = run_dir / "report.md"
    report.write_text(markdown_report(entry, workspace, result, request.lang, comparison), encoding="utf-8")
    entry.report = str(report)


def exit_code(entry: JournalEntry) -> int:
    if entry.status == "input_error":
        return 2
    if entry.status in ("partial", "error", "crashed") or entry.action in ("refused", "failed"):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m spec_to_test.qa_agent.on_change",
        description="Analyze a changed requirements document with the QA task agent.",
    )
    parser.add_argument("--document", required=True, type=Path, help="the new version (.md, .txt or .pdf)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--previous", type=Path, help="the previous version, for Change Impact")
    source.add_argument("--project", help="project id in local storage (SPEC_TO_TEST_STORAGE=local)")
    parser.add_argument("--task", default=DEFAULT_TASK, help=f'the QA task (default: "{DEFAULT_TASK}")')
    parser.add_argument("--out", type=Path, default=Path("qa-runs"), help="folder for the journal and reports")
    parser.add_argument("--lang", choices=("en", "uk", "ru"), default="en", help="report language")
    parser.add_argument("--allow-write", action="store_true",
                        help="allow the status change the task asks for in the project's saved document")
    parser.add_argument("--force", action="store_true", help="run even if the same inputs were analyzed before")
    parser.add_argument("--ai", action="store_true",
                        help="also run the AI review with the AI_PROVIDER model (sends the document to it)")
    args = parser.parse_args(argv)
    if args.allow_write and not args.project:
        print("--allow-write changes a project's saved document: pass --project too.", file=sys.stderr)
        return 2

    request = Request(document=args.document, previous=args.previous, project_id=args.project, task=args.task,
                      out=args.out, lang=args.lang, allow_write=args.allow_write, force=args.force, ai=args.ai)
    try:
        entry = run_on_change(request)
    except RunLocked as error:
        print(f"Another run is in progress (lock: {error}).", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"Cannot write to {args.out}: {type(error).__name__}", file=sys.stderr)
        return 2

    line = f"Run {entry.run_id}: {entry.status}"
    if entry.error:
        line += f" ({entry.error})"
    if entry.status == "skipped":
        line += f"; same inputs as run {entry.duplicate_of} (use --force to run again)"
    elif entry.status not in ("input_error", "crashed"):
        line += f"; problems {entry.problems}, unknowns {entry.unknowns}, recommendations {entry.recommendations}"
        if entry.compared_with:
            line += (f"; since run {entry.compared_with}: resolved {entry.resolved}, still open {entry.still_open},"
                     f" new {entry.new_problems}")
            if entry.unmatched_before or entry.unmatched_now:
                line += f", not comparable {entry.unmatched_before} before / {entry.unmatched_now} now"
    if entry.ai_error:
        line += f"; AI review failed: {t(f'ai.error.{entry.ai_error}', request.lang)}"
    elif entry.ai and entry.status not in ("skipped", "input_error", "crashed"):
        line += f"; AI review: {entry.ai}"
    if entry.action != "none":
        line += f"; change {', '.join(entry.action_test_case_ids)} → {entry.action_status}: {entry.action}"
        line += f" ({entry.action_reason})" if entry.action_reason else ""
    print(line)
    if entry.report:
        print(f"Report: {entry.report}")
    return exit_code(entry)


if __name__ == "__main__":
    sys.exit(main())
