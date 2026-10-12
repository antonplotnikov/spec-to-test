"""Read Playwright's JSON report into a RunResult plus the files it points to."""

import json
import re
from pathlib import Path
from typing import Any

from spec_to_test.automation.models import Artifact, RunResult, TestOutcome
from spec_to_test.automation.security import Redactor

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
MAX_ERROR_CHARS = 4000


def _clean(text: str, redact: Redactor) -> str:
    text = redact(ANSI.sub("", text or "")).strip()
    return text if len(text) <= MAX_ERROR_CHARS else text[: MAX_ERROR_CHARS - 1] + "…"


def _specs(suite: dict[str, Any]) -> list[dict[str, Any]]:
    found = list(suite.get("specs", []))
    for child in suite.get("suites", []):
        found += _specs(child)
    return found


def _relative(path: str, job_dir: Path) -> str | None:
    try:
        resolved = Path(path).resolve()
        return str(resolved.relative_to(job_dir.resolve()))
    except (ValueError, OSError):
        return None  # never expose files outside the job folder


def parse_report(report_path: Path, job_dir: Path, redact: Redactor) -> tuple[RunResult, list[Artifact]]:
    """Parse report/results.json. A missing or broken report is a failed run."""
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return RunResult(passed=False, errors=["Playwright did not write a test report."]), []

    outcomes: list[TestOutcome] = []
    artifacts: list[Artifact] = []
    for suite in data.get("suites", []):
        for spec in _specs(suite):
            for test in spec.get("tests", []):
                results = test.get("results") or [{}]
                last = results[-1]
                errors = last.get("errors") or ([last["error"]] if last.get("error") else [])
                message = "\n\n".join(_clean(e.get("message") or e.get("stack") or "", redact) for e in errors)
                location = ""
                if errors and isinstance(errors[0].get("location"), dict):
                    loc = errors[0]["location"]
                    location = f"{Path(str(loc.get('file', ''))).name}:{loc.get('line', '')}"
                outcomes.append(
                    TestOutcome(
                        title=_clean(spec.get("title", ""), redact),
                        status=str(last.get("status", "unknown")),
                        duration_ms=int(last.get("duration") or 0),
                        error=message,
                        error_location=location,
                    )
                )
                for attachment in last.get("attachments", []):
                    path = attachment.get("path")
                    relative = _relative(path, job_dir) if path else None
                    if relative is None:
                        continue
                    content_type = str(attachment.get("contentType", ""))
                    if content_type.startswith("image/"):
                        artifacts.append(Artifact(kind="screenshot", path=relative))
                    elif attachment.get("name") == "trace":
                        artifacts.append(Artifact(kind="trace", path=relative))
    report_errors = [_clean(e.get("message") or e.get("stack") or "", redact) for e in data.get("errors", [])]
    stats = data.get("stats", {})
    passed = bool(outcomes) and all(o.status == "passed" for o in outcomes) and not report_errors
    return (
        RunResult(
            passed=passed,
            tests=outcomes,
            duration_ms=int(stats.get("duration") or 0),
            errors=[e for e in report_errors if e],
        ),
        artifacts,
    )
