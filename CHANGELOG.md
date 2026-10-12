# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- LLM providers: Claude (Anthropic), OpenAI and local Ollama models behind one
  structured-output call (`spec_to_test.llm`). `AI_PROVIDER` picks the default
  (`anthropic`/`claude`, `openai`, `ollama`); every provider with credentials
  (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` + optional `OPENAI_BASE_URL`,
  `OLLAMA_HOST`) can be chosen per browser session in the new sidebar
  **AI settings**, with the model (`AI_MODEL`, `ANTHROPIC_MODEL`,
  `OPENAI_MODEL`, `OLLAMA_MODEL`), a **Use AI features** switch (off = the
  rule-based mode, nothing sent) and a **Test connection** button.
  `AI_LOCK_SETTINGS=true` makes the settings read-only on shared deployments.
  Keys are read only from the environment, Streamlit secrets or `.env`, never
  shown or logged. Ollama is called over plain HTTP (no SDK). New error codes
  `model_not_found` and `unsupported_provider`. `requirements-ai.txt` now also
  installs `openai`. Automation keeps using Claude whichever provider is
  selected.
- Grill Mode AI interviewer: after the built-in questions, the model asks
  follow-up questions one at a time, each with why it matters and an
  importance. It receives every earlier question with the reply and its
  status (answered / assumed / unknown / skipped), must not repeat itself
  (exact and near-duplicate questions are also filtered in code), never asks
  again about unknown fields, and stops when nothing important is left or
  after 12 questions. Consent is one tick per Grill session; a provider
  failure is shown once and the interview continues without AI.
- Grill Mode final report (`grill/report.py`): clarified requirements
  (verbatim, with confirmed and assumed clarifications and open questions),
  confirmed facts, assumptions and unknowns kept apart, and suggested test
  cases — rule-based from the linked requirements, plus optional AI ideas that
  are kept only when their expected result quotes a requirement or the
  author's answer (the basis label is decided in code). Included in the
  existing Markdown download.
- Automation tab: an Approved test case becomes a validated Playwright
  TypeScript test. Claude (opt-in per run) explores the staging UI through the
  Playwright MCP server and submits a structured script; Spec-to-Test renders
  it with role/label/test-id locators and `TC`/`REQ` tags, runs it in a
  sandboxed Chromium, and shows the JSON report, screenshots and trace. One
  repair attempt is allowed and may not change assertions; every assertion
  must quote the approved expected result or requirement. Jobs run in the
  background (queued → planning → exploring → generating → validating →
  passed / failed / blocked / cancelled) with live progress and Cancel.
  Approved tests are stored in the workspace (`Workspace.automated_tests`,
  optional field; older saves load unchanged) and export as a Playwright
  project. Security: staging allowlist, SSRF checks (private networks opt-in,
  metadata addresses never), DNS pinning and a dead-proxy egress lock in the
  browser, reduced MCP tool set, destructive-action guard, secrets by name
  with masking in logs/reports/traces, minimal child environment, resource
  limits and timeouts. New `requirements-automation.txt`,
  `automation/runner` (pinned `@playwright/test` 1.63.0, `@playwright/mcp`
  0.0.80), `Dockerfile` and `docker-compose.yml`, and a CI job with
  real-browser end-to-end tests.
  The MCP handshake has a 60 s start-up timeout (a silent server blocks the
  job instead of hanging it), the activity log shows when the browser is up,
  and private sandbox folders left by a force-quit server are removed on the
  next start.
- macOS app: `macos/build_app.sh` builds `Spec-to-Test.app`, which runs the
  app in its own native window (pywebview) with its own Dock icon. The server
  runs on `127.0.0.1` only and stops when the window closes (or the app
  crashes). Work is saved on disk in
  `~/Library/Application Support/Spec-to-Test/data`. New
  `requirements-desktop.txt` (app + pywebview), audited in CI.
- macOS app settings file `~/Library/Application Support/Spec-to-Test/settings.env`
  (mode 600, created with commented examples; only `AI_*`, `ANTHROPIC_API_KEY`
  and `AUTOMATION_*` are read; the process environment wins). With Node.js
  installed, the build sets up the Automation tab (Python extras, Playwright
  toolchain) and records the `node` path (`AUTOMATION_NODE`), because apps
  opened from Finder get a minimal `PATH`.

### Security
- Storage isolation (P0-1, BUG-010): `session` is now the default storage mode
  in every environment. Previously only a path check (`/mount/src`) made
  Streamlit Cloud use it, so any other shared deployment (Docker, VM, another
  host, a different mount path) silently saved documents to one shared folder
  and showed the last visitor's workspace to new visitors. In `session` mode
  nothing is read from or written to disk; edits survive reruns, screen
  switches and re-analyzing the same document within the session, and a new
  session starts clean (old files on disk are ignored).
- Only the exact value `SPEC_TO_TEST_STORAGE=local` (case and surrounding
  spaces ignored) enables disk storage. Unknown and empty values mean
  `session`. The setting is read from the environment / Streamlit secrets
  only; a `.env` file does not switch the mode. Cloud detection by path was
  removed.

### Changed
- AI configuration moved to `spec_to_test.llm`; `spec_to_test.ai_analysis`
  re-exports the old names (`AIConfig`, `AIError`, `load_config`,
  `request_structured`, ...), so existing imports keep working. AI error
  messages no longer assume Claude, and `NotFoundError` from an SDK now shows
  "unknown model" instead of a generic failure. `docker-compose.yml` no longer
  forces `AI_MODEL=claude-opus-5-5` (empty = the provider's default).
- **Behavior change for local users:** work is no longer saved to
  `.spec_to_test_data/` unless you set `SPEC_TO_TEST_STORAGE=local`
  (for example `SPEC_TO_TEST_STORAGE=local streamlit run app.py`).
- Re-analyzing the same document in one session keeps that session's edits
  (as saved files did before in `local` mode). In `local` mode it reloads the
  saved file, so newer edits from another tab are not overwritten.

### Fixed
- Grill Mode: a confirmed test case or bug report could be added to a
  different document that had a requirement with the same ID (for example
  `REQ-2` in two documents), because only the ID was compared. A Grill
  session already stored the requirements it was started on; the new check
  compares that snapshot with the analyzed document, and **Add to the
  workspace** works only when the requirements (IDs and texts) are identical.
  Otherwise nothing is added and the button is disabled with a translated
  reason. In test case and bug report sessions (not Requirements Grill) that
  are not cancelled, a warning is shown while the session is open (tested on the
  question, review and final steps) as soon as the analyzed document differs
  from the session's, or when a document is analyzed after a
  session that was started without one. Answers are kept, and the confirmed
  result can still be downloaded as Markdown. See BUG-009 in
  `docs/qa/BUG_REPORTS.md`.

### Known limitations
- The Grill document check compares requirement IDs and texts. Two different
  documents whose requirements are all identical are not told apart, and a
  slightly edited re-analysis of the same document is treated as another
  document (use the Markdown download or start a new session).
- Resolving findings (Requirements Grill) is unchanged: it still requires each
  requirement of the session to exist in the workspace with the same text, and
  does not compare the whole document.
- This change does not address shared local storage between users
  (fixed separately, see Security above).

## [1.1.0] - 2026-10-11

### Added
- **Grill Mode** (sidebar → Mode): an interactive QA interviewer with four
  workflows — clarify requirements, build or improve a test case, build or
  improve a bug report, and QA review of an existing artifact.
  - Explicit workflow steps with validated transitions; stale or double clicks
    are rejected. Nothing is finalized without explicit confirmation.
  - Deterministic question banks; answers can be confirmed, kept as
    assumptions, marked unknown, or skipped (non-essential questions only).
  - Provenance for every draft value (source, confirmed, assumption,
    AI suggestion, unknown); source requirements are never rewritten.
  - Deterministic review with blocking / warning / suggestion levels, reusing
    the rule engine (vague wording, limits vs. the linked requirement,
    test-design consistency, traceability, placeholders, duplicates).
  - Labeled-draft parser for pasted test cases and bug reports.
  - Optional AI assistant: extra questions and an AI review, with per-request
    consent; AI questions are never essential and AI findings never block.
  - Confirmed results can be downloaded as Markdown (origins, assumptions
    and open questions kept), and handed to the analyzed workspace: a test
    case linked to a requirement becomes a Draft test case (RTM, coverage,
    Jira / TestRail / Markdown exports); a bug report with a requirement and
    a severity becomes a bug report (Jira bug CSV). Nothing is added twice.
  - Opt-in, per clarification: findings answered by a confirmed (not
    assumed) clarification can be marked resolved.
  - Full EN / UK / RU translations.
- `Source.USER` for values written or confirmed by a person.

### Changed
- `ai_analysis.request_structured()` is the shared, consent-agnostic model
  call used by the AI analysis tab and Grill Mode (behavior unchanged).
- Rule findings can now be marked resolved (through a confirmed Grill Mode
  clarification only).

### Security
- Grill Mode answers and draft fields are limited to the same 100,000
  characters as an analyzed document, so one session cannot grow without
  bound or fill the save file.

[Unreleased]: https://github.com/antonplotnikov/spec-to-test/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/antonplotnikov/spec-to-test/releases/tag/v1.1.0

## [1.0.0] - 2026-10-11

First public release.

### Added
- Markdown QA report export (summary, RTM, test cases, bug reports).
- Storage modes: `local` (save to disk) and `session` (browser session only).
  `session` is the default on Streamlit Community Cloud.
- Streamlit secrets support for AI and storage settings
  (`.streamlit/secrets.toml.example`).
- Loading indicator while analyzing; app version in the sidebar.
- Localization test sweep across all tabs in EN / UK / RU.
- CI: lint (ruff), type check (mypy), tests on Python 3.11 and 3.12,
  dependency audit (pip-audit), JUnit test report artifact.
- LICENSE (MIT), SECURITY.md, deployment guide, release checklist,
  and QA documentation (test plan, test cases, bug reports, RTM, summary report).

### Fixed
- User text in tables, warnings, and headings was rendered as Markdown
  (links, emphasis, images). It is now escaped and shown exactly as written.
- On shared hosting, the last analyzed document could be restored for a
  different visitor. Shared deployments no longer write or restore documents.
- AI consent stayed ticked after a run and after analyzing a new document;
  it is now required again for every run.
- A bug report created from an AI suggestion did not appear in the Bug reports
  tab until the next interaction.
- Confirmation and "could not save" messages could be lost because the page
  reran immediately after showing them.
- Dependency lower bounds allowed `pypdf` and `streamlit` versions with known
  security advisories (now `pypdf>=6.19`, `streamlit>=1.65`).
- Long text was cut off in result tables on large screens; tables now wrap
  text and the layout uses the full screen width.

### Changed
- `pandas` is declared explicitly (it was used but only installed indirectly).
- Removed unused code (`quality.average_score`, `Workspace.generated_language`).
- Project-level ruff and mypy configuration in `pyproject.toml`.

## [0.2.0] - 2026-10-11

### Added
- Quality score, test case editor with Draft / Reviewed / Approved, test design
  (BVA, equivalence partitioning, decision tables), bug reports, RTM, QA
  dashboard, Jira / TestRail / RTM CSV exports, local persistence, optional AI
  analysis with consent.

## [0.1.0] - 2026-10-10

### Added
- Requirement parsing (text, TXT, MD, PDF), rule-based analysis, EN / UK / RU
  interface.

[1.0.0]: https://github.com/antonplotnikov/spec-to-test/releases/tag/v1.0.0
[0.2.0]: https://github.com/antonplotnikov/spec-to-test/releases/tag/v0.2.0
[0.1.0]: https://github.com/antonplotnikov/spec-to-test/releases/tag/v0.1.0
