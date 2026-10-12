"""Turn a TestScript into a Playwright TypeScript test, deterministically.

Claude never writes code directly. It submits a structured script (actions,
user-facing locators, assertions with quotes), which is checked here and then
rendered by fixed templates, so the generated file can only contain:
- locators by role, label, test id, placeholder or visible text (no CSS/XPath),
- navigation to the vetted staging origin,
- assertions whose quote is found in the approved expected result or
  requirement (text assertions must also expect a value from that quote),
- secrets by name (process.env), never by value.
"""

import json
import re
from collections.abc import Callable

from pydantic import BaseModel

from spec_to_test.automation.config import AutomationConfig
from spec_to_test.automation.models import (
    PAGE_ACTIONS,
    TEXT_ASSERTIONS,
    AssertionCheck,
    ScriptStep,
    TestScript,
)
from spec_to_test.automation.security import (
    BLOCKING_PROXY,
    EgressPolicy,
    Redactor,
    UrlRejected,
    check_navigation,
    destructive_term,
)
from spec_to_test.models import Requirement, TestCase

MAX_STEPS = 60
MAX_FIELD = 500
# WAI-ARIA roles Playwright's getByRole accepts that make sense in a test.
ARIA_ROLES = frozenset(
    """alert alertdialog application article banner blockquote button caption cell checkbox code
    columnheader combobox complementary contentinfo definition deletion dialog document emphasis feed
    figure form generic grid gridcell group heading img insertion link list listbox listitem log main
    marquee math menu menubar menuitem menuitemcheckbox menuitemradio meter navigation none note option
    paragraph presentation progressbar radio radiogroup region row rowgroup rowheader scrollbar search
    searchbox separator slider spinbutton status strong subscript superscript switch tab table tablist
    tabpanel term textbox time timer toolbar tooltip tree treegrid treeitem""".split()
)
ELEMENT_ACTIONS = frozenset({"click", "fill", "select", "check", "uncheck", "hover"})
INTERACTIONS = frozenset({"click", "fill", "select", "check", "uncheck", "press", "goto"})
KEY_PATTERN = re.compile(r"^[A-Za-z0-9]+(\+[A-Za-z0-9]+)*$")
Report = Callable[[int, str, str], None]


class ScriptProblem(BaseModel):
    step: int  # 1-based, 0 = whole script
    code: str
    detail: str

    def __str__(self) -> str:
        where = f"step {self.step}" if self.step else "script"
        return f"{where}: {self.detail}"


def _norm(text: str) -> str:
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'").replace("«", '"').replace("»", '"')
    return " ".join(text.split()).casefold()


def _quote_source(evidence: str, tc: TestCase, requirement: Requirement | None) -> str | None:
    quote = _norm(evidence).strip(" \"'.")
    if len(quote) < 3:
        return None
    if quote in _norm(tc.expected_result):
        return "expected_result"
    if requirement is not None and quote in _norm(requirement.text):
        return "requirement"
    return None


def validate_script(
    script: TestScript,
    tc: TestCase,
    requirement: Requirement | None,
    policy: EgressPolicy,
    secret_names: list[str],
    redactor: Redactor,
    allow_destructive: bool,
) -> tuple[list[AssertionCheck], list[ScriptProblem]]:
    """Check a submitted script. Returns the assertion trace and every problem found."""
    problems: list[ScriptProblem] = []
    checks: list[AssertionCheck] = []

    def problem(index: int, code: str, detail: str) -> None:
        problems.append(ScriptProblem(step=index, code=code, detail=detail))

    if len(script.steps) > MAX_STEPS:
        problem(0, "too_long", f"at most {MAX_STEPS} steps are allowed")
    if redactor.contains_secret(script.model_dump_json()):
        problem(0, "secret_value", "the script contains a secret value; use the secret's name in `secret`")
    for index, step in enumerate(script.steps, start=1):
        for field in ("target", "value", "evidence", "role", "secret"):
            if len(getattr(step, field)) > MAX_FIELD:
                problem(index, "too_long", f"`{field}` is longer than {MAX_FIELD} characters")
        _check_locator(index, step, problem)
        _check_action(index, step, policy, secret_names, problem)
        if not -1 <= step.tc_step <= len(tc.steps):
            problem(index, "tc_step", f"`tc_step` must be between -1 and {len(tc.steps)}")
        if step.action in INTERACTIONS and not allow_destructive:
            term = destructive_term(f"{step.target} {step.value if step.action != 'fill' else ''}")
            if term:
                problem(index, "destructive", f"'{term}' looks destructive and destructive actions are not allowed")
        if step.is_assertion:
            check = _check_assertion(index, step, tc, requirement, problem)
            if check is not None:
                checks.append(check)
    if not any(step.is_assertion for step in script.steps):
        problem(0, "no_assertion", "the script must assert the expected result")
    return checks, problems


def _check_locator(index: int, step: ScriptStep, problem: Report) -> None:
    page_level = step.action in PAGE_ACTIONS
    if step.strategy == "page":
        if not page_level:
            problem(index, "locator", f"`{step.action}` needs an element locator")
        return
    if step.action in ("goto", "expect_url", "expect_title"):
        problem(index, "locator", f"`{step.action}` works on the page; use strategy \"page\"")
        return
    if step.strategy == "role":
        if step.role not in ARIA_ROLES:
            problem(index, "locator", f"unknown ARIA role {step.role!r}")
    elif not step.target.strip():
        problem(index, "locator", f"strategy {step.strategy!r} needs `target`")


def _check_action(
    index: int, step: ScriptStep, policy: EgressPolicy, secret_names: list[str], problem: Report
) -> None:
    if step.secret and step.action != "fill":
        problem(index, "secret", "`secret` can only be used with fill")
    if step.action == "goto":
        try:
            check_navigation(step.value, policy)
        except UrlRejected:
            problem(index, "url", "goto must open a path on the staging site (e.g. \"/login\") or an allowed URL")
    elif step.action == "fill":
        if step.secret:
            if step.secret not in secret_names:
                problem(index, "secret", f"unknown secret {step.secret!r}; available: {', '.join(secret_names) or 'none'}")
            if step.value:
                problem(index, "secret", "leave `value` empty when `secret` is set")
    elif step.action == "select" and not step.value.strip():
        problem(index, "value", "select needs the option in `value`")
    elif step.action == "press" and not KEY_PATTERN.match(step.value):
        problem(index, "value", "press needs a key such as \"Enter\" or \"Control+A\"")
    elif step.action in ("expect_url", "expect_title") and not step.value.strip():
        problem(index, "value", f"{step.action} needs the expected text in `value`")


def _check_assertion(
    index: int, step: ScriptStep, tc: TestCase, requirement: Requirement | None, problem: Report
) -> AssertionCheck | None:
    source = _quote_source(step.evidence, tc, requirement)
    if source is None:
        problem(
            index,
            "evidence",
            "`evidence` must quote the approved expected result or requirement word for word; "
            "assertions may not come from what the page shows",
        )
        return None
    evidence = _norm(step.evidence)
    key_text = step.value if step.action in TEXT_ASSERTIONS or step.action == "expect_url" else step.target
    in_quote = bool(key_text.strip()) and _norm(key_text).strip(" \"'") in evidence
    if step.action in TEXT_ASSERTIONS:
        if not step.value.strip():
            problem(index, "value", f"{step.action} needs the expected text in `value`")
            return None
        if not in_quote:
            problem(index, "value", "the expected text in `value` must appear in the quoted `evidence`")
            return None
    return AssertionCheck(
        step_index=index,
        action=step.action,
        value=step.value or step.target,
        evidence=step.evidence.strip(),
        status="verified" if in_quote else "interpreted",
        source="expected_result" if source == "expected_result" else "requirement",
    )


def assertions_changed(before: TestScript, after: TestScript) -> bool:
    """True when a repair added, removed or altered what the test asserts."""
    return sorted(s.assertion_key() for s in before.steps if s.is_assertion) != sorted(
        s.assertion_key() for s in after.steps if s.is_assertion
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _js(text: str) -> str:
    """A JavaScript string literal (JSON strings are valid JS)."""
    return json.dumps(text, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _comment(text: str, limit: int = 160) -> str:
    """Single-line comment text: no line breaks of any kind."""
    flat = " ".join(re.sub(r"[\r\n\u2028\u2029\x85\v\f]", " ", text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _regex_literal(text: str) -> str:
    escaped = re.sub(r"[\\^$.*+?()[\]{}|/-]", lambda m: "\\" + m.group(0), text.strip())
    return f"new RegExp({_js(escaped)})"


def _tag(text: str) -> str:
    return "@" + re.sub(r"[^A-Za-z0-9_.-]", "_", text)


def _locator(step: ScriptStep) -> str:
    exact = ", exact: true" if step.exact else ""
    if step.strategy == "role":
        options = f", {{ name: {_js(step.target)}{exact} }}" if step.target else ""
        return f"page.getByRole({_js(step.role)}{options})"
    if step.strategy == "testid":
        return f"page.getByTestId({_js(step.target)})"
    method = {"label": "getByLabel", "placeholder": "getByPlaceholder", "text": "getByText"}[step.strategy]
    options = ", { exact: true }" if step.exact else ""
    return f"page.{method}({_js(step.target)}{options})"


def _statement(step: ScriptStep) -> str:
    action = step.action
    if action == "goto":
        return f"await page.goto({_js(step.value.strip())});"
    if action == "press":
        if step.strategy == "page":
            return f"await page.keyboard.press({_js(step.value)});"
        return f"await {_locator(step)}.press({_js(step.value)});"
    if action == "expect_url":
        return f"await expect(page).toHaveURL({_regex_literal(step.value)});"
    if action == "expect_title":
        return f"await expect(page).toHaveTitle({_regex_literal(step.value)});"
    loc = _locator(step)
    if action == "fill":
        value = f"secret({_js(step.secret)})" if step.secret else _js(step.value)
        return f"await {loc}.fill({value});"
    simple = {
        "click": ".click()", "check": ".check()", "uncheck": ".uncheck()", "hover": ".hover()",
    }
    if action in simple:
        return f"await {loc}{simple[action]};"
    if action == "select":
        return f"await {loc}.selectOption({_js(step.value)});"
    matchers = {
        "expect_visible": "toBeVisible()", "expect_hidden": "toBeHidden()",
        "expect_enabled": "toBeEnabled()", "expect_disabled": "toBeDisabled()",
        "expect_checked": "toBeChecked()",
        "expect_value": f"toHaveValue({_js(step.value)})",
        "expect_text": f"{'toHaveText' if step.exact else 'toContainText'}({_js(step.value)})",
    }
    return f"await expect({loc}).{matchers[action]};"


def _group_title(tc_step: int, tc: TestCase) -> str:
    if tc_step == 0:
        return "Setup"
    if tc_step == -1:
        return f"Expected result: {_comment(tc.expected_result, 120)}"
    return f"Step {tc_step}: {_comment(tc.steps[tc_step - 1], 120)}"


def spec_file_name(tc: TestCase) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", tc.id).lower() + ".spec.ts"


def render_spec(
    script: TestScript, tc: TestCase, requirement: Requirement | None, model: str, job_id: str, generated_at: str
) -> str:
    """The TypeScript test file. Uses `baseURL`, so it runs against any environment."""
    lines = [
        "// Generated by Spec-to-Test Automation. Review before adding it to your suite.",
        f"// Test case:   {_comment(tc.id)} — {_comment(tc.title)}",
        f"// Requirement: {_comment(tc.requirement_id)}" + (f" — {_comment(requirement.text)}" if requirement else ""),
        f"// Generated:   {_comment(generated_at)} · model {_comment(model or 'n/a')} · job {_comment(job_id)}",
        "// Assertions come only from the approved test case and requirement (each one quotes its source).",
        "import { test, expect } from '@playwright/test';",
        "",
    ]
    if any(step.secret for step in script.steps):
        lines += [
            "/** Credentials come from environment variables and are never written in this file. */",
            "function secret(name: string): string {",
            "  const value = process.env[name];",
            "  if (!value) throw new Error(`Set the ${name} environment variable to run this test.`);",
            "  return value;",
            "}",
            "",
        ]
    tags = ", ".join(_js(t) for t in dict.fromkeys([_tag(tc.id), _tag(tc.requirement_id)]))
    title = f"{tc.id}: {tc.title}"
    lines.append(f"test({_js(title)}, {{ tag: [{tags}] }}, async ({{ page }}) => {{")
    groups: list[tuple[int, list[ScriptStep]]] = []
    for step in script.steps:
        if groups and groups[-1][0] == step.tc_step:
            groups[-1][1].append(step)
        else:
            groups.append((step.tc_step, [step]))
    for tc_step, steps in groups:
        lines.append(f"  await test.step({_js(_group_title(tc_step, tc))}, async () => {{")
        for step in steps:
            if step.is_assertion:
                lines.append(f"    // Expected (from the approved text): {_comment(step.evidence)}")
            lines.append(f"    {_statement(step)}")
        lines.append("  });")
    lines += ["});", ""]
    return "\n".join(lines)


def render_config(policy: EgressPolicy, config: AutomationConfig) -> str:
    """playwright.config.ts for the sandboxed validation run (not part of the export)."""
    use = {
        "baseURL": policy.base_url,
        "browserName": "chromium",
        "headless": True,
        "trace": "on",
        "screenshot": "on",
        "video": "off",
        "actionTimeout": 15_000,
        "navigationTimeout": 30_000,
        "serviceWorkers": "block",
        "acceptDownloads": False,
        "ignoreHTTPSErrors": config.ignore_https_errors,
        "viewport": {"width": 1280, "height": 720},
        # Egress control: see security.py.
        "proxy": {"server": BLOCKING_PROXY, "bypass": policy.proxy_bypass()},
        "launchOptions": {"args": policy.browser_args(), "chromiumSandbox": config.chromium_sandbox},
    }
    settings = {
        "testDir": "./tests",
        "outputDir": "./test-results",
        "timeout": 90_000,
        "globalTimeout": max(30, config.run_timeout - 15) * 1000,
        "expect": {"timeout": 10_000},
        "retries": 0,
        "workers": 1,
        "maxFailures": 1,
        "forbidOnly": True,
        "reporter": [["json", {"outputFile": "report/results.json"}], ["line"]],
        "use": use,
    }
    return (
        "// Sandbox configuration written by Spec-to-Test for one validation run.\n"
        "import { defineConfig } from '@playwright/test';\n\n"
        f"export default defineConfig({json.dumps(settings, indent=2, ensure_ascii=False)});\n"
    )
