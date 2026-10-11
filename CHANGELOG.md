# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
  (tracked separately as P0-1; not fixed here).

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
