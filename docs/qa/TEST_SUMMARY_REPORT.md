# Test Summary Report — Spec-to-Test v1.1.0

| Field | Value |
|---|---|
| Version tested | 1.1.0 (release candidate, not yet published): 1.0.0 plus Grill Mode |
| Test period | 2026-10-11 |
| Prepared by | Release preparation (AI coding assistant), to be reviewed by the maintainer |
| Plan | [TEST_PLAN.md](TEST_PLAN.md) |
| Previous report | v1.0.0: 617 tests, all passed (same date, before Grill Mode) |

All numbers below come from real runs on the date above. Nothing that was not
run is reported as passed.

## 1. Environment

| Item | Value |
|---|---|
| OS | macOS (Darwin 27) |
| Python | 3.11.17 |
| Key packages | streamlit 1.65.0, pydantic 2.14.0, pypdf 6.20.0, pandas 3.0.6; anthropic 1.13.0 (optional) |
| Browser (manual checks) | None for 1.1.0 — see section 6 |

## 2. Automated results

Command: `pytest -q -p no:cacheprovider` in three environments.

| Run | Tests | Passed | Failed | Errors | Skipped | Duration |
|---|---:|---:|---:|---:|---:|---:|
| Project venv | 1211 | 1211 | 0 | 0 | 0 | 20.0 s |
| Clean venv from `requirements-dev.txt` | 1211 | 1211 | 0 | 0 | 0 | 23.1 s |
| Same clean venv + `requirements-ai.txt` (real `anthropic` SDK installed) | 1211 | 1211 | 0 | 0 | 0 | 19.0 s |

| Test file | Tests | Focus |
|---|---:|---|
| test_i18n.py | 616 | Every key translated in 3 languages, same placeholders (Grill keys included) |
| test_grill_validation.py | 46 | Deterministic checks: required fields, placeholders, duplicates, provenance |
| test_input_parser.py | 41 | Requirement extraction |
| test_grill_workflow.py | 39 | Grill state machine: transitions, stale revisions, back / skip / edit / cancel, confirmation |
| test_rule_engine.py | 33 | Rule-based findings |
| test_grill_ai.py | 31 | Grill AI: consent, minimal payload, validation of model output, error mapping (fake client) |
| test_grill_review.py | 30 | Content review: vague wording, limits vs. requirement, test-design consistency |
| test_grill_planner.py | 27 | Question banks, relevance, stop rule, rule-finding questions |
| test_reference_spec.py | 25 | Known-good / known-bad reference specification |
| test_grill_ui.py | 22 | Grill page via AppTest: all workflows, hand-over to workspace, isolation, EN/UK/RU |
| test_grill_integration.py | 22 | Grill results → TestCase / DefectReport, RTM, coverage, exports, Markdown, resolved findings, storage |
| test_file_formats.py | 22 | TXT / MD / PDF validation |
| test_app_features.py | 22 | Streamlit UI: editor, RTM, bugs, AI consent, persistence, regressions |
| test_audit_regressions.py | 20 | Earlier parser regressions |
| test_grill_models.py | 19 | Grill models, invariants, stale-state loading |
| test_formatting.py | 19 | Markdown escaping (BUG-002) |
| test_id_mapping.py | 18 | Requirement IDs |
| test_test_design.py | 18 | BVA, EP, decision tables |
| test_ai_analysis.py | 15 | AI config, consent, quote verification, error mapping (fake client) |
| test_exports.py | 14 | Jira / TestRail / RTM CSV, Markdown report, link integrity, CSV injection |
| test_app.py | 12 | Core UI flows |
| test_grill_inputs.py | 11 | Labeled-draft parser |
| test_quality.py | 10 | Quality score |
| test_grill_ai_ui.py | 10 | Grill AI panel: consent per request, labels, errors, translations |
| test_storage.py | 9 | Persistence and storage modes (BUG-001) |
| test_security.py | 9 | Secrets, network isolation, hostile input |
| test_models.py | 8 | Data models, `Source.USER` backward compatibility |
| test_localization.py | 8 | All tabs in EN / UK / RU |
| test_grill_security.py | 7 | Grill: no network without AI, key not in session, input limits (BUG-008), CSV / Markdown injection |
| test_bug_reports.py | 7 | Bug report generation |
| test_rtm_dashboard.py | 7 | RTM, coverage, dashboard, filters |
| test_test_generator.py | 7 | Draft test cases |
| test_release.py | 7 | Version, required files, dependency bounds, docs ↔ tests |
| **Total** | **1211** | |

## 3. Static analysis and security

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | All checks passed |
| Types | `mypy` | No issues in 28 source files |
| Dependencies (runtime + AI) | `pip-audit -r requirements-ai.txt` | No known vulnerabilities |
| Dependencies (dev) | `pip-audit -r requirements-dev.txt` | No known vulnerabilities |
| Static security scan | `bandit -r src app.py grill_ui.py` (ad hoc, not in CI) | 0 high, 0 medium; 14 low, all B101 (`assert` used for type narrowing after explicit checks) |
| Secrets in git history | `git log -p --all` searched for key patterns | None found |
| AI SDK compatibility | `anthropic` 1.13.0: `messages.parse` signature and offline `transform_schema` of all three response models (no network call) | All arguments accepted; schemas built |
| App start without AI | `streamlit run app.py --server.headless true` with `AI_PROVIDER=none`, then `/_stcore/health` | `ok`, no errors in the log |
| CI workflow | jobs `lint`, `test` (3.11, 3.12), `security` | Green on GitHub (Python 3.11 and 3.12, lint, audit) for commit `a962e6e`, the full 1.1.0 code |

## 4. Manual results

| Test case | Result | Notes |
|---|---|---|
| TC-016, TC-019, TC-020, TC-021 | Pass (v1.0.0) | Executed for 1.0.0 in a browser preview; not re-executed for 1.1.0 |
| TC-023 … TC-030 (Grill Mode) | Not executed | Covered by the automated tests listed in TEST_CASES.md; manual browser run pending |
| All other manual cases | Not executed | As for 1.0.0 |

## 5. Defects

8 defects found (7 for 1.0.0, 1 for 1.1.0), 8 fixed, 0 open. Details:
[BUG_REPORTS.md](BUG_REPORTS.md).

| Severity | Found | Fixed | Open |
|---|---:|---:|---:|
| Critical | 1 | 1 | 0 |
| High | 2 | 2 | 0 |
| Medium | 2 | 2 | 0 |
| Low | 3 | 3 | 0 |

## 6. Not tested

| Area | Reason |
|---|---|
| Grill Mode in a real browser | Only Streamlit `AppTest` (headless) and a server smoke start were used; the Markdown download was checked as content, not as a browser download |
| Live AI API call (analysis and Grill) | No API key used; AI is tested with a fake client and offline SDK checks |
| Streamlit Community Cloud | Not deployed |
| Real Jira / TestRail import of Grill-added items | No test instances; CSV columns are the same as for other items |
| Firefox, Safari, Windows, mobile devices | Not available |
| Accessibility (screen readers, keyboard-only) | Not in scope for this release |
| Performance with 500 requirements in Grill Mode | Not measured |

## 7. Conclusion

All automated checks pass in three environments and no known defects are
open. The exit criteria in the test plan are **met for automated testing**.
Before publishing, the maintainer should run the Grill Mode manual cases
(TC-023 … TC-030) in a browser, and complete
[../RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md).
