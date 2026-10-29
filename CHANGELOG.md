# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Audit fixes before the commit

#### Fixed
- Two saves of one document could both pass the check, and the second one then replaced the first silently (lost edit). Saves now check and write under a file lock; the second save reports a conflict.
- Test runs, bug reports and QA Agent memory are changed as transactions: each change re-reads the latest saved file under its lock. Results recorded from an older copy no longer erase a result another tab saved; run IDs and bug report IDs are chosen under the lock.
- A saved file that cannot be read (damaged, or of another format) is never overwritten. Entries a newer version wrote, and unknown fields of saved runs, bug reports and memory entries, are kept when the file is saved again.
- AI limits are checked before a request is sent and count the request's worst case: parallel requests cannot overshoot a limit together, and a request whose usage is not reported keeps its worst case in the check.
- The AI budget is shared by the whole running app, not by one browser session: a new tab or a page reload no longer starts a new budget. The counters are kept in memory and restart with the app.
- A deleted test case's ID is not handed out again while a test run still refers to it, so an old result is never attributed to a new test case.

#### Changed
- Conflict copies are named by the digest of their content (`<hash>.unsaved-<digest>.json`).

### RTM and dashboard: coverage levels

#### Changed
- The RTM and dashboard keep three coverage levels apart: **Design** (a
  requirement has a test case, drafts included), **Review** (a test case is
  Approved) and **Execution**, which is shown as "Not tracked": no test runs are
  recorded yet, so an Approved test case is never counted as an executed test.
- Status labels follow the review meaning: "Covered" is now "Approved",
  "Partially covered" is "Not approved yet", "Not covered" is "No test cases".
  The stored values and filters are unchanged. The dashboard's "Coverage" is now
  "Review coverage". Exports use the same labels.

### Test case quality score and save conflicts

#### Added
- Test case quality score 0–100 from the existing critic: 100 minus the points of each problem found (placeholder step −20, conflicting expectation −25, and so on); unknown items cost nothing. Shown in the test case editor, with the points of each problem, and as an average per requirement in the RTM.

#### Fixed
- Local mode: when a saved document changed elsewhere (another tab or the QA on-change run), the app used to replace the user's unsaved edit with the saved version without saying so. The edit now stays in the session and in the project's `conflicts` folder, and the user chooses "Save my version over it" or "Load the saved version". Nothing is overwritten without that choice; a replaced saved file is kept in `conflicts`.
- Saved documents are checked and written under a file lock (`spec_to_test/filelock.py`: `flock` on POSIX, `msvcrt` on Windows, released by the OS if the app crashes). Two saves of one document can no longer both pass the check: the second one reports a conflict instead of silently replacing the first. A first save no longer replaces a file that another writer created in the meantime.
- Conflict copies are named by the digest of their content, so a different unsaved edit never replaces an earlier copy.
- The saved file format is unchanged; old saves open as before.

### Possible duplicate requirements

#### Added
- Requirement Analyzer: requirements of one document whose wording is the same (after ignoring case, punctuation and spacing) or nearly the same (similarity of 0.9 or more) are listed on the Findings tab as questions for the BA/PO, with their IDs. Nothing is merged, and quality scores do not change.

### Impact decisions

#### Added
- Analysis page: each changed requirement can be confirmed as **Accepted**, **Rejected** or **Deferred**, with an optional comment. A decision records your choice only: it changes no test case, and statuses are still changed on the Test Cases page.
- A decision stays current only while what it was made from is unchanged (the wording of the requirement in both versions, the affected test cases and their review status, and the whole set of recommendations). Otherwise it shows as **Stale: check again**, and a new decision supersedes it.
- Decisions are kept in `impact_decisions.json` in the project's folder (`local` mode only), with stable IDs (`DEC-001`, never reused). Documents keep their format. A file that cannot be read is never overwritten.
- The CSV and Markdown Impact exports get a Decision column when decisions are shown.
- A requirement without an ID in the document is marked: its ID is its position, not a stable identity.

### Change impact recommendations

#### Added
- Impact analysis suggests an action per changed requirement: **Add** (a new requirement), **Update** (a changed requirement with draft test cases), **Review** (a changed requirement with an Approved test case, or an unmatched one), **Remove** (a removed requirement), and **Keep** (unchanged requirements, counted). Suggestions only: no test case status changes.
- Regression hint: the changed requirements that have Approved test cases are marked for a regression run.
- Impact Report download in two formats: Markdown (the report, with the note that nothing is applied) and CSV (the recommendations).

### Possible duplicate bug reports

#### Added
- Bug Reports page: before a draft or an opened report is saved, saved reports that may describe the same bug are listed (up to three, with a similarity percentage). It is a question for the reporter; nothing is merged.

### Test case search and bulk actions

#### Added
- Test Cases page: a search box (every word must match the ID, title, requirement, preconditions, steps or expected result) and a review-status filter. Both narrow the table and the case selector.
- Bulk actions on chosen test cases: set their review status (Draft, Reviewed or Approved) in one step, or delete them. Deleting needs a confirmation checkbox first. Results of test runs that name deleted cases are kept and shown as removed.

### Manual test execution

#### Added
- Test Cases page, new **Test runs** tab: start a run from the Smoke, Regression or Full suite, with a name, environment and build. Each run has a stable ID (RUN-001, never reused), a date and one result per test case: Passed, Failed, Blocked or Not run, with an optional comment and Bug ID.
- Run figures: progress, pass rate (Passed / (Passed + Failed)), Passed, Failed, Blocked and Not run. Run history for the document, and a CSV download of a run's results.
- Runs are stored in their own file, `test_runs.json`, in the project's folder (`local` mode only; in `session` mode they live in the browser session). Existing documents and their files are not changed. Every change is applied to the latest saved file under its lock, a run ID is chosen there (so two tabs cannot take the same ID), and a file that cannot be read is never overwritten.
- Test case IDs that a run still refers to are not handed out again when a new test case is added or generated.
- RTM: Execution coverage now has a value once a run of the document is recorded: the share of requirements with a Passed or Failed result. With no runs it still reads "Not tracked".

#### Notes
- Screenshots are not attached to results yet; a Bug ID is recorded as text.

### AI usage, cost and limits

#### Added
- Every AI answer from Anthropic, OpenAI, an OpenAI-compatible server and Ollama is counted: input and output tokens are taken from the provider's own response. A count the provider does not report is shown as unknown, never as zero.
- Sidebar: the requests, tokens (input and output) and estimated cost of the running app, for all its browser sessions. The counters are kept in memory and start from zero when the app restarts.
- Cost uses prices you set in `AI_PRICES` (USD per million tokens, per provider and model). No price is built in, so a model without one shows an unknown cost, never 0.
- App-wide limits `AI_TOKEN_LIMIT` and `AI_COST_LIMIT_USD`: a warning from 80%. Before a request is sent, it reserves its worst case (estimated input tokens plus the output limit it asks for), so parallel requests cannot overshoot a limit together. A request whose usage the provider does not report keeps its worst case in the limit check. A cost limit counts priced requests only; the token limit covers every model.
- Settings that cannot be read (a non-number limit, malformed `AI_PRICES`) are left off and flagged in the sidebar.

#### Notes
- A request that fails before the provider answers (connection, authorization) is not counted. An answer that cannot be used (truncated, refused, malformed) is counted at its worst case, because its tokens were spent. The connection test (the Test button in Settings) sends a real request and is counted.

### Bug Report Generator

#### Added
- **Bug Reports** page: a product bug described in free text (English,
  Ukrainian or Russian; prose or labeled parts such as "Steps:", "Expected
  result:", "Шаги:", Markdown headings) becomes a structured report with Title,
  What / Where / When, Preconditions, Steps to Reproduce, Actual Result,
  Expected Result, Environment, Severity / Priority and Missing Information.
- Rule-based and local (no AI): every value is text from the description.
  Fields with no matching text stay empty and show "Needs clarification"; a
  marker typed into a field is saved as empty. Clauses no rule recognises are
  kept in "Not used in any field", and the original description is kept.
- Severity and priority are preliminary: stated by the reporter, or suggested
  from cue words in the actual result (crash, data loss, server error or a
  failure in payment / checkout / login → High; cosmetic → Low; other failures
  → Medium), with the words that triggered the rule. Priority follows severity,
  one level lower when the problem does not happen every time.
- Missing Information lists the questions still open (where, when, frequency,
  steps, expected result, platform, app version, evidence, ...) and follows
  the edits.
- Drafts are saved only on Save; saved reports belong to the project (session
  or `SPEC_TO_TEST_STORAGE=local`, `bug_reports.json`), can be reopened,
  edited, deleted after a confirmation, and downloaded as Markdown one by one
  or all together. Deleting a project deletes its bug reports.

- Optional **Generate with Claude Code** (`SPEC_TO_TEST_CLAUDE_CODE=1`): for
  personal use, the report is written by Claude through the local Claude Code
  CLI and the user's own Claude login (no API key). The login must be a
  claude.ai login (`claude auth status`); API-key and cloud variables are
  removed from the CLI's environment; the model gets no tools, MCP, hooks,
  CLAUDE.md or memory and runs one turn in an empty temporary folder. Every
  field must be backed by quotes from the description; unsupported values
  (and invented numbers, URLs or platforms) are removed. Consent is asked
  each time; not signed in, usage limit, rate limit and timeout errors are
  shown, and the rule-based generator stays the default.
- Usage of each Claude Code generation: tokens (input / output / cache, model,
  time) from the CLI's result, and the plan's session and weekly limits before
  and after it (percent, change, reset time) from the local `/usage` command,
  which makes no model request. Saved with the report, listed in a Tokens
  column; "Check plan limits" shows the current percentages. A failed request
  still reports the tokens it used.

## [1.2.0] - 2026-10-16

### QA Agent — generate missing test cases

#### Added
- **Generate missing test cases** on the QA Agent page (mode "QA task"): when
  the result names requirements without test cases (Traceability) or with
  scenarios no test case exercises yet (Scenario Coverage), one click adds the
  missing cases, made by the same rule-based generator as the Test cases page
  (no AI). A requirement without test cases gets every case the generator
  makes; otherwise only cases for the missing scenario kinds are added, one per
  kind. A case with the title, or the type, steps and expected result, of an
  existing test case of the requirement is never added, so a second click adds
  nothing. New cases are Draft and linked to their requirement; existing and
  Approved test cases are not changed.
- Where an open finding leaves the requirement without a checkable result (a
  contradiction, vague wording, no stated result, a limit without a value), the
  new case's expected result reads "Not defined yet: … needs clarification
  first" instead of a quote, and keeps the clarification questions.
- After the click the page lists the new cases and, per requirement, the
  coverage after them: test cases before → after, scenarios without a test
  case before → after, the Approved coverage, and the scenario kinds the
  generator has no case for (permissions, state transitions, recovery, a
  negative case without numbers), to be written by hand.

### Generated test cases — the user's action in positive steps

#### Changed
- For a user-capability requirement ("The user can …", "Users are able to …",
  "Пользователь может …", "Користувач може …") the positive case's action step
  quotes the action verbatim: `Perform the action stated in REQ-1: “request a
  password reset from the login page by entering their email address”.`
  Before, it read `Perform the action described in the requirement.` Other
  actors, negations and conditions before the actor keep the generic step.

### TestRail export — self-contained test cases

#### Changed
- The TestRail CSV Preconditions now start with the linked requirement's
  wording (`Requirement REQ-3: The reset link expires after 30 minutes.`) and
  end with the case's open questions (`Open question: …`). Before, a case
  imported into TestRail showed only the requirement ID, and open questions
  (e.g. a conflict with another requirement) were dropped, though the Jira
  export already had both.

### QA task report — what each problem refers to

#### Added
- Under every problem and unknown of the QA task result (QA Agent page, mode
  "QA task", and `on_change` `report.md`) the requirements it names are quoted
  with their line in the document, and the test cases with their review status
  and requirement, e.g. both sides of a possible contradiction. At most 5 per
  line ("…and N more"); long texts are shortened. Change Impact lines are not
  quoted (their IDs belong to the previous version). Detection, the eval and
  its gold are unchanged.

### QA Agent — AI mode

#### Added
- `on_change --ai`: the `AI_PROVIDER` model (Claude, OpenAI, an
  OpenAI-compatible server including local models, or Ollama) reviews the
  document, its test cases and the Change Impact; its checked problems,
  questions and recommendations are one more step ("AI review") of the usual
  report. Replies that do not match the schema are errors; items naming no
  known ID or quoting text that is not in the document are rejected.
- `StructuredProvider` interface and `ConfiguredProvider` / `load_provider`
  in `spec_to_test.llm.providers`.
- Without configuration, or when the request fails, the report and the command
  line say why; the rule-based result is kept. Without `--ai` nothing changes.
- QA Agent page, mode "QA task": an "Add AI review" consent box (off by
  default, cleared after every run) adds the same AI review to the result,
  using the provider and model of the sidebar AI settings; failures are shown
  with their reason in the conclusions.

### QA Agent — shorter Full check report

#### Changed
- Each problem is reported once: the mirror line of a conflicting pair is
  dropped, and the same remark of one check on several IDs is one line naming
  every ID (`Item.refs`); type, IDs and the check it came from are kept.
- "Not Approved" lines of Coverage, Traceability and Suites (and their
  "approve" recommendations) are no longer problems: one "Review status" line
  (`AgentResult.approval`) names the checks and the requirements concerned.
- Coverage reports a scenario that no test case covers, not even a Draft, as
  its own problem ("no test case at all, not even a Draft").
- On the five QA Agent eval documents: 172 → 42 problem lines, 218 → 73 report
  lines, 3 → 0 duplicates, 93 → 0 "not Approved" lines among the problems;
  precision and recall unchanged.

### Missing expected results

#### Fixed
- The QA task agent's requirements step also reports the rule engine's
  "missing expected result" findings ("The user can change the password").
  Before, Full check showed them only as Unknowns of the Critic and Coverage.
- "Must be able to delete their account", "може видалити", "может удалить":
  the verb after "can / able to" is the user's action, not its result, so the
  requirement is reported as having no expected result. "Can see",
  "can receive" and a result stated elsewhere in the sentence still count.
- QA Agent eval: `missing_expected_result` recall 0/11 → 10/11, precision 1.00.

### Test design — time and size limits

#### Fixed
- "Within 60 seconds", "протягом / в течение 5 минут" are deadlines: 59 and
  60 s are in time, 61 s too late (were "not specified" around an equality).
- "Expires after 30 minutes", "30 minutes after", "через 15 хвилин" are delays:
  at 29 the change has not happened, at 31 it has; "after 5 attempts" happens
  on the 5th attempt, "after more than 5 attempts" on the 6th.
- "Locked for 15 minutes" is a duration: still in effect at 14, over at 16.
- "Не повинен перевищувати", "не должен превышать", "cannot exceed" are
  inclusive upper limits (were read as "more than" and then as equality).
- Coarse data limits are probed in a smaller unit: "at most 1 MB" is tested
  with 1023 / 1024 / 1025 KB instead of 0 / 1 / 2 MB.
- "More than" / "less than" without a timing word stay exact values, as
  before: which side is valid depends on the sentence.

### QA Agent evaluation — boundary semantics

#### Changed
- A boundary problem of generated test cases with `expect` in the gold counts
  as resolved when the generated test cases give the expected outcomes; a
  correct `must_not` test case that changes is a regression (new thresholds:
  `recall.boundary_semantics` ≥ 1.0, `regressions` ≤ 0).

### QA Agent evaluation

#### Added
- `python -m spec_to_test.evaluation.qa_agent_eval`: rule-based evaluation of the
  QA task agent ("Full check") on five documents against a hand-written gold
  (`evaluation/qa_agent_gold.json`) of requirement and test case problems;
  precision and recall per problem kind and per trap (contradictions,
  within/after, numeric boundaries, error handling, template test cases);
  Unknowns are not counted as found, duplicates do not count twice, status
  lines are reported as noise; stops when the gold is stale (see
  docs/EVALUATION.md).
- `evaluation.runner.threshold_failures` checks thresholds over any metric totals.

### QA Agent — automation when a requirements document changes

#### Added
- `python -m spec_to_test.qa_agent.on_change`: runs the QA task agent once for a
  new version of a requirements document (from `--previous` or the project's
  saved versions), writes a Markdown/JSON report and a run journal
  (`journal.jsonl`), skips repeats with the same inputs (`--force` to rerun),
  allows one run per output folder, and changes project data only with
  `--project … --allow-write` (see docs/QA_AGENT.md).
- `storage.save_workspace(..., remember=False)` saves without changing the last
  opened document.

#### Fixed
- A saved document is no longer overwritten by an older copy: `save_workspace`
  raises `WorkspaceConflict` when the file changed since the copy was read, so a
  change applied with `--allow-write` is not lost when the app saves its open
  copy (the app shows the saved version and asks to repeat the last change).
- The on-change run lock older than 15 minutes is kept while the process it
  names still runs, and a run removes only its own lock.

### QA task agent — requirement findings

#### Added
- A "requirements analysis" step reports the rule engine's open findings
  stored with the document — possible contradictions (once per pair),
  ambiguous wording and missing error handling. Full check runs it first;
  tasks like "find contradictions", "check the requirements" or "is the
  document ready for testing?" (EN/UK/RU) run it alone.

### Test Case Critic — conflicting expectations

#### Added
- The Critic reports a test case that expects the opposite outcome to another
  test case for the same input value ("9 characters → accepted" vs
  "→ rejected") with the same preconditions, within one requirement or across
  requirements the analyzer reported as contradicting.
- The QA task agent does not propose (and `on_change --allow-write` therefore
  does not apply) an approval of such test cases; it names them instead.

### AI providers — local and OpenAI-compatible models

#### Added
- Provider `openai_compatible` (alias `compatible`) for self-hosted servers with an
  OpenAI-style `/chat/completions` API (LM Studio, vLLM, llama.cpp server,
  LocalAI): `OPENAI_COMPATIBLE_BASE_URL`, `OPENAI_COMPATIBLE_MODEL` (required, no
  default) and an optional `OPENAI_COMPATIBLE_API_KEY`. It sits next to the real
  OpenAI provider (both can be configured), needs no SDK (plain HTTP, like
  Ollama), never receives the OpenAI key or other `OPENAI_*` settings, and does
  not follow redirects. Replies are validated against the same Pydantic models;
  a `<think>` block or a Markdown fence around the JSON is accepted (also for Ollama).
- `AI_TIMEOUT`: seconds one AI request may take (default 300, clamped to 10–3600),
  for slow local models.
- Settings page: the compatible server's address and whether it uses a key;
  new problems *server address missing*, *model missing or invalid* and
  *key would be sent unencrypted*.

#### Changed
- A provider key is sent only over `https` or over `http` to this machine. An
  `OPENAI_BASE_URL` with plain `http` to another host together with
  `OPENAI_API_KEY` now makes the OpenAI provider unusable (*insecure_url*)
  instead of sending the key unencrypted.

### Autonomous QA — from a URL to bug reports

#### Added
- **Autonomous QA mode** on the QA Agent page (`qa_auto_ui.py`): enter an
  authorized URL and click *Start Autonomous QA*. The agent explores the site
  read-only (Playwright; GET only, no typing, clicking or submitting; destructive
  and sign-out links not opened; off-host redirects stopped), records every fact
  as evidence (`EV-…`), drafts requirements (`WEB-…`) labelled **Observed /
  Inferred / Unknown** with confidence, evidence and clarification questions,
  and generates positive, negative, validation and boundary test cases from them.
- **Review and approval**: approve, reject, defer or edit requirements and answer
  their questions (an answer makes an expectation testable and confirmed);
  approve cases (form-submitting cases need their own confirmation and a per-run
  permission). **Send to workspace** creates one document per session, so the
  approved requirements and cases appear in Requirements Analysis, Grill Mode,
  Test Cases, RTM, Dashboard and the manual QA plan, without duplicates on re-send.
- **Runs, triage and bug reports**: runs use the existing QA Agent service
  (destructive actions never allowed); results get a meaning — Defect,
  Uncertain expectation, Timeout, Environment, Security block; bug reports only
  for defects and uncertain expectations, with the website evidence attached and
  no root-cause claims. Interrupted discoveries and runs can be resumed.
- **Final report** with the traceability chain Website evidence → Requirement →
  Test case → Execution result → Bug report (Markdown, ZIP, session JSON).
- Optional **AI interpretation** of the evidence: validated candidates only
  (must cite existing evidence, always Inferred, confidence ≤ 60%, no automatic
  tests); page content is passed as untrusted data.
- Settings `QA_DISCOVERY_MAX_PAGES`, `QA_DISCOVERY_MAX_DEPTH`,
  `QA_DISCOVERY_TIMEOUT`, `QA_DISCOVERY_MAX_ELEMENTS`. Docs: `docs/AUTONOMOUS_QA.md`.

#### Changed
- QA plan cases may carry a `risk` (form submission); such cases run only when
  the run allows form submissions (new checkbox on Run and Retest). Existing
  plans and approvals are unaffected (the fingerprint only includes a set risk).
- Bug reports have an optional `classification`, shown in Markdown and CSV.
- The Demo Shop home page links to the dashboard, account page, `/broken` and
  `/go-elsewhere`, and the contact form's Name field has `maxlength=40`, so
  discovery finds them.

### QA Agent — plan, run and report browser tests

#### Added
- **QA Agent page** (`qa_agent_ui.py`, `spec_to_test.qa_agent`): an editable
  test plan built from the document's test cases and linked to requirement
  and test case IDs; per-case approval (a fingerprint, so any edit revokes it);
  execution of approved cases with Python Playwright in headless Chromium;
  Passed / Failed / Blocked / Not run results with screenshots, errors,
  observed page text and console errors; bug reports for failed cases; saved
  run history with retest of failed and blocked cases; QA report with
  requirement coverage (Markdown, ZIP with screenshots, JSON, CSV).
- **Step language** (`goto`, `fill`, `click`, `select`, `check`, `press`,
  `expect_text`, `expect_url`, …) interpreted by a fixed executor — no code
  is generated or evaluated. Concrete English test steps convert
  automatically; a case with any unreadable step gets no steps (never guessed).
- **Safety**: reuses the Automation allowlist, SSRF checks, DNS pinning,
  redaction and destructive-word list; additionally blocks loopback bypass of
  the dead proxy, aborts off-allowlist requests, checks every main-frame
  navigation including redirects, checks each clicked element's text for
  destructive words, withholds screenshots that would show a secret, and
  enforces per-step, per-navigation and per-run timeouts, case/step limits and
  one run at a time (`QA_*` settings).
- Optional **AI step proposals** for a case (consent per request; the model
  sees no secret values or page content; one invalid step rejects the whole
  proposal; approval still required).
- **CLI**: `python -m spec_to_test.qa_agent --plan … --authorized --approve-all`.
- **Demo Shop** (`examples/qa_demo/`): local stdlib web app with a deliberate
  bug, requirements and a plan that produces real Passed, Failed and Blocked
  results.
- `requirements-qa.txt`, `docs/QA_AGENT.md`, tests (`tests/test_qa_agent_*.py`),
  including real-browser tests and a CI job that installs Chromium.

#### Changed
- Navigation has a new **QA Agent** page between Test Cases and RTM.

### Grill Mode v2.1 — reactive questions, smarter rules, broader evaluation

#### Added
- **Reactive interview queue.** Open questions are recalculated after every
  answer, draft edit and finding status change. `GrillWorkflow.sync_settled`
  follows findings resolved or reopened in the analyzed document during an
  interview (the page calls it on every render; no change = no new revision):
  a resolved finding's open question leaves the queue, a reopened one returns
  under the same ID (asked at once if the interview had run out), a shown
  review is redone and a pending confirmation withdrawn. Answers, question IDs
  and the question on screen are kept unless it was the one resolved.
- **Answered elsewhere.** `planner.covered_questions`: a confirmed or assumed
  clarification that states a limit settles the missing-limit question of the
  same requirement; one that names the failure path (negation-aware) settles
  its error-handling question; a number settles amount/speed vagueness.
- **Retired questions keep their history.** `GrillSession.retired` (schema 3,
  older sessions migrate with none) keeps each question that left the queue
  with its reason (`settled`, `answered_elsewhere`, `duplicate`, `obsolete`)
  and the covering question; new audit events `question_retired`,
  `question_restored`, `findings_synced` (EN/RU/UK). The answers panel lists
  them under **Closed without asking**.
- **`quantities.py`**: one parser for limits in EN/RU/UK — comparators
  (min, max, strict more/less than, "must not exceed", "не дольше", "не
  пізніше"), ranges, number formats ("1 000", "1,000", "2,5"), unit
  conversion within a dimension (ms…weeks, KB/MB/GB), percent, items, and
  the currencies USD/EUR/GBP/RUB/UAH (never converted into each other).
- **Evaluation**: 26 new cases (30 in total: 13 English, 10 Russian — one
  with mixed Latin/Cyrillic units — and 7 Ukrainian) covering ambiguity,
  contradictions, currencies, boundaries, irrelevant-question traps,
  duplicates, multi-step interviews, findings
  resolved/reopened mid-interview and every API failure kind. New gold fields
  (`contradictions`, `non_contradictions`, `must_not_ask`, `steps`) and
  metrics (`false_positive_rate`, `contradiction_recall`,
  `contradiction_precision`, `invented_values`, `progress_regressions`;
  `resolved_reasked` now also counts findings resolved during the interview).
  Thresholds tightened; CI runs the scripted and rules-only suites and
  publishes both tables in the job summary.

#### Changed
- **Contradictions are context-aware.** Limits are compared per dimension in
  base units (30 min = 1800 s is not a conflict; 500 ms vs 2 s is), lower vs
  upper limits that cannot both hold are reported, and requirements with
  another scope qualifier (*international*, *оптовых*, *корпоративних*,
  *admin*) or an extra condition (*if …*, *для …*, *якщо …*) are not.
  Topic similarity also compares what the limit is about (the words before
  it). Grill answers are compared with their requirement in base units too;
  an answer that adds a scope qualifier states a new rule, not a conflict.
- **Fewer irrelevant questions.** Error handling is not asked for
  adjective-like participles (*uploaded photos*, *загруженные*, *завантажені*)
  unless the input is validated or limited, for preconditions (*after login*),
  nouns (*login date*, *account type*, *in the form of*), look-alikes
  (*enterprise*, *формат*), page loading (*загружаться*) or a form/field named
  without an action; limits are not asked for event-bound expiry (*expires
  when the user logs out*); quoted labels are not vague; *see / видит /
  бачить*, *формируется / формується* and *завершается* count as outcomes; a
  declarative rule with a stated value is not asked what to observe. Inflected
  vague words (*простым*, *кількох*) and attachments (*attach*, *прикрепля*)
  are recognized.
- AI questions are dropped when they ask about exactly a contradicting pair a
  built-in question already covers (or that was resolved), offer one value in
  two units ("30 minutes or 1800 seconds?"), or repeat a closed question.
- `numbers_in` (hallucination checks) understands grouped numbers ("1 000").

### Changed
- Adaptive Grill: within a priority the riskiest question is asked first
  (`Question.risk`: finding severity, requirement quality, findings spanning
  several requirements); field questions of test cases and bug reports keep
  their order. Findings already resolved in the analyzed document are not
  asked again, neither by the planner nor by the AI (their questions count as
  already asked). Some tests were updated for the new order only.
- Grill footer: **Review**, **Close, keep saved**, **Cancel**. The History
  tab and the trace use compact list rows that fit the right panel.
- Redesigned interface: a dark navy sidebar with the project/document switcher,
  page navigation (Home, Requirements Analysis, Grill Mode, Test Cases,
  Traceability, Dashboard, Export, Settings), the AI status and the language;
  a page header with title, AI status, a quick provider/model menu and a
  Settings shortcut; white cards on a light workspace with blue-violet
  accents. Design tokens live in `theme_ui.py` (mirrored in
  `.streamlit/config.toml`, checked by `tests/test_theme.py`); all CSS is
  scoped to Streamlit test IDs or keyed containers. The former tabs moved to
  pages: Findings, Test design, Bug reports and AI analysis are tabs of
  Requirements Analysis, Automation is a tab of Test Cases. Analyze opens
  Requirements Analysis; a new or deleted document opens Home.
- Grill Mode layout: the interview in the center (progress, counters for
  confirmed / assumptions / unknowns / unresolved contradictions, the current
  requirement with a full-requirement view, a question card with priority,
  category, requirement IDs and rationale, answer actions, previous answers)
  and an Analysis / Findings / Report panel on the right, computed from the
  session (`grill/insights.py`). Buttons read **Submit answer**, **Mark as
  assumption**, **Mark as unknown** and **Skip**. Findings show what the
  interview decided without resolving them; assumptions are never shown as
  confirmed.
- AI settings moved from the sidebar to **Settings** and the header menu;
  project rename/delete moved to **Settings → Projects**. The AI choice and
  typed requirements are kept while their page is not shown. The status says
  *connected* only after a successful connection test of the provider and
  model in use.
- Streamlit toolbar set to `minimal` (no developer "Deploy" button).

### Added
- **Saved Grill interviews** (`grill/persistence.py`): every change is saved as
  an interview of the open project — answers, question history, draft,
  findings, progress, unresolved questions and audit log. The start screen
  lists unfinished interviews (Resume / Delete) and finished ones; **Close,
  keep saved** leaves an interview without cancelling it. In `local` storage
  interviews are files in the project's `grill/` folder and the last
  unfinished one reopens after a page reload; in `session` storage nothing is
  written to disk and **Save progress to a file** / **Resume from a file**
  carry an interview across reloads and machines (validated, size-limited).
- **Findings history** (`findings.py`): resolved findings can be **reopened**
  and the last change **undone** on Requirements Analysis → Findings, each
  with an optional reason; every resolve, reopen and undo is recorded in
  `Workspace.finding_history` (time, how, Grill session, clarification,
  reason). Grill's resolve panel takes an optional reason. Both sides of a
  contradiction change together.
- **Decision traceability and audit log** (`grill/trace.py`): a History tab
  in Grill Mode shows each question's source (rule finding with its trigger
  words, contradiction, conflicting answer, follow-up, AI interviewer and
  model, empty field), requirement IDs, answer and state (CONFIRMED,
  ASSUMPTION, UNKNOWN, CONFLICT, OPEN; overruled answers marked), every
  change to each answer, and the session's append-only audit log. **Download
  audit log (JSON)**; the Markdown download now ends with the decision trace.
- **AI quality evaluation** (`spec_to_test.evaluation`, `docs/EVALUATION.md`):
  `python -m spec_to_test.evaluation` runs fixture documents through the real
  Grill pipeline with a scripted model and reports relevance, duplication,
  coverage, re-asked resolved findings, hallucinations before and after the
  trust filters, test case quality and invented requirement IDs, gated by
  `thresholds.json`. `--rules-only` gives the baseline, `--live` uses the
  configured provider; `pytest -m live_ai` (with `SPEC_TO_TEST_LIVE_AI=1`) is
  the optional live test. CI uploads the report.
- `grill.ai` functions accept `on_response` to observe the raw model reply
  (used by the evaluation; never changes the result). AI questions record
  their model (`Question.ai_model`).
- `theme_ui.list_item`, a reusable list row (badges, literal text, caption);
  styles for saved interviews and the findings panel; reduced-motion support.
- Quality dimensions (`quality.DIMENSIONS`, `dimension_scores`): Clarity,
  Completeness, Testability and Consistency, each a fixed group of the
  existing criteria, so they add up to the same points as the score.
- Test case read view, export validation (how many test cases each file holds, a warning when it would be empty),
  dashboard "Unresolved issues" and "Requirements by quality", RTM coverage
  bars, empty states that lead to Home.
- Projects: group requirement documents by product or application. The
  sidebar picks the project and one of its documents, creates projects (name,
  optional description), renames them and deletes a document or a whole
  project after confirmation. Every document has its own workspace, so the same
  text in two projects is separate work. In `local` storage projects live in
  `projects/<id>/` of the data folder and the last project and document reopen
  on the next start; in `session` storage they stay in the browser session and
  nothing touches the disk. Work saved by earlier versions opens unchanged in
  the default project ("My project").
- Grill Mode, unified adaptive interview: built-in and AI questions share one
  queue ranked by priority (high / medium / low; every built-in question now
  has one), re-ranked after each answer; contradictions are asked first within
  their priority. New deterministic follow-ups: a clarification that is still
  vague asks for a testable value, one that sets a new input limit asks what
  happens beyond it (not for time targets, not when the behavior is already
  stated), one level deep, dismissed by skipping.
- Grill Mode conflicts (`grill/conflicts.py`): an answer whose limit
  contradicts its requirement or another answer (rule-engine limit parsing)
  becomes a high-priority, essential question offering the statements
  verbatim; it is resolved only by the user's answer ("unknown" leaves it
  open, with a review warning `answer_conflict`). Every question has a derived
  state — CONFIRMED, ASSUMPTION, UNKNOWN, CONFLICT or OPEN — shown with the
  progress bar, in the answer history and in a new **Unresolved issues** panel.
  Each question shows its priority, requirement IDs and testing impact.
- Grill final report: **Contradictions** section (decision or unresolved);
  contested and overruled answers are kept out of the confirmed decisions and
  never resolve workspace findings. Sections renamed to "Confirmed decisions",
  "Unresolved questions" and "Suggested test scenarios".
- AI interviewer quality controls: the model receives the planned queue,
  states and open conflicts; it may be consulted after every answer (once per
  answer state, never chained by its own questions) and its question joins the
  ranked queue (`GrillWorkflow.merge_questions`). Questions are dropped when
  they repeat or reword any known question, ask about a confirmed or unknown
  field, name an unknown requirement, exceed 400 characters, or state a number
  that is not in the input (disputed values excluded). AI test case ideas are
  dropped when their expected result states such a number.
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
- Grill interviews ask the most important open question first, so the order
  differs from earlier versions (for example a missing expected result before
  vague wording; without a document, the feature under test before an
  unverifiable requirement ID). Stored sessions still load: questions without
  a priority count as high if essential, otherwise medium.
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

### Migration
- Grill session schema 1 → 2 (audit log, timestamps, settled findings,
  question risk, AI model) and workspace schema 1 → 2 (`schema_version`,
  `finding_history`). Older saves are upgraded automatically on load and
  rewritten on the next save; files from a newer version are refused. No
  manual step is needed.

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

[Unreleased]: https://github.com/antonplotnikov/spec-to-test/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/antonplotnikov/spec-to-test/compare/v1.1.0...v1.2.0
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
