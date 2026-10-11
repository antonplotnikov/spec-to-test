# Test Summary Report — Spec-to-Test v1.0.0

| Field | Value |
|---|---|
| Version tested | 1.0.0 (release candidate, not yet published) |
| Test period | 2026-10-11 |
| Prepared by | Release preparation (AI coding assistant), to be reviewed by the maintainer |
| Plan | [TEST_PLAN.md](TEST_PLAN.md) |

All numbers below come from real runs on the date above. Nothing that was not
run is reported as passed.

## 1. Environment

| Item | Value |
|---|---|
| OS | macOS (Darwin 27) |
| Python | 3.11.17 |
| Key packages | streamlit 1.65.0, pydantic 2.14.0, pypdf 6.20.0, pandas 3.0.6 |
| Browser (manual checks) | Chromium-based preview pane in the Claude desktop app |

## 2. Automated results

Command: `pytest -q --junitxml=…` (project venv) and a second run in a fresh
virtual environment installed only from `requirements-dev.txt`.

| Run | Tests | Passed | Failed | Errors | Skipped | Duration |
|---|---:|---:|---:|---:|---:|---:|
| Project venv | 617 | 617 | 0 | 0 | 0 | 9.1 s |
| Clean venv from `requirements-dev.txt` | 617 | 617 | 0 | 0 | 0 | 9.9 s |

| Test file | Tests | Focus |
|---|---:|---|
| test_i18n.py | 289 | Every key translated in 3 languages, same placeholders |
| test_input_parser.py | 41 | Requirement extraction |
| test_rule_engine.py | 33 | Rule-based findings |
| test_reference_spec.py | 25 | Known-good / known-bad reference specification |
| test_file_formats.py | 22 | TXT / MD / PDF validation |
| test_app_features.py | 22 | Streamlit UI: editor, RTM, bugs, AI consent, persistence, regressions |
| test_audit_regressions.py | 20 | Earlier parser regressions |
| test_formatting.py | 19 | Markdown escaping (BUG-002) |
| test_id_mapping.py | 18 | Requirement IDs |
| test_test_design.py | 18 | BVA, EP, decision tables |
| test_ai_analysis.py | 15 | AI config, consent, quote verification, error mapping (fake client) |
| test_exports.py | 14 | Jira / TestRail / RTM CSV, Markdown report, link integrity, CSV injection |
| test_app.py | 12 | Core UI flows |
| test_quality.py | 10 | Quality score |
| test_security.py | 9 | Secrets, network isolation, hostile input |
| test_storage.py | 9 | Persistence and storage modes (BUG-001) |
| test_localization.py | 8 | All tabs in EN / UK / RU |
| test_bug_reports.py | 7 | Bug report generation |
| test_rtm_dashboard.py | 7 | RTM, coverage, dashboard, filters |
| test_test_generator.py | 7 | Draft test cases |
| test_release.py | 7 | Version, required files, dependency bounds, docs ↔ tests |
| test_models.py | 5 | Data models |
| **Total** | **617** | |

## 3. Static analysis and security

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | All checks passed |
| Types | `mypy` | No issues in 15 source files |
| Dependencies (runtime + AI) | `pip-audit -r requirements-ai.txt` | No known vulnerabilities |
| Dependencies (dev) | `pip-audit -r requirements-dev.txt` | No known vulnerabilities |
| Minimum allowed versions (before fix) | `pip-audit` on `streamlit==1.50.0`, `pypdf==5.0.0` | Advisories found → BUG-004, fixed |
| AI SDK compatibility | `inspect.signature` of `anthropic` 1.13.0 `messages.parse` (no network call) | All arguments used by the app are accepted |
| CI workflow | YAML parsed; jobs `lint`, `test`, `security` | Valid; **not yet run on GitHub** |

## 4. Manual results

| Test case | Result | Notes |
|---|---|---|
| TC-016 Work restored after reload | Pass | Browser preview |
| TC-019 User text shown literally | Pass | Browser preview, after the BUG-002 fix |
| TC-020 Large screen (1920 px) | Pass | Browser preview |
| TC-021 Phone screen (375 px) | Pass | Browser preview; no horizontal page scroll |
| All other manual cases (TC-001 … TC-015, TC-017, TC-018, TC-022) | Not executed | Covered by automated tests where listed in TEST_CASES.md; manual run pending |

## 5. Defects

7 defects found, 7 fixed, 0 open. Details: [BUG_REPORTS.md](BUG_REPORTS.md).

| Severity | Found | Fixed | Open |
|---|---:|---:|---:|
| Critical | 1 | 1 | 0 |
| High | 2 | 2 | 0 |
| Medium | 2 | 2 | 0 |
| Low | 2 | 2 | 0 |

## 6. Not tested

| Area | Reason |
|---|---|
| Live AI API call | No API key used; AI is tested with a fake client and an offline SDK signature check |
| Python 3.12 | Not installed locally; runs in the CI matrix after the first push |
| GitHub Actions | Repository not pushed yet (publishing needs maintainer approval) |
| Streamlit Community Cloud | Not deployed yet; `/mount/src` detection is unit-tested with a fake path |
| Real Jira / TestRail import | No test instances available; CSV format verified against documented columns |
| Firefox, Safari, Windows, mobile devices | Only a Chromium-based preview and emulated viewport sizes were used |
| Accessibility (screen readers, keyboard-only) | Not in scope for this release |
| Performance with the 500-requirement limit | Not measured |

## 7. Conclusion

All automated checks pass and no known defects are open. The exit criteria in
the test plan are **met for automated testing**. Before publishing, the
maintainer should run the manual test cases marked "Not executed", confirm CI
on GitHub, and complete [../RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md).
