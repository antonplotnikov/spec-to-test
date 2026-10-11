# Test Plan — Spec-to-Test v1.1.0

| Field | Value |
|---|---|
| Product | Spec-to-Test (Streamlit web app) |
| Version under test | 1.1.0 (1.0.0 scope plus Grill Mode) |
| Document version | 1.1 — 2026-10-11 (Grill Mode added: F16–F19) |
| Author | Project maintainer |
| Related documents | [TEST_CASES.md](TEST_CASES.md), [RTM.md](RTM.md), [BUG_REPORTS.md](BUG_REPORTS.md), [TEST_SUMMARY_REPORT.md](TEST_SUMMARY_REPORT.md) |

## 1. Purpose

Describe how Spec-to-Test v1.1.0 is tested before release (v1.0.0 scope plus Grill Mode):
what is in scope, which levels and types of testing are used, the environments,
entry/exit criteria, and risks.

## 2. Scope

### In scope

| ID | Feature | Product requirements |
|---|---|---|
| F1 | Input: paste text, upload TXT/MD/PDF, validation | PR-01, PR-02 |
| F2 | Requirement extraction (IDs, lists, headings, tables) | PR-03 |
| F3 | Rule-based analysis (5 finding types, EN/UK/RU) | PR-04 |
| F4 | Quality score 0–100 with breakdown | PR-05 |
| F5 | Test case generation and editor, review workflow | PR-06, PR-07 |
| F6 | Test design: BVA, EP, decision tables | PR-08 |
| F7 | Bug reports | PR-09 |
| F8 | RTM and coverage | PR-10 |
| F9 | QA dashboard and filters | PR-11 |
| F10 | Exports: Jira, TestRail, RTM CSV, Markdown | PR-12 |
| F11 | Optional AI analysis with consent | PR-13 |
| F12 | Persistence and storage modes | PR-14 |
| F13 | Localization EN / UK / RU | PR-15 |
| F14 | Security: untrusted input, escaping, secrets | PR-16 |
| F15 | Responsive layout | PR-17 |
| F16 | Grill Mode workflows: requirements, test case, bug report, QA review; interview and draft review | PR-18 |
| F17 | Grill Mode trust: provenance, no invented facts, review levels, explicit confirmation | PR-19 |
| F18 | Grill Mode optional AI: per-request consent, AI never blocking or essential | PR-20 |
| F19 | Grill Mode results in the workspace, RTM, coverage, exports; opt-in resolved findings | PR-21 |

### Out of scope

- Accuracy of the keyword rules beyond the reference specification
  (`tests/fixtures/reference_spec.md`) — rules are documented heuristics.
- Quality of live LLM output (non-deterministic; depends on the provider).
- Performance/load testing of Streamlit Community Cloud infrastructure.
- Actual import into Jira Cloud / TestRail instances (format is verified;
  import is a manual release step).

## 3. Test approach

| Level / type | How | Tooling |
|---|---|---|
| Unit | Pure functions: parser, rules, quality, test design, exports, storage, formatting | pytest |
| Integration | Parser → rules → workspace → RTM → exports; AI module with a fake client | pytest |
| UI (component) | Full app script driven headlessly: clicks, forms, tabs, languages | Streamlit `AppTest` |
| State machine (Grill) | Valid and invalid transitions, stale revisions, back / skip / edit / cancel, confirmation | pytest |
| Regression | One test per fixed bug (see BUG_REPORTS.md) | pytest |
| Localization | Every tab rendered in EN/UK/RU; no raw keys, no English leftovers | pytest + AppTest |
| Security | No secrets in repo, no network in tests, hostile input, CSV injection, Markdown injection | pytest, pip-audit |
| Static analysis | Lint and type checks | ruff, mypy |
| Manual exploratory / UI | Layout, readability, responsive behaviour, real browser | Browser |
| Release | Version consistency, required files, dependency audit | pytest, pip-audit, CI |

Test design techniques used: equivalence partitioning and boundary values
(file size, PDF pages, text length, numeric limits), decision tables
(consent × configuration for AI; requirement link × severity for Grill bug
hand-over), state transitions (Draft → Reviewed → Approved; coverage status;
Grill workflow steps), error guessing (malformed files, hostile text,
oversized answers, double clicks from an outdated page).

## 4. Environments

| Environment | Details |
|---|---|
| Local | macOS, Python 3.11, Streamlit 1.65, Chromium-based browser preview |
| CI | GitHub Actions, ubuntu-latest, Python 3.11 and 3.12 |
| Staging / production | Streamlit Community Cloud (after deployment) |

## 5. Entry and exit criteria

**Entry:** code complete for 1.1.0; dependencies install from
`requirements-dev.txt`; example data available (`examples/password_reset.md`).

**Exit:**
- 100 % of automated tests pass on Python 3.11 locally and in CI.
- ruff and mypy report no issues; pip-audit reports no known vulnerabilities.
- No open bug with severity Critical or High.
- All manual test cases in TEST_CASES.md executed, or explicitly listed as not
  executed with a reason in the Test Summary Report.

## 6. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Users' documents exposed on shared hosting | High | `session` storage mode by default on Streamlit Cloud; regression tests |
| Documents sent to an AI provider without consent | High | Consent enforced in code and UI, per run; tests with fake client |
| User text rendered as Markdown (link/image injection) | Medium | Escaping helper + regression tests |
| False positives/negatives in rules | Medium | Reference spec tests; findings labelled as hints |
| Untranslated or inconsistent UI text | Medium | Translation completeness tests + UI language sweep |
| Dependency vulnerabilities | Medium | Lower bounds + pip-audit in CI |
| Grill presents an assumption or AI suggestion as a confirmed fact | High | Provenance on every value; assumptions never resolve findings; AI output never blocking or essential; tests |
| Grill result added to the workspace twice or linked to an invented requirement | Medium | Hand-over only for real requirement IDs; duplicate checks; tests |
| Unbounded Grill input fills memory or the save file | Low | 100,000-character limit per answer and field; tests |
| Python 3.12 differences | Low | CI matrix (not verified locally) |

## 7. Deliverables

Test plan (this document), test cases, bug reports, RTM, test summary report,
automated test suite (`tests/`), CI workflow.

## 8. Defect management

Severity: **Critical** (data loss/exposure, app unusable), **High** (main
feature broken, no workaround), **Medium** (feature impaired, workaround
exists), **Low** (cosmetic). Each fixed defect gets a regression test that
fails without the fix.
