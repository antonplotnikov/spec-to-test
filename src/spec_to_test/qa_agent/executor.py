"""Runs approved plan cases in a real browser (Python Playwright, Chromium, headless).

Deterministic: each step is one fixed Playwright call chosen by its action;
plan text is never evaluated. Results:

- PASSED   every step and check succeeded;
- FAILED   a check did not hold, a step could not be performed (element not
           found, timeout) or a page answered with a server error (5xx);
- BLOCKED  safety stopped the case: a navigation or redirect leaving the
           allowed hosts, a destructive action, a missing secret, or the
           browser could not start / the run ran out of time;
- NOT RUN  the case was not approved, changed after approval, has no steps
           or checks, or the run limit was reached.

Egress: the browser resolves only the vetted hosts (pinned to their checked
address), sends every other connection, loopback included, to a proxy that
does not exist, and aborts requests to other hosts before they leave. Every
navigation of the main frame, redirects included, is checked against the
policy, so a redirect to an internal address blocks the case.

Each case gets a fresh browser context (no cookies shared between cases),
a screenshot at its end, and its console errors. Secrets are typed from the
environment, masked in screenshots and redacted from every stored text.
"""

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec_to_test.automation.security import (
    BLOCKING_PROXY,
    EgressPolicy,
    UrlRejected,
    check_navigation,
    destructive_term,
)
from spec_to_test.qa_agent.models import (
    CaseResult,
    PlanCase,
    PlanStep,
    QARun,
    RunState,
    RunStatus,
    StepAction,
    StepResult,
)
from spec_to_test.qa_agent.safety import QASettings, preflight
from spec_to_test.qa_agent.steps import EMPTY, describe_locator, parse_locator, secret_name, shown_value

MAX_ERROR = 1500
MAX_RECEIVED = 600
MAX_CONSOLE = 20
ANSI = re.compile(r"\x1b\[[0-9;]*m")
SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")
INTERNAL_SCHEMES = ("about:", "data:", "blob:", "chrome-error:")
# Stored instead of a file name when the page showed a secret value.
SCREENSHOT_WITHHELD = "withheld:secret-visible"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class _Blocked(Exception):
    def __init__(self, reason: str, **params: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.params = params


class _Failed(Exception):
    """A step failed for a reason that is not a Playwright error (e.g. HTTP 500)."""

    def __init__(self, reason: str, message: str, **params: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.params = params


def clean_error(text: str, redact: Callable[[str], str]) -> str:
    text = ANSI.sub("", text or "").strip()
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return redact("\n".join(lines[:20]))[:MAX_ERROR]


def step_label(step: PlanStep) -> str:
    """Language-neutral one-line description, used in results and bug reports."""
    target = describe_locator(step.target) if step.target else ""
    value = shown_value(step.value)
    if step.action == StepAction.FILL and value == EMPTY:
        return f"Clear {target}"
    return {
        StepAction.GOTO: f"Open {value}",
        StepAction.FILL: f"Fill {target} with \"{value}\"",
        StepAction.CLICK: f"Click {target}",
        StepAction.SELECT: f"Select \"{value}\" in {target}",
        StepAction.CHECK: f"Check {target}",
        StepAction.UNCHECK: f"Uncheck {target}",
        StepAction.PRESS: f"Press {value}" + (f" in {target}" if target else ""),
        StepAction.WAIT_FOR: f"Wait for {target}",
        StepAction.EXPECT_VISIBLE: f"Verify {target} is visible",
        StepAction.EXPECT_HIDDEN: f"Verify {target} is not visible",
        StepAction.EXPECT_TEXT: f"Verify {target or 'the page'} shows \"{value}\"",
        StepAction.EXPECT_NO_TEXT: f"Verify {target or 'the page'} does not show \"{value}\"",
        StepAction.EXPECT_URL: f"Verify the URL is {value}",
        StepAction.EXPECT_TITLE: f"Verify the page title contains \"{value}\"",
        StepAction.EXPECT_VALUE: f"Verify {target} has the value \"{value}\"",
    }[step.action]


def url_matches(current: str, expected: str) -> bool:
    """Exact URL, or (for "/path") the same path, with or without the query."""
    if current == expected:
        return True
    if not expected.startswith("/"):
        return False
    rest = current.split("://", 1)[-1]
    path = "/" + rest.split("/", 1)[1] if "/" in rest else "/"
    return path == expected or path.split("?", 1)[0].split("#", 1)[0] == expected


class Executor:
    def __init__(
        self,
        settings: QASettings,
        policy: EgressPolicy,
        run_dir: Path,
        allow_destructive: bool = False,
        clock: Callable[[], float] = time.monotonic,
        allow_forms: bool = False,
    ) -> None:
        self.settings = settings
        self.limits = settings.limits
        self.policy = policy
        self.run_dir = run_dir
        self.allow_destructive = allow_destructive
        self.allow_forms = allow_forms
        self.secrets = settings.automation.secret_values()
        self.redact = settings.redactor()
        self.clock = clock
        self._pw: Any = None
        self._browser: Any = None

    # --- Browser lifecycle ---------------------------------------------------------

    def _launch(self) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=self.policy.browser_args(),
            # "<-loopback>" removes Chromium's implicit loopback bypass: only vetted host:port pairs go direct.
            proxy={"server": BLOCKING_PROXY, "bypass": ",".join(["<-loopback>", self.policy.proxy_bypass()])},
            chromium_sandbox=self.settings.automation.chromium_sandbox,
            timeout=60_000,
        )

    def browser_version(self) -> str:
        return f"Chromium {self._browser.version}" if self._browser is not None else ""

    def close(self) -> None:
        for closer in (lambda: self._browser and self._browser.close(), lambda: self._pw and self._pw.stop()):
            try:
                closer()
            except Exception:  # noqa: BLE001, S110 - cleanup must not hide the run's result
                pass
        self._browser = self._pw = None

    # --- Run -------------------------------------------------------------------------

    def run(self, run: QARun, on_case: Callable[[QARun, CaseResult], None] | None = None) -> QARun:
        deadline = self.clock() + self.limits.run_timeout_s
        launch_error = ""
        executed = 0
        try:
            for index, case in enumerate(run.cases):
                result = self._next_result(run, index, case, executed, deadline, launch_error)
                if result is None:  # the case may run
                    if self._browser is None and not launch_error:
                        try:
                            self._launch()
                            run.browser = self.browser_version()
                        except Exception as exc:  # noqa: BLE001 - not installed, sandbox, ...
                            launch_error = clean_error(str(exc), self.redact)
                            run.error = launch_error
                    if launch_error:
                        result = self._skipped(case, RunStatus.BLOCKED, "browser", error=launch_error)
                    else:
                        executed += 1
                        result = self._run_case(index, case, run.target_url, deadline)
                run.results.append(result)
                if on_case:
                    on_case(run, result)
            run.state = RunState.COMPLETED
        except Exception as exc:  # noqa: BLE001 - keep the partial results
            run.state = RunState.ABORTED
            run.error = clean_error(str(exc), self.redact)
            done = {r.case_id for r in run.results}
            run.results += [self._skipped(c, RunStatus.NOT_RUN, "aborted") for c in run.cases if c.id not in done]
        finally:
            self.close()
            run.finished_at = now()
        return run

    def _next_result(
        self, run: QARun, index: int, case: PlanCase, executed: int, deadline: float, launch_error: str
    ) -> CaseResult | None:
        if verdict := preflight(case, self.policy, self.secrets, self.limits, self.allow_destructive, self.allow_forms):
            return self._skipped(case, verdict.status, verdict.reason, verdict.params)
        if executed >= self.limits.max_cases:
            return self._skipped(case, RunStatus.NOT_RUN, "run_limit", {"max": str(self.limits.max_cases)})
        if self.clock() >= deadline:
            return self._skipped(case, RunStatus.NOT_RUN, "run_timeout")
        return None

    def _skipped(
        self, case: PlanCase, status: RunStatus, reason: str, params: dict[str, str] | None = None, error: str = ""
    ) -> CaseResult:
        return CaseResult(
            case_id=case.id, requirement_id=case.requirement_id, test_case_id=case.test_case_id, title=case.title,
            status=status, reason=reason, reason_params=params or {}, error=error,
            expected_result=case.expected_result, started_at=now(),
        )

    # --- One case ----------------------------------------------------------------------

    def _run_case(self, index: int, case: PlanCase, target_url: str, deadline: float) -> CaseResult:
        from playwright.sync_api import Error as PlaywrightError

        result = self._skipped(case, RunStatus.PASSED, "")
        started = self.clock()
        console: list[str] = []
        blocked: list[str] = []
        off_policy: list[str] = []
        masks: list[Any] = []
        context = self._browser.new_context(
            accept_downloads=False,
            service_workers="block",
            ignore_https_errors=self.settings.automation.ignore_https_errors,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        context.set_default_timeout(self.limits.step_timeout_ms)
        context.set_default_navigation_timeout(self.limits.nav_timeout_ms)

        def guard(route: Any) -> None:
            url = route.request.url
            if url.startswith(INTERNAL_SCHEMES) or self.policy.allows(url):
                route.continue_()
            else:
                if len(blocked) < MAX_CONSOLE:
                    blocked.append(self.redact(url)[:300])
                route.abort("blockedbyclient")

        context.route("**/*", guard)
        page = context.new_page()

        def on_request(request: Any) -> None:
            if request.is_navigation_request() and request.frame == page.main_frame:
                url = request.url
                if not url.startswith(INTERNAL_SCHEMES) and not self.policy.allows(url):
                    off_policy.append(url)

        def record(text: str) -> None:
            if len(console) < MAX_CONSOLE:
                console.append(self.redact(text)[:500])

        page.on("request", on_request)
        page.on("console", lambda message: record(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: record(str(error)))
        page.on("dialog", lambda dialog: dialog.dismiss())

        steps = [PlanStep(action=StepAction.GOTO, value=target_url), *case.steps]
        try:
            for number, step in enumerate(steps):
                if self.clock() >= deadline:
                    raise _Blocked("run_timeout")
                step_started = self.clock()
                status, error = RunStatus.PASSED, ""
                try:
                    self._do(page, step, masks)
                    self._check_location(page, off_policy)
                except AssertionError as exc:
                    status, error = RunStatus.FAILED, clean_error(str(exc), self.redact)
                    result.reason = "assertion"
                except _Failed as exc:
                    status, error = RunStatus.FAILED, clean_error(str(exc), self.redact)
                    result.reason, result.reason_params = exc.reason, dict(exc.params)
                except _Blocked as exc:
                    status, error = RunStatus.BLOCKED, ""
                    result.reason, result.reason_params = exc.reason, dict(exc.params)
                except PlaywrightError as exc:
                    if off_policy:
                        status = RunStatus.BLOCKED
                        result.reason, result.reason_params = "redirect", {"url": self.redact(off_policy[0])[:300]}
                    else:
                        status, error = RunStatus.FAILED, clean_error(str(exc), self.redact)
                        result.reason = "action_error"
                result.steps.append(StepResult(
                    index=number, step=step, status=status, error=error,
                    duration_ms=int((self.clock() - step_started) * 1000),
                ))
                if status != RunStatus.PASSED:
                    result.status, result.error = status, error
                    break
        except _Blocked as exc:  # out of time between steps
            result.status, result.reason, result.reason_params = RunStatus.BLOCKED, exc.reason, dict(exc.params)
        finally:
            result.final_url = self.redact(page.url)[:500] if not page.is_closed() else ""
            result.actual_result = self._actual(page, result)
            result.screenshot = self._screenshot(page, index, case, masks)
            result.console_errors = console
            result.blocked_requests = blocked
            result.duration_ms = int((self.clock() - started) * 1000)
            try:
                context.close()
            except PlaywrightError:
                pass
        return result

    def _check_location(self, page: Any, off_policy: list[str]) -> None:
        if off_policy:
            raise _Blocked("redirect", url=self.redact(off_policy[0])[:300])
        url = page.url
        if not url.startswith(INTERNAL_SCHEMES) and not self.policy.allows(url):
            raise _Blocked("redirect", url=self.redact(url)[:300])

    def _locator(self, page: Any, target: str) -> Any:
        loc = parse_locator(target)
        if loc.kind == "label":
            return page.get_by_label(loc.value, exact=True)
        if loc.kind == "text":
            return page.get_by_text(loc.value)
        if loc.kind == "placeholder":
            return page.get_by_placeholder(loc.value, exact=True)
        if loc.kind == "testid":
            return page.get_by_test_id(loc.value)
        if loc.kind == "role":
            return page.get_by_role(loc.value, name=loc.name, exact=True) if loc.name else page.get_by_role(loc.value)
        return page.locator(f"css={loc.value}")

    def _settle(self, page: Any) -> None:
        """Let a navigation started by the last action finish (no-op when there is none)."""
        from playwright.sync_api import Error as PlaywrightError

        try:
            page.wait_for_load_state("load", timeout=self.limits.nav_timeout_ms)
        except PlaywrightError:
            pass

    def _do(self, page: Any, step: PlanStep, masks: list[Any]) -> None:
        from playwright.sync_api import expect

        timeout = self.limits.step_timeout_ms
        action = step.action
        # validate_step (in preflight) guarantees a target for every action that uses `loc`.
        loc: Any = self._locator(page, step.target) if step.target else None
        if action == StepAction.GOTO:
            try:
                url = check_navigation(step.value, self.policy)
            except UrlRejected as rejected:
                raise _Blocked("url", code=rejected.code, **rejected.params) from None
            response = page.goto(url, wait_until="load")
            if response is not None and response.status >= 500:
                raise _Failed("http_status", f"HTTP {response.status} for {self.redact(url)}", status=str(response.status))
        elif action == StepAction.FILL:
            name = secret_name(step.value)
            value = self.secrets[name] if name else ("" if step.value == EMPTY else step.value)
            loc.fill(value)
            if name:
                masks.append(loc)
        elif action == StepAction.CLICK:
            if not self.allow_destructive and (term := self._destructive_element(loc)):
                raise _Blocked("destructive", term=term)
            loc.click()
            self._settle(page)
        elif action == StepAction.SELECT:
            loc.select_option(step.value)
        elif action == StepAction.CHECK:
            loc.check()
        elif action == StepAction.UNCHECK:
            loc.uncheck()
        elif action == StepAction.PRESS:
            (loc.press if loc is not None else page.keyboard.press)(step.value)
            self._settle(page)
        elif action == StepAction.WAIT_FOR:
            loc.wait_for(state="visible")
        elif action == StepAction.EXPECT_VISIBLE:
            expect(loc).to_be_visible(timeout=timeout)
        elif action == StepAction.EXPECT_HIDDEN:
            expect(loc).to_be_hidden(timeout=timeout)
        elif action == StepAction.EXPECT_TEXT:
            expect(loc if loc is not None else page.locator("body")).to_contain_text(step.value, timeout=timeout)
        elif action == StepAction.EXPECT_NO_TEXT:
            expect(loc if loc is not None else page.locator("body")).not_to_contain_text(step.value, timeout=timeout)
        elif action == StepAction.EXPECT_URL:
            self._expect_url(page, step.value, timeout)
        elif action == StepAction.EXPECT_TITLE:
            expect(page).to_have_title(re.compile(re.escape(step.value)), timeout=timeout)
        elif action == StepAction.EXPECT_VALUE:
            expect(loc).to_have_value(step.value, timeout=timeout)

    def _expect_url(self, page: Any, expected: str, timeout: int) -> None:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        try:
            page.wait_for_url(lambda url: url_matches(url, expected), timeout=timeout, wait_until="commit")
        except PlaywrightTimeout:
            raise AssertionError(f"Expected URL: {expected}\nReceived URL: {page.url}") from None

    def _destructive_element(self, loc: Any) -> str | None:
        """A destructive word in what the element says (text, value, aria-label, title)."""
        parts = [loc.inner_text(timeout=self.limits.step_timeout_ms)]
        for attribute in ("value", "aria-label", "title"):
            parts.append(loc.get_attribute(attribute, timeout=self.limits.step_timeout_ms) or "")
        return destructive_term(" ".join(parts))

    def _actual(self, page: Any, result: CaseResult) -> str:
        """What was observed, from the page itself. Never inferred."""
        if page.is_closed():
            return ""
        try:
            title = page.title()
        except Exception:  # noqa: BLE001
            title = ""
        location = f"Page: \"{title}\" at {result.final_url}" if title else f"Page: {result.final_url}"
        failed = result.failed_step
        if result.status == RunStatus.PASSED:
            return self.redact(f"All {len(result.steps)} steps passed. {location}")
        if failed is None:
            return self.redact(location)
        observed = ""
        if failed.status == RunStatus.FAILED and failed.step.action in (StepAction.EXPECT_TEXT, StepAction.EXPECT_NO_TEXT):
            observed = self._visible_text(page, failed.step)
        text = f"Step {failed.index + 1}: {step_label(failed.step)} — {failed.status.value}. {location}"
        if observed:
            text += f"\nVisible text: {observed}"
        return self.redact(text)[:MAX_ERROR]

    def _visible_text(self, page: Any, step: PlanStep) -> str:
        from playwright.sync_api import Error as PlaywrightError

        try:
            loc = self._locator(page, step.target) if step.target else page.locator("body")
            text = " ".join(loc.first.inner_text(timeout=2000).split())
        except PlaywrightError:
            return ""
        return text[:MAX_RECEIVED] + ("…" if len(text) > MAX_RECEIVED else "")

    def _screenshot(self, page: Any, index: int, case: PlanCase, masks: list[Any]) -> str:
        from playwright.sync_api import Error as PlaywrightError

        if page.is_closed() or page.url.startswith("about:"):
            return ""
        # Fields filled with a secret are masked, but a page that displays a secret value
        # (e.g. echoes it back) would show it in the image: no screenshot then.
        try:
            if self.redact.contains_secret(page.content() + page.inner_text("body", timeout=2000)):
                return SCREENSHOT_WITHHELD
        except PlaywrightError:
            return ""
        name = f"{index + 1:03d}-{SAFE_NAME.sub('_', case.id)[:40]}.png"
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(self.run_dir / name), full_page=True, mask=masks,
                            timeout=self.limits.step_timeout_ms, animations="disabled")
        except (PlaywrightError, OSError):
            return ""
        return name
