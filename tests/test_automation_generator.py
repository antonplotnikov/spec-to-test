"""Script validation (traceability, safety) and deterministic TypeScript rendering."""

import json
import re

import pytest

from automation_fakes import REQ, SECRET_NAME, SECRET_VALUE, TC, config, good_script, resolver, step
from spec_to_test.automation.generator import (
    assertions_changed,
    render_config,
    render_spec,
    spec_file_name,
    validate_script,
)
from spec_to_test.automation.models import TestScript
from spec_to_test.automation.results import parse_report
from spec_to_test.automation.security import Redactor, build_egress_policy


@pytest.fixture
def env(tmp_path):
    cfg = config(tmp_path)
    policy = build_egress_policy("https://staging.example.com/", cfg, resolver())
    return cfg, policy, Redactor(cfg.secret_values())


def check(env, script: dict, allow_destructive: bool = False, tc=TC):
    cfg, policy, redact = env
    return validate_script(TestScript.model_validate(script), tc, REQ, policy, list(cfg.secrets), redact, allow_destructive)


def codes(problems) -> list[str]:
    return [p.code for p in problems]


def with_step(**fields) -> dict:
    script = good_script()
    script["steps"].insert(1, step(**fields))
    return script


def test_good_script_is_accepted_with_verified_trace(env):
    checks, problems = check(env, good_script())
    assert problems == []
    assert [(c.status, c.source, c.value) for c in checks] == [("verified", "expected_result", "Link expired")]


def test_assertion_must_quote_the_approved_text(env):
    script = good_script()
    script["steps"][-1]["evidence"] = "The page shows Link expired"  # paraphrase, not a quote
    _, problems = check(env, script)
    assert codes(problems) == ["evidence"]


def test_quote_from_the_requirement_is_accepted(env):
    script = good_script()
    script["steps"][-1]["evidence"] = 'an expired link shows "Link expired"'
    checks, problems = check(env, script)
    assert not problems and checks[0].source == "requirement"


def test_assumptions_are_not_a_source_for_assertions(env):
    script = with_step(action="expect_text", strategy="text", target="Expires", value="15 minutes",
                       evidence="Links expire after 15 minutes")  # only in the unconfirmed assumptions
    _, problems = check(env, script, tc=TC.model_copy(update={"expected_result": "The error \"Link expired\" is shown."}))
    assert "evidence" in codes(problems)


def test_text_assertion_value_must_come_from_the_quote(env):
    script = good_script()
    script["steps"][-1]["value"] = "Token invalid"  # observed on the page, not in the approved text
    _, problems = check(env, script)
    assert "value" in codes(problems)


def test_url_assertion_is_marked_interpreted(env):
    script = with_step(action="expect_url", value="/reset", tc_step=-1, evidence="the password is not changed")
    checks, problems = check(env, script)
    assert not problems
    assert [c.status for c in checks] == ["interpreted", "verified"]


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        (dict(action="goto", value="https://evil.example.org/"), "url"),
        (dict(action="goto", value="javascript:alert(1)"), "url"),
        (dict(action="click", strategy="role", role="div[onclick]", target="x"), "locator"),
        (dict(action="click", strategy="label"), "locator"),
        (dict(action="click"), "locator"),
        (dict(action="goto", strategy="text", target="x", value="/"), "locator"),
        (dict(action="fill", strategy="label", target="Email", secret="UNKNOWN"), "secret"),
        (dict(action="fill", strategy="label", target="Email", secret=SECRET_NAME, value="x"), "secret"),
        (dict(action="click", strategy="role", role="button", target="Save", secret=SECRET_NAME), "secret"),
        (dict(action="press", value="Enter; rm -rf /"), "value"),
        (dict(action="select", strategy="label", target="Country"), "value"),
        (dict(action="click", strategy="text", target="Help", tc_step=7), "tc_step"),
        (dict(action="click", strategy="role", role="button", target="Delete account"), "destructive"),
        (dict(action="fill", strategy="label", target="Password", value=SECRET_VALUE), "secret_value"),
        (dict(action="click", strategy="text", target="x" * 600), "too_long"),
    ],
)
def test_unsafe_or_invalid_steps_are_rejected(env, fields, code):
    _, problems = check(env, with_step(**fields))
    assert code in codes(problems)


def test_destructive_step_is_accepted_when_allowed(env):
    _, problems = check(env, with_step(action="click", strategy="role", role="button", target="Delete account"), True)
    assert problems == []


def test_assertions_changed_detects_any_change_to_expectations():
    before = TestScript.model_validate(good_script())
    relocated = good_script("Update password")
    relocated["steps"][-1]["strategy"], relocated["steps"][-1]["role"], relocated["steps"][-1]["target"] = "text", "", "Link"
    assert not assertions_changed(before, TestScript.model_validate(relocated))  # locators may change
    weakened = good_script()
    weakened["steps"][-1]["action"] = "expect_visible"
    assert assertions_changed(before, TestScript.model_validate(weakened))
    dropped = good_script()
    dropped["steps"].pop()
    assert assertions_changed(before, TestScript.model_validate(dropped))


# --- Rendering ---------------------------------------------------------------------------------


def test_spec_uses_user_facing_locators_and_traceability():
    code = render_spec(TestScript.model_validate(good_script()), TC, REQ, "claude-opus-5-5", "abc", "2026-10-12")
    assert "import { test, expect } from '@playwright/test';" in code
    assert 'test("TC-001: Expired link is rejected", { tag: ["@TC-001", "@REQ-001"] }' in code
    assert 'await page.goto("/reset?token=expired");' in code
    assert 'await page.getByLabel("New password").fill(secret("STAGING_PASSWORD"));' in code
    assert 'await page.getByRole("button", { name: "Save password" }).click();' in code
    assert 'await expect(page.getByRole("alert")).toContainText("Link expired");' in code
    assert 'test.step("Step 2: Submit a new password"' in code
    assert "// Expected (from the approved text): The error \"Link expired\" is shown" in code
    assert SECRET_VALUE not in code
    assert "locator(" not in code and "xpath" not in code.lower()


def test_hostile_text_cannot_break_out_of_strings_or_comments():
    tc = TC.model_copy(update={"title": "x }); process.exit(1); //", "steps": ["a */ evil()", "b\nconst y = 1"]})
    script = good_script()
    script["steps"][1]["target"] = 'Pass"word`${process.env.HOME}`\\'
    code = render_spec(TestScript.model_validate(script), tc, REQ, "m", "j", "d")
    for line in code.splitlines():
        if line.lstrip().startswith("//"):
            assert " " not in line
    assert " " not in code
    assert '"Pass\\"word`${process.env.HOME}`\\\\"' in code  # JSON string: no template evaluation
    assert "\nconst y = 1" not in code


def test_url_assertion_is_escaped_into_a_regexp():
    script = good_script()
    script["steps"].append(step("expect_url", value="/reset?token=(a+b)", tc_step=-1, evidence="the password is not changed"))
    code = render_spec(TestScript.model_validate(script), TC, REQ, "m", "j", "d")
    assert 'toHaveURL(new RegExp("\\\\/reset\\\\?token=\\\\(a\\\\+b\\\\)"))' in code


def test_spec_file_name_is_safe():
    assert spec_file_name(TC.model_copy(update={"id": "../TC 1"})) == "___tc_1.spec.ts"


def test_sandbox_config_pins_egress_and_collects_evidence(tmp_path):
    cfg = config(tmp_path, AUTOMATION_CHROMIUM_SANDBOX="false")
    policy = build_egress_policy("https://staging.example.com/", cfg, resolver())
    text = render_config(policy, cfg)
    settings = json.loads(re.search(r"defineConfig\((\{.*\})\);", text, re.S).group(1))
    use = settings["use"]
    assert use["baseURL"] == "https://staging.example.com/"
    assert use["proxy"] == {"server": "http://egress-blocked.invalid:9", "bypass": "staging.example.com:443"}
    assert use["launchOptions"]["args"] == ["--host-resolver-rules=MAP staging.example.com 93.184.216.34, MAP * ~NOTFOUND"]
    assert use["launchOptions"]["chromiumSandbox"] is False
    assert (use["trace"], use["screenshot"], use["serviceWorkers"]) == ("on", "on", "block")
    assert settings["retries"] == 0 and settings["workers"] == 1
    assert settings["reporter"][0] == ["json", {"outputFile": "report/results.json"}]


# --- Report parsing ----------------------------------------------------------------------------


def report(job_dir, **result) -> dict:
    base = {"status": "passed", "duration": 812, "errors": [], "attachments": []}
    base.update(result)
    return {"suites": [{"title": "tc-001.spec.ts", "specs": [], "suites": [
        {"title": "", "specs": [{"title": "TC-001: Expired link is rejected", "tests": [{"results": [base]}]}]}]}],
        "errors": [], "stats": {"duration": 1500}}


def write(job_dir, data) -> None:
    (job_dir / "report").mkdir(parents=True, exist_ok=True)
    (job_dir / "report" / "results.json").write_text(json.dumps(data))


def test_report_with_passing_test(tmp_path):
    shot = tmp_path / "test-results" / "a" / "test-finished-1.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"png")
    write(tmp_path, report(tmp_path, attachments=[
        {"name": "screenshot", "contentType": "image/png", "path": str(shot)},
        {"name": "trace", "contentType": "application/zip", "path": str(tmp_path / "test-results" / "a" / "trace.zip")},
        {"name": "screenshot", "contentType": "image/png", "path": "/etc/passwd"},  # outside the job folder
    ]))
    result, artifacts = parse_report(tmp_path / "report" / "results.json", tmp_path, Redactor())
    assert result.passed and result.duration_ms == 1500
    assert [(a.kind, a.path) for a in artifacts] == [
        ("screenshot", "test-results/a/test-finished-1.png"), ("trace", "test-results/a/trace.zip")]


def test_report_with_failure_is_cleaned_and_masked(tmp_path):
    error = {"message": "\x1b[31mError:\x1b[39m expected Link expired, got Hunter-2-pass", "location": {"file": "/x/tc-001.spec.ts", "line": 18}}
    write(tmp_path, report(tmp_path, status="failed", errors=[error]))
    result, _ = parse_report(tmp_path / "report" / "results.json", tmp_path, Redactor({"PW": "Hunter-2-pass"}))
    assert not result.passed
    outcome = result.tests[0]
    assert outcome.status == "failed" and outcome.error_location == "tc-001.spec.ts:18"
    assert "\x1b" not in outcome.error and "Hunter-2-pass" not in outcome.error
    assert "expected Link expired" in result.failure_summary()


def test_missing_report_is_a_failed_run(tmp_path):
    result, artifacts = parse_report(tmp_path / "nope.json", tmp_path, Redactor())
    assert not result.passed and result.errors and artifacts == []
