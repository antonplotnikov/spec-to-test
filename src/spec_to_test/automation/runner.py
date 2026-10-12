"""Run a generated test with Playwright in the sandbox and collect the evidence.

The job folder looks like this after a run:

    playwright.config.ts   sandbox settings (egress pinning, trace, screenshots)
    tests/<tc>.spec.ts     the generated test
    report/results.json    Playwright JSON report (secrets masked)
    test-results/...       screenshots and trace.zip per test (secrets masked)
    run.log                console output of the run (secrets masked)
"""

import shutil
import subprocess
import threading
import time
from pathlib import Path

from spec_to_test.automation.config import AutomationConfig
from spec_to_test.automation.models import Artifact, RunResult
from spec_to_test.automation.results import parse_report
from spec_to_test.automation.sandbox import kill_tree, limited_command, node_command, private_dir, sandbox_env
from spec_to_test.automation.security import Redactor

MAX_JOB_BYTES = 300 * 1024 * 1024
LOG_TAIL_CHARS = 3000


class RunCancelled(Exception):
    pass


def link_toolchain(job_dir: Path, config: AutomationConfig) -> None:
    """Make `@playwright/test` importable from the job folder (Node resolves upwards)."""
    link = job_dir / "node_modules"
    if not link.exists():
        link.symlink_to(config.runner_dir / "node_modules", target_is_directory=True)


class PlaywrightRunner:
    """Runs `playwright test` for one job folder. Blocking; call from a worker thread."""

    def __init__(self, config: AutomationConfig) -> None:
        self.config = config

    def run(self, job_dir: Path, secrets: dict[str, str], redact: Redactor, cancel: threading.Event) -> tuple[RunResult, list[Artifact]]:
        link_toolchain(job_dir, self.config)
        for stale in ("report", "test-results"):
            _remove_tree(job_dir / stale)
        command = node_command(self.config, self.config.playwright_cli, "test", "--config", "playwright.config.ts")
        sandbox = private_dir("stt-run-")
        env = sandbox_env(sandbox, secrets)
        log_path = job_dir / "run.log"
        started = time.monotonic()
        timed_out = False
        with log_path.open("wb") as log:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                limited_command(command, cpu_seconds=self.config.run_timeout * 4),
                cwd=job_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                while process.poll() is None:
                    if cancel.is_set():
                        kill_tree(process)
                        raise RunCancelled
                    if time.monotonic() - started > self.config.run_timeout:
                        timed_out = True
                        kill_tree(process)
                        break
                    time.sleep(0.25)
            finally:
                kill_tree(process)
                _remove_tree(sandbox)

        redact.redact_file(log_path)
        report = job_dir / "report" / "results.json"
        redact.redact_file(report)
        result, artifacts = parse_report(report, job_dir, redact)
        for artifact in artifacts:
            if artifact.kind == "trace":
                redact.redact_zip(job_dir / artifact.path)
        result.exit_code = process.returncode
        result.timed_out = timed_out
        result.passed = result.passed and process.returncode == 0 and not timed_out
        try:
            result.log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-LOG_TAIL_CHARS:]
        except OSError:
            result.log_tail = ""
        artifacts = [*artifacts, Artifact(kind="log", path="run.log")]
        if report.is_file():
            artifacts.append(Artifact(kind="report", path="report/results.json"))
        return result, _sized(job_dir, artifacts)


def _sized(job_dir: Path, artifacts: list[Artifact]) -> list[Artifact]:
    """Fill in sizes; drop traces when the job folder grows beyond its limit."""
    kept: list[Artifact] = []
    for artifact in artifacts:
        path = job_dir / artifact.path
        if path.is_file():
            kept.append(artifact.model_copy(update={"size": path.stat().st_size}))
    if sum(a.size for a in kept) > MAX_JOB_BYTES:
        for artifact in kept:
            if artifact.kind == "trace":
                (job_dir / artifact.path).unlink(missing_ok=True)
        kept = [a for a in kept if a.kind != "trace"]
    return kept


def _remove_tree(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path, ignore_errors=True)
