# Spec-to-Test

[![CI](https://github.com/antonplotnikov/spec-to-test/actions/workflows/ci.yml/badge.svg)](https://github.com/antonplotnikov/spec-to-test/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

**Spec-to-Test** is a Streamlit web app for QA engineers. Paste software
requirements (or upload a TXT, MD, or PDF file) and it will:

- flag ambiguous, incomplete, or contradictory requirements,
- score each requirement's quality from 0 to 100 with a transparent breakdown,
- generate draft test cases, including boundary values, equivalence classes,
  and decision tables,
- let you review and edit test cases (Draft → Reviewed → Approved),
- produce bug reports for requirement defects,
- track coverage in a Requirements Traceability Matrix and a QA dashboard,
- export to Jira, TestRail, CSV, and Markdown,
- **Grill Mode:** interview you, one question at a time, until a requirement
  set, test case, or bug report is complete and unambiguous — or review an
  artifact you already have,
- **Automation (optional):** turn an Approved test case into a Playwright
  TypeScript test — Claude explores your staging site in a real browser, the
  test is generated, run in a sandboxed Chromium, and approved by you.
- **QA Agent:** build an editable test plan linked to requirement IDs, run
  the approved cases in a real browser (Python Playwright) against a web app
  you are authorized to test, and get Passed / Failed / Blocked / Not run
  results with screenshots, bug reports, run history, retests and a QA report
  with requirement coverage — no AI key needed.
- **Autonomous QA:** enter the URL of a site you may test; the agent explores
  it read-only, drafts evidence-based requirements (Observed / Inferred /
  Unknown, with questions), generates tests, and — after your approval — runs
  them and drafts bug reports, with traceability from website evidence to bug.

The interface is available in **English** (default), **Ukrainian**, and
**Russian**. It works fully offline; AI review is optional and runs only with
your explicit consent.

> **Live demo:** `https://<your-app-name>.streamlit.app` *(add after deployment)*

---

## Screenshots

> 📸 *Placeholder — add `docs/screenshots/analysis.png` (requirements and findings).*
>
> 📸 *Placeholder — add `docs/screenshots/dashboard.png` (QA dashboard with filters).*
>
> 📸 *Placeholder — add `docs/screenshots/test-case-editor.png` (editing and review status).*
>
> 📸 *Placeholder — add `docs/screenshots/test-design.png` (BVA and decision table).*

See [docs/screenshots/README.md](docs/screenshots/README.md) for what each
screenshot should show.

---

## Features

| Area | What it does |
|---|---|
| **Projects** | Group requirement documents by product or application: pick and create projects in the sidebar, rename and delete them under **Settings → Projects**, add any number of documents to each, and switch between them. Each document keeps its own test cases, reviews and bug reports, so the same text in two projects is two separate pieces of work. |
| **Input** | Paste text or upload TXT/MD/PDF (≤ 2 MB, ≤ 50 PDF pages). Recognises IDs (`REQ-1:`, `FR-AUTH-01`, `[US-3]`), Markdown headings and tables, bullet and numbered lists, and plain sentences. |
| **Rule-based analysis** | Ambiguous wording, missing expected result, missing boundaries, missing error handling, possible contradictions — in EN, UK, and RU text. Every finding is a *hint* marked "Needs clarification". |
| **Quality score** | 0–100 per requirement from 7 fixed criteria, with the evidence that cost points. |
| **Test cases** | Draft cases generated per requirement; edit, add, delete (with confirmation), and review: Draft → Reviewed → Approved. |
| **Test design** | Boundary Value Analysis, Equivalence Partitioning, and Decision Tables — only from facts written in the requirement. Unstated outcomes are shown as "not specified", never guessed. |
| **Bug reports** | Editable reports for requirement defects: ID, severity, description, expected behavior, reproduction context. |
| **RTM** | Requirement → quality → open issues → test cases → approved tests → bug reports → coverage. |
| **QA dashboard** | Requirements, open issues, test cases, coverage %, average quality, severity / coverage / review charts, and filters. |
| **Exports** | Jira CSV (test cases, bugs), TestRail CSV, RTM CSV, and a Markdown QA report. |
| **Grill Mode** | An interactive QA interviewer: clarify requirements, build or improve a test case or bug report, or run a QA review of an existing artifact. Every value shows where it came from (source, confirmed by you, assumption, unknown); nothing is finalized without your explicit confirmation. |
| **AI analysis (optional)** | An AI model (Claude, OpenAI, an OpenAI-compatible server or local Ollama) looks for ambiguities, contradictions, and missing scenarios. Consent is required for every run; results are labeled and kept apart from rule-based facts. |
| **Persistence** | By default work (projects included) lives only in your browser session and nothing is written to disk. Opt-in `SPEC_TO_TEST_STORAGE=local` (single-user machines) saves projects and edits to disk and reopens the last project and document next time. |

### Coverage status

| Status | Meaning |
|---|---|
| Covered | At least one linked test case is **Approved** |
| Partially covered | Test cases exist, but none is Approved |
| Not covered | No test cases |

### Quality score

Only open **rule-based** findings reduce the score; AI suggestions never do.

| Criterion | Points | Loses points when |
|---|---:|---|
| Unambiguous | 20 | −10 per ambiguous term (fast, user-friendly, …) |
| Expected result | 20 | no observable outcome is stated |
| Consistent | 20 | possible contradiction with another requirement |
| Concrete limits | 15 | limits mentioned without numbers |
| Error handling | 10 | user input without failure behavior |
| Atomic | 10 | several sentences each contain an obligation (must, shall, …) |
| Has an ID | 5 | the ID was generated, not written in the document |

Grades: **Good** ≥ 80, **Fair** 50–79, **Poor** < 50.

---

## Installation

Requires **Python 3.11 or newer** and `git`.

### macOS / Linux

```bash
git clone https://github.com/antonplotnikov/spec-to-test.git
cd spec-to-test
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt        # app only
streamlit run app.py
```

### Windows (PowerShell)

```powershell
git clone https://github.com/antonplotnikov/spec-to-test.git
cd spec-to-test
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501 and try it with
[`examples/password_reset.md`](examples/password_reset.md).

| File | Installs | Use it when |
|---|---|---|
| `requirements.txt` | Streamlit, Pydantic, pypdf, pandas | you only want to run the app |
| `requirements-dev.txt` | the above + pytest, ruff, mypy | you want to run tests or contribute |
| `requirements-ai.txt` | the above + the `anthropic` and `openai` SDKs | you want the optional AI features with Claude or OpenAI (Ollama and OpenAI-compatible servers need no SDK) |

No configuration is needed: without a `.env` file the app runs fully offline.

### macOS app (own window, no browser)

```bash
git clone https://github.com/antonplotnikov/spec-to-test.git
cd spec-to-test
macos/build_app.sh            # creates ~/Applications/Spec-to-Test.app
```

Then open **Spec-to-Test** from Finder, Launchpad, or Spotlight. It opens in
its own window (WebKit, via [pywebview](https://pywebview.flowrl.com/)) with
its own Dock icon. Closing the window or **⌘Q** stops the local server.

- `build_app.sh` creates `.venv` if needed and installs
  `requirements-desktop.txt` (the app plus pywebview). If `.env` sets
  `AI_PROVIDER` to `anthropic` or `openai`, the AI SDKs are installed on launch too.
- **Settings** (AI key, Automation hosts and credentials) go in
  `~/Library/Application Support/Spec-to-Test/settings.env` — a private file
  (only your user can read it) created with commented examples on first
  launch. Uncomment the lines you need and restart the app. Only the AI
  provider keys (see [Configuration](#configuration)) and `AUTOMATION_*` keys
  are read from it.
- **Automation tab:** if Node.js 20+ is installed (nvm or Homebrew is fine),
  the build also installs `requirements-automation.txt` and the Playwright
  toolchain in `automation/runner`, and remembers where `node` is (apps opened
  from Finder do not get your shell's `PATH`). Then set `AI_PROVIDER`,
  `ANTHROPIC_API_KEY` and `AUTOMATION_ALLOWED_HOSTS` in `settings.env`; for a
  staging site on your own machine or LAN also
  `AUTOMATION_ALLOW_PRIVATE_NETWORK=true`.
- The server listens on `127.0.0.1` only, on port 8501 (or the next free one),
  and exits when the window process ends, even after a crash.
- Work is **saved on disk** (`SPEC_TO_TEST_STORAGE=local`) in
  `~/Library/Application Support/Spec-to-Test/data`, because the app is meant
  for your own Mac. The log is `~/Library/Logs/Spec-to-Test/server.log`.
- Exports open a Save dialog (default folder: Downloads); links open in your
  browser.
- The app runs this checkout, so code changes apply on the next launch.
  Rebuild it after moving the folder or recreating `.venv` with another
  Python. Without building the app: `macos/start.sh`.
- The app is signed ad hoc, not notarized: it is meant to be built on the Mac
  that runs it.

### Optional: AI features (Claude, OpenAI, OpenAI-compatible servers or Ollama)

```bash
pip install -r requirements-ai.txt   # official anthropic and openai SDKs
cp .env.example .env                 # then set AI_PROVIDER and the provider's key
```

| Provider | `AI_PROVIDER` | Credentials | Default model |
|---|---|---|---|
| Claude (Anthropic) | `anthropic` (or `claude`) | `ANTHROPIC_API_KEY` | `claude-opus-5-5` |
| OpenAI | `openai` | `OPENAI_API_KEY` (+ optional `OPENAI_BASE_URL` for a compatible gateway) | `gpt-5` |
| OpenAI-compatible server (LM Studio, vLLM, llama.cpp, LocalAI) | `openai_compatible` (or `compatible`) | `OPENAI_COMPATIBLE_BASE_URL` (e.g. `http://localhost:1234/v1`); optional `OPENAI_COMPATIBLE_API_KEY` | none: set `OPENAI_COMPATIBLE_MODEL` |
| Ollama (local) | `ollama` | none; `OLLAMA_HOST` (default `http://localhost:11434`) | `llama3.1` (`ollama pull` it first) |

- `AI_PROVIDER` is the default. Every other provider whose key is set (or
  Ollama / an OpenAI-compatible server, when `OLLAMA_HOST` /
  `OPENAI_COMPATIBLE_BASE_URL` is set) can be picked per browser session in the
  header's AI menu (the model button next to the status) or under
  **Settings → AI provider**, together with the model. **Use AI features**
  switches AI off for your session: the app falls back to the rule-based mode
  and nothing is sent anywhere. **Test connection** sends one tiny request
  with no document data. The status in the header and the sidebar says
  *connected* only after that test succeeded for the provider and model in
  use; otherwise it says *not tested*, *connection failed* or *rule-based
  mode*. On a shared deployment, `AI_LOCK_SETTINGS=true` shows the settings
  read-only.
- API keys come only from the environment, Streamlit secrets or `.env`. They
  are never entered in or shown by the page (it only says which variable is
  set), never logged, and never part of error messages. A key is sent only
  over `https`, or over `http` to this machine (`localhost`, `127.x`, `::1`);
  otherwise the provider is reported as unusable instead of being called.
- OpenAI-compatible servers and Ollama are called over plain HTTP: no SDK, no
  retries, no redirects followed, and no `OPENAI_*` setting of the real OpenAI
  provider (key, organisation, custom headers) is sent to them. They get the
  JSON schema as `response_format` (`json_schema`, non-strict) and the reply is
  validated here; a leading `<think>…</think>` block or a ```` ```json ```` fence
  around the JSON is accepted. The server must support `response_format`
  (LM Studio, vLLM, llama.cpp server and LocalAI do); otherwise the request
  fails with a generic error. Local models on a CPU can be slow: raise
  `AI_TIMEOUT` (seconds, default 300, 10–3600).
- Nothing is sent until you tick the consent checkbox (it names the provider
  and the number of requirements). Consent is asked again for every run and
  for every new document, and it is also enforced in code.
- Only requirement IDs and texts are sent. Every provider must answer in a
  fixed JSON structure that is validated before use.
- Each suggestion must reference requirement IDs from your document; its quote
  is checked against the text (✅ found / ⚠️ not found).
- Errors (wrong key, rate limit, unreachable server, unknown model, refused or
  cut-off answer) are shown as a short message; rule-based results are never
  affected.
- The same setup enables the AI interviewer in Grill Mode (see below). The
  Automation tab always uses Claude, because its browser agent is built on
  Claude's tool use.

---

## Usage

The dark sidebar holds the project and document switcher, the navigation, the
AI status and the interface language. Every page has a header with its title,
the AI status, a quick AI provider/model menu and a **Settings** shortcut. On
narrow screens the sidebar collapses (open it with the arrow at the top left)
and the columns stack.

1. Optional: in the sidebar, open **New project**, enter a name (for example
   the application under test) and click **Create project**. Without that,
   documents go to the default project, *My project*.
2. **Home** — paste requirements or upload a file, then click **Analyze**. The
   document is added to the current project and **Requirements Analysis**
   opens; pick it later in **Requirements document**, or choose **➕ New
   requirements** to add another one. Analyzing a document the project already
   has reopens its saved work. With a document open, Home shows its key
   figures and shortcuts.
3. **Requirements Analysis** — quality score with four dimensions (Clarity,
   Completeness, Testability, Consistency; each is a fixed group of the
   explainable criteria), open findings by severity, and the tabs
   *Requirements*, *Findings*, *Test design*, *Bug reports* and *AI analysis*.
   **Launch Grill Mode** clarifies the open findings.
4. **Test Cases** — read each case (preconditions, steps, expected result,
   linked requirement and its risk), edit it, and move it to *Approved*; the
   *Automation* tab turns approved cases into Playwright tests.
5. **Traceability (RTM) / Dashboard** — coverage, unresolved issues and charts;
   filter by severity, coverage, quality, or text.
6. **Export** — download Jira / TestRail / RTM CSV or the Markdown report; the
   page says how many test cases each file will contain and warns when it
   would be empty. Field mappings: [docs/EXPORTS.md](docs/EXPORTS.md).
7. **Settings** — AI provider and model, connection test, where keys come
   from, project rename/delete (with confirmation) and the storage mode.

---

## Grill Mode

Open **Grill Mode** in the sidebar (or **Launch Grill Mode** on Requirements
Analysis). The page has two columns: the interview in the middle (progress,
counters for confirmed answers, assumptions, unknowns and unresolved
contradictions, the current requirement, the question card with its priority,
category, requirement IDs and testing rationale, the answer actions and your
previous answers) and an analysis panel on the right with four tabs:
*Analysis* (quality score and dimensions of the session's requirements, open
items, active assumptions, unresolved questions, related requirements),
*Findings* (ambiguities, missing information, contradictions and review
risks, each with what the interview decided so far), *Report* (a live
summary that keeps confirmed facts, assumptions and open questions apart) and
*History* (where every decision came from and every change to it, see
[Decision history](#decision-history-and-audit-log)).
Everything in the panel is computed from the session; assumptions are never
counted or listed as confirmed. Pick a workflow:

| Workflow | Start from | Result |
|---|---|---|
| **Clarify requirements** | pasted requirements, or the document analyzed on the main page | the original requirements (unchanged) plus clarifications linked to their IDs |
| **Test case** | scratch (interview) or your draft | a test case that another tester can run without asking anyone |
| **Bug report** | scratch (interview) or your draft | a bug report a developer can reproduce |
| **QA review** | an existing requirements set, test case, or bug report | review findings, no interview |

How it works:

1. **Questions, one at a time, most important first.** Every question has a
   priority (high / medium / low), names the requirement(s) it is about, and
   says why it matters for testing. Answer it, keep your answer as an
   *assumption*, mark it as *unknown*, or skip it (essential questions cannot be
   skipped). You can go back and change any answer. Within a priority, the
   riskiest question comes first: a severe finding on a weak requirement (low
   quality score) before a minor one. Findings already resolved in the
   analyzed document are not asked about again (the start screen says how
   many). The queue adapts after every answer:
   - an answer that contradicts its requirement or another answer (for
     example "at least 10 characters" vs "at least 8") is flagged as a
     **conflict** and asked about next — choose the correct statement, write
     the correct rule, or mark it unknown; nothing is decided for you;
   - a clarification that is still vague ("fast enough") asks for a testable
     value; one that sets a new input limit asks what happens beyond it;
   - follow-ups such as boundary values appear only when they apply.

   Each question has a state — ✅ confirmed, 🟡 assumption, ❓ unknown,
   ⚔️ conflict or ⏳ open — shown under the progress bar, in the answer
   history, and in **Unresolved issues**, which lists everything still open
   by priority. Grill Mode works the same with no API key.
2. **Draft.** Edit any field directly. Every value is labeled with its origin:
   *from the source*, *confirmed by you*, *assumption*, *AI suggestion*, or
   *unknown*. Unknown values stay empty — the app never guesses them.
3. **Review.** Findings are **blocking** (must be fixed), **warnings** (fix
   them or explicitly accept them as unresolved), or **suggestions**. Checks
   reuse the rule engine: vague wording, limits that contradict or are not in
   the linked requirement, negative tests that expect success, missing test
   data, invented requirement IDs, placeholders such as `TBD`, and more.
4. **Confirmation.** Only an explicit confirmation finalizes the artifact.
   Any change after a review makes it outdated, and you must review again.
5. **Use the result.** Every confirmed result can be downloaded as Markdown,
   with origins, assumptions and open questions kept. When a document is
   analyzed on the main page:
   - a **test case** linked to one of its requirements can be added as a
     *Draft* test case (source *User-provided*). It then appears in Test
     cases, the RTM, the dashboard and every export, and counts toward
     coverage once you approve it. Test data is added to the preconditions;
     assumed values and open questions go to its assumptions and questions.
   - a **bug report** linked to one of its requirements and with a severity
     can be added to Bug reports (and the Jira bug CSV). Steps, environment,
     version, evidence, reproducibility and priority go into the report's
     context; unknown values are written as *Unknown*. Without a requirement
     or a severity the report stays Markdown-only — neither is guessed.
   - **clarified requirements:** findings answered by a clarification you
     *confirmed* can be marked resolved, one tick per clarification, nothing
     ticked by default, with an optional reason. Assumptions never resolve a
     finding. This raises the quality score; every change is recorded and can
     be **reopened or undone** on Requirements Analysis → Findings (see
     [Findings history](#findings-history-reopen-and-undo)).

To improve an existing draft, paste it with labels, for example:

```text
Title: Expired reset link is rejected
Requirement: REQ-3
Test type: negative
Steps:
1. Request a reset link
2. Wait 16 minutes and open it
Expected result: The page says "This link has expired"
```

Lines the parser does not recognize are shown to you, never dropped silently.

**AI interviewer (optional).** When AI is on, tick **AI interviewer** at the
top of a Grill session (that tick is also your consent for this session only).
It is part of the same interview, not a separate phase: after each answer the
model may add **one** question, with *why it matters* and a priority, to the
same queue as the built-in questions, and the most important open question is
always asked next (a contradiction before anything else of its priority).

- It sees the requirements, every question (asked and planned) with its
  priority, state and your reply, and the unresolved conflicts, and builds on
  them (an error path, a limit or a state your answer implies).
- Its output is checked in code before it is used: repeats and close
  rewordings of any known question are dropped, as are questions about a
  field you confirmed or marked *unknown*, questions pointing at requirements
  that do not exist, and questions that state a number found nowhere in your
  input (a presumed answer). Values in an open or lost contradiction do not
  count as input.
- It never fills in the draft and never suggests answers: only your reply
  does, and you can still answer, assume, mark it as *unknown*, or skip.
- It is asked once per answer (never in a loop) and stops after 12 questions;
  **Ask the AI for the next question** asks again. If the provider fails,
  you see the error once and the interview simply continues without AI.

The **AI assistant** panel can still suggest a batch of extra questions or add
an AI review (fresh consent tick per request). AI questions are always
optional, AI findings can warn but never block, and output that cannot be
traced (unknown fields, invented requirement IDs, quotes not found in your
text) is discarded.

**Final report.** Every confirmed session ends with a report that keeps the
kinds of statements apart and never fills a gap: **clarified requirements**
(verbatim, with their clarifications), **confirmed decisions** (the source
text, your draft, answers you confirmed), **assumptions** (not confirmed),
**unresolved questions** (unknown, skipped or unanswered), and
**contradictions** — each with your decision, or marked unresolved. An answer
that is still contested, or that lost a contradiction, is listed there and
never as a decision (and never resolves a finding in the workspace). Then
come **suggested test scenarios**: rule-based ones from the linked
requirements, plus — on request, with consent — AI ideas. An AI test case is
kept only if its expected result quotes a requirement or one of your answers;
the app (not the model) labels its basis as *requirement*, *confirmed answer*
or *depends on an assumption*. **Download as Markdown** contains the result
followed by the report and the decision trace.

### Saving and resuming interviews

Every change to an interview is saved as an interview of the open project —
answers, question history, draft, findings, progress, unresolved questions
and the audit log. The start screen lists the project's **unfinished
interviews** (with progress and open questions) to **Resume** or **Delete**;
finished and cancelled ones are kept below. **Close, keep saved** leaves an
interview without cancelling it.

- `local` storage: interviews are files in the project's data folder, written
  after every action, and the last unfinished one **reopens automatically
  after a page reload** (or the next visit), with a note saying so.
- `session` storage (the default, e.g. shared deployments): interviews are
  kept for this browser session only; nothing is written to disk. Use **Save
  progress to a file** (a JSON file) and **Resume from a file** to continue
  after a reload or on another machine. Loaded files are size-limited and
  validated; older formats are upgraded, invalid ones refused.

### Decision history and audit log

The **History** tab lists every question with its source — a rule finding
(and the words that triggered it), a contradiction in the source, an answer
that conflicts with a requirement or another answer, a follow-up to an
answer, the AI interviewer (and its model), or an empty draft field — the
requirement IDs it is about, the answer, and its state: **CONFIRMED** (a
decision), **ASSUMPTION**, **UNKNOWN**, **CONFLICT** or **OPEN**. An answer
that lost a resolved contradiction is marked *overruled*. Every change to an
answer is kept with its time and previous value, and the **audit log** lists
every action (answers, changes, AI questions added, draft edits, reviews,
confirmation, cancellation); entries are never edited. **Download audit log
(JSON)** exports the requirements, every decision and the full log. Nothing
is inferred: requirement IDs appear only when the question or draft links
them and the document contains them, and unknown items carry no value.

### Findings history: reopen and undo

Requirements Analysis → Findings has a **Resolved findings** panel: pick a
resolved finding and **Reopen** it (it counts against quality and coverage
again), or **Undo last change** (the whole last action — e.g. everything one
Grill resolution resolved — is reverted). Both take an optional reason. The
**change history** shows every resolve, reopen and undo with its time, how
it happened (Grill clarification with its session, by hand, undo) and the
reason or clarification. Both sides of a contradiction always change
together. Findings resolved before history was recorded show that their
history is unknown.

### Reactive interview queue

The open questions are recalculated after every answer (confirmed, assumption
or unknown), every direct draft edit, and every finding status change:

- **Findings resolved or reopened during an interview.** When a finding of
  the analyzed document is resolved or reopened (Requirements Analysis →
  Findings, or another interview's resolution), the open requirements
  interview on that document follows at once: a resolved finding's open
  question leaves the queue, a reopened one comes back under the same ID and,
  if the interview had run out of questions, is asked next. A note says what
  changed; answers are never touched, the question on screen stays unless it
  was the one resolved, and a review that was shown is redone.
- **Answers that settle other questions.** A confirmed or assumed
  clarification that states a limit ("locked after 5 failed attempts")
  answers the missing-limit question of the same requirement; one that names
  the failure path ("files over 20 MB are rejected with an error") answers
  its error-handling question. Contradictions and missing outcomes are never
  settled this way. Changing that answer to *unknown* brings the question back.
- **Nothing is lost.** A question that leaves the queue is listed under
  **Closed without asking** with the reason (resolved in the document,
  answered by another answer, no longer applies) and recorded in the audit
  log (*question closed*, *question back in the queue*, *findings changed in
  the document*). Question IDs never change, so the decision trace, saved
  interviews and exports stay consistent, and the number of handled
  questions never goes down.

### Numbers, units and contradictions (EN / RU / UK)

The rule engine, the test design and Grill's conflict checks share one parser
(`quantities.py`) for limits written in English, Russian or Ukrainian:

- comparators *at least / up to / more than / less than / must not exceed*,
  *не менее / не более / свыше / менее / не дольше*, *щонайменше / не більше /
  понад / менше / не пізніше*; ranges *between 8 and 64*, *8–64*, *от 8 до 64*,
  *від 8 до 64*; numbers like *1 000*, *1,000*, *2,5*;
- units of time (ms … weeks), size (KB, MB, GB, also КБ/МБ/ГБ), characters,
  attempts, items, percent, and the currencies USD ($), EUR (€), GBP (£),
  RUB (₽, руб., рублей) and UAH (₴, грн, гривень).

Two requirements contradict only when their limits cannot both hold in the
same dimension after converting units: *30 minutes* and *1800 seconds* agree,
*500 ms* and *2 seconds* do not, *at least 10* and *at most 8 characters* do
not. Amounts in different currencies are never compared (no exchange rate is
assumed). Requirements for another scope or condition — *international
orders*, *для оптовых покупателей*, *для корпоративних клієнтів*, *… if the
address is abroad* — are a different context, not a contradiction; an answer
that states a limit for another scope is treated as a new rule, not a
conflict. Questions are asked only where they apply: *uploaded photos should
appear quickly*, *after login the dashboard shows …*, *in the form of a PDF*,
*enterprise customers*, *страница загружается*, *отчёт формируется в формате
PDF*, a quoted label such as *«Быстрая оплата»*, or a session that *expires
when the user logs out* no longer raise error-handling, ambiguity or limit
questions, and a rule that states its value (*Orders over 50 USD get free
shipping*) is not asked what should be observed.

---

## AI quality evaluation

A repeatable suite measures how good the Grill AI is, using the same code
path as the app (planner, AI interviewer merged into the ranked queue,
reviews, test case suggestions, trust filters):

```bash
cd src
python -m spec_to_test.evaluation              # scripted model: deterministic, offline (also run by pytest in CI)
python -m spec_to_test.evaluation --rules-only # built-in questions only, as a baseline
python -m spec_to_test.evaluation --live       # the configured provider (optional; costs API credits)
python -m spec_to_test.evaluation --json out.json --markdown out.md
```

| Metric | Meaning |
|---|---|
| relevance | asked questions that address a gold issue of the case |
| duplication | asked questions repeating an earlier one about the same requirement |
| coverage | gold issues addressed by at least one asked question |
| resolved_reasked | questions about findings resolved in the document at that moment — before or during the interview (must be 0) |
| false_positive_rate | "must not ask" traps (questions a reviewer would not ask) that were asked |
| contradiction_recall / _precision | contradicting requirement pairs found / pairs reported that a person judged contradictory |
| invented_values | numbers in the clarified requirements that neither the document nor an answer contains (must be 0) |
| progress_regressions | times the number of handled questions went down (must be 0) |
| hallucination_raw / _accepted | model items with an invented requirement ID, an invented number, or a quote/basis not in the input — before / after the trust filters (accepted must be 0) |
| test_case_quality | suggested test cases with steps, an expected result, a real requirement, a traceable basis and no invented number |
| invented_requirements | requirement IDs in the result that the document does not contain (must be 0) |
| ai_errors | failed model calls; the interview must continue without them |

Thirty cases live in `src/spec_to_test/evaluation/fixtures/` (English,
Russian and Ukrainian): requirements, gold issues and contradicting pairs
labeled by a person, look-alike pairs that must not be flagged, "must not
ask" traps, a scripted author, findings resolved or reopened mid-interview,
and scripted model replies with planted hallucinations, duplicates and every
kind of API failure. Thresholds per mode are in
`src/spec_to_test/evaluation/thresholds.json`; the command exits with 1 when
one is missed, and CI publishes both reports in the job summary. The live test is optional:
`SPEC_TO_TEST_LIVE_AI=1 AI_PROVIDER=anthropic ANTHROPIC_API_KEY=… pytest -m live_ai`.
See [docs/EVALUATION.md](docs/EVALUATION.md).

---

## QA Agent

The **QA Agent** page runs browser tests against a web app you are
authorized to test, without an AI key:

1. **Test plan** — one plan case per test case, linked to its requirement and
   test case IDs. Concrete steps ("Enter "x" in the "Email" field", "Click the
   "Sign in" button") are converted to executable steps; vague ones are left
   empty and flagged, never guessed. Edit steps in a small step language
   (`goto /login`, `fill label=Email | …`, `click role=button[name=Sign in]`,
   `expect_text Welcome`), then approve each case.
2. **Run** — confirm you are authorized to test the host, and the approved
   cases run in headless Chromium through Python Playwright. Each step is one
   fixed Playwright call; nothing is executed as code.
3. **History** — Passed / Failed / Blocked / Not run per case with the
   screenshot, error, observed page text, console errors and a bug report for
   every failure; retest failed and blocked cases as a linked run.
4. **QA report** — coverage by requirement and downloads (Markdown, ZIP with
   screenshots, JSON, CSV).

Safety: operator allowlist (`AUTOMATION_ALLOWED_HOSTS`), SSRF checks on the
URL and on every redirect and page request, destructive actions blocked unless
allowed, secrets typed from `AUTOMATION_SECRET_<NAME>` and redacted
everywhere, per-step/per-run timeouts and run limits. A local **Demo Shop**
(`examples/qa_demo/`) with a deliberate bug shows a real pass and failure.
Setup, step language, statuses and limitations:
[docs/QA_AGENT.md](docs/QA_AGENT.md).

### Autonomous QA

Switch the QA Agent page to **Autonomous QA**, enter an authorized URL, tick
the authorization and click **Start Autonomous QA**:

1. **Discovery** (automatic, read-only) — pages, navigation, forms, fields,
   buttons and redirects, each recorded as evidence. GET requests only; nothing
   is typed, clicked or submitted; destructive links and other hosts are never
   opened.
2. **Requirements** (automatic draft, you decide) — each with an ID, source
   URL, evidence, confidence and basis: *Observed*, *Inferred* (needs
   confirmation) or *Unknown* (a question). Approve, reject, defer, edit or
   answer them.
3. **Test plan** — positive, negative, validation and boundary cases for the
   approved requirements; cases that submit forms need their own approval.
   *Send to workspace* puts the approved work into a document, so analysis,
   Grill Mode, Test Cases and the RTM use it too.
4. **Run & bugs** — runs after a fresh authorization; results are classified
   as defect, uncertain expectation, timeout, environment or security block;
   bug reports only where the evidence supports them.
5. **Final report** — site map, requirements, results, bugs and the chain
   *evidence → requirement → test case → result → bug*.

Try it on the Demo Shop and read the safety model and limitations in
[docs/AUTONOMOUS_QA.md](docs/AUTONOMOUS_QA.md).

---

## Automation (optional)

The **Automation** tab turns an *Approved* test case into a validated
Playwright test:

1. **Plan** — the test case must be Approved; the staging URL must be on the
   server's allowlist and resolve to a safe address.
2. **Explore** — Claude drives a headless Chromium through the
   [Playwright MCP server](https://github.com/microsoft/playwright-mcp),
   performs the steps, and learns real roles, labels and test ids.
3. **Generate** — Claude submits a *structured* script (not code).
   Spec-to-Test checks it and renders TypeScript from fixed templates: only
   `getByRole` / `getByLabel` / `getByTestId` / `getByPlaceholder` /
   `getByText` locators, `TC-…`/`REQ-…` tags, and assertions that quote the
   approved expected result or requirement word for word.
4. **Validate** — the test runs with `@playwright/test` in a sandboxed
   Chromium; the JSON report, screenshots and trace are kept. On failure
   Claude gets **one** repair attempt, which may fix locators and steps but
   never what the test asserts (enforced in code). A mismatch with the
   expected result stays a failure: it may be a product defect.
5. **Approve** — only a test that passed a real run can be approved. Approved
   tests are stored in the workspace and exported as a ready Playwright
   project (`.zip`).

Jobs run in the background (the page stays usable, shows live progress, and
can cancel). States: queued → planning → exploring → generating → validating
→ passed / failed / blocked / cancelled.

### Setup

```bash
pip install -r requirements-automation.txt          # anthropic + mcp
cd automation/runner && npm ci && npx playwright install chromium && cd -   # Node 20+
export AI_PROVIDER=anthropic ANTHROPIC_API_KEY=...
export AUTOMATION_ALLOWED_HOSTS=staging.example.com
export AUTOMATION_SECRET_STAGING_PASSWORD=...        # optional, typed by name only
streamlit run app.py
```

Or with Docker (app, Node toolchain and Chromium in one hardened container):

```bash
cp .env.example .env    # set AI_* and AUTOMATION_* (compose reads it)
docker compose up --build    # http://localhost:8501
```

### Security model

- **Explicit opt-in:** AI must be configured, and every run needs a fresh
  consent tick that names the provider and model.
- **Allowlist + SSRF protection:** only `http(s)` URLs on
  `AUTOMATION_ALLOWED_HOSTS` (ports 80/443 unless a port is listed). Every
  address a host resolves to must be public; private/loopback addresses need
  `AUTOMATION_ALLOW_PRIVATE_NETWORK=true`; link-local and cloud-metadata
  addresses are always refused. URLs with credentials are refused.
- **Egress lockdown in the browser:** vetted hosts are pinned to the checked
  address (no DNS rebinding), all other host names fail to resolve, and all
  other traffic — including bare IPs, other ports, redirects and requests
  from page scripts — goes to a non-existent proxy. Verified by real-browser
  tests.
- **Reduced tools:** Claude cannot evaluate JavaScript, upload files, read
  network logs or open other sites; page content is treated as untrusted.
- **No destructive actions** (delete, pay, transfer, …, in EN/UK/RU) unless
  the user ticks *Allow actions that change or delete data*.
- **Secrets** are referenced by name; values are typed by the browser, kept
  out of the model's context and the generated code, and masked in logs,
  reports and traces. The API key never reaches the child processes.
- **Isolation and limits:** child processes get a minimal environment, a
  private `HOME`/`TMPDIR`, CPU/file-size limits, their own process group
  (killed on timeout or Cancel), a 40-action exploration budget, per-run and
  per-job timeouts, and a cap on concurrent jobs.
- **Ownership:** jobs are visible only to the browser session that started
  them (or to everyone on a single-user machine in `local` storage mode).

---

## Configuration

| Setting | Where | Default | Purpose |
|---|---|---|---|
| `AI_PROVIDER` | `.env` / env / Streamlit secrets | `none` | Default provider: `anthropic` (`claude`), `openai`, `openai_compatible` (`compatible`) or `ollama`; `none` = AI off |
| `AI_MODEL` | `.env` / env / Streamlit secrets | provider default | Model for the `AI_PROVIDER` provider |
| `AI_LOCK_SETTINGS` | `.env` / env / Streamlit secrets | `false` | `true`: Settings and the header show provider and model but cannot change them |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | `.env` / env / Streamlit secrets | — / `claude-opus-5-5` | Claude key and model (Automation always uses Claude) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | `.env` / env / Streamlit secrets | — / `gpt-5` / OpenAI | OpenAI key, model, optional compatible gateway |
| `OPENAI_COMPATIBLE_BASE_URL` / `OPENAI_COMPATIBLE_MODEL` / `OPENAI_COMPATIBLE_API_KEY` | `.env` / env / Streamlit secrets | — / — / — | Self-hosted OpenAI-compatible server (`…/v1`), the model it serves, optional key |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | `.env` / env / Streamlit secrets | `http://localhost:11434` / `llama3.1` | Local Ollama server and model (no key) |
| `AI_TIMEOUT` | `.env` / env / Streamlit secrets | `300` | Seconds one AI request may take (clamped to 10–3600) |
| `SPEC_TO_TEST_STORAGE` | env / Streamlit secrets (**not** `.env`) | `session` | Only the exact value `local` (any case, spaces ignored) saves work to disk; anything else, including empty, means `session` (browser session only, nothing on disk) |
| `SPEC_TO_TEST_DATA_DIR` | env | `.spec_to_test_data/` | Folder for saved work and Grill interviews (`local` mode only) |
| `SPEC_TO_TEST_LIVE_AI` | env (tests only) | — | `1` lets `pytest -m live_ai` run the evaluation suite against the configured real provider |
| `AUTOMATION_ALLOWED_HOSTS` | env / Streamlit secrets (**not** `.env`) | — | Staging hosts for the Automation tab (`host`, `*.domain`, `host:port`); empty = off |
| `AUTOMATION_ALLOW_PRIVATE_NETWORK` | env / secrets | `false` | Allow hosts on private/loopback addresses (internal staging) |
| `AUTOMATION_SECRET_<NAME>` | env / secrets | — | Credential a test may type, referenced as `<NAME>` |
| `AUTOMATION_MAX_TOOL_CALLS` / `AUTOMATION_RUN_TIMEOUT` / `AUTOMATION_JOB_TIMEOUT` / `AUTOMATION_MAX_JOBS` | env | `40` / `240` s / `1200` s / `2` | Budgets and limits |
| `AUTOMATION_IGNORE_HTTPS_ERRORS` | env | `false` | For staging with self-signed certificates |
| `AUTOMATION_CHROMIUM_SANDBOX` | env | `true` | `false` only inside a container that is itself the sandbox (set in the Dockerfile) |
| `AUTOMATION_DATA_DIR` / `AUTOMATION_RUNNER_DIR` | env | see below / `automation/runner` | Job folders (default: next to saved work in `local` mode, else a private temp folder) and the Node toolchain |

Environment variables override `.env`. Upload limits are in
`.streamlit/config.toml` and `src/spec_to_test/input_parser.py` (a test keeps
them in sync).

**Saved data and migrations.** Saved workspaces and Grill interviews carry a
schema version and are upgraded when they are loaded, so files from older
versions keep opening; no manual step is needed. Workspace schema 2 adds the
findings change history (older files start with an empty history; findings
they mark resolved stay resolved). Grill session schema 2 adds the audit log,
timestamps, settled findings, question risk and the AI model of AI questions;
a migrated interview gets one *upgraded* entry saying its earlier history was
not recorded. Grill session schema 3 adds the questions closed without asking
(a schema 2 interview simply has none yet). A file is rewritten in the new format on its next save; files
from a newer app version are refused, not guessed. Older app versions ignore
the new fields.

---

## Architecture

```
app.py                       Streamlit entry point: settings, open document, AI choice, page dispatch
src/spec_to_test/
├── models.py                Pydantic models: Requirement, Finding, TestCase, DefectReport, Workspace …
├── input_parser.py          File validation (type, size, encoding, PDF pages) + requirement extraction
├── rule_engine.py           Keyword rules → Findings (EN / UK / RU)
├── quality.py               Explainable 0–100 score and its four dimensions
├── test_design.py           BVA, equivalence partitions, decision tables
├── test_generator.py        Draft test cases
├── bug_reports.py           Defect reports from findings / AI suggestions
├── rtm.py                   Traceability matrix, coverage, dashboard summary, filters
├── exports.py               Jira / TestRail / RTM CSV, Markdown report
├── formatting.py            Markdown escaping for user text
├── storage.py               Storage modes: session (default) and opt-in local JSON
├── projects.py              Projects of requirement documents; session and disk stores
├── quantities.py            Numbers, units, currencies, ranges (EN/RU/UK) shared by rules, test design, Grill
├── findings.py              Resolve / reopen / undo findings with change history
├── migrations.py            Upgrades saved workspaces to the current schema
├── evaluation/              AI quality evaluation: cases, scripted model, metrics, CLI
├── ai_analysis.py           Optional LLM review (consent required)
├── llm/                     Optional LLM providers (no Streamlit)
│   ├── config.py            Provider settings from env / secrets / .env; per-session choice
│   └── providers.py         One structured request to Claude, OpenAI, a compatible server or Ollama; error codes
├── i18n.py                  All UI text in EN / UK / RU
└── grill/                   Grill Mode domain logic (no Streamlit, no network)
    ├── models.py            Session, drafts, questions, answers, findings, provenance
    ├── workflow.py          Explicit steps and validated transitions
    ├── planner.py           Deterministic question banks, priorities, adaptive follow-ups
    ├── conflicts.py         Contradictions in answers, answer states (confirmed … conflict)
    ├── validation.py        Deterministic review checks
    ├── inputs.py            Labeled-draft parser
    ├── integration.py       Confirmed results → workspace, resolved findings, Markdown
    ├── report.py            Final report: facts / assumptions / unknowns, suggested test cases
    ├── insights.py          Analysis panel data: findings by kind, counts, related requirements
    ├── persistence.py       Saved interviews: disk and session stores, export / import
    ├── trace.py             Decision trace and audit log (sources, states, answer history)
    └── ai.py                Optional AI interviewer, questions, review and test ideas
├── automation/              Automation tab domain logic (no Streamlit)
│   ├── config.py            Settings from the environment, prerequisites
│   ├── security.py          Allowlist, SSRF checks, egress pinning, redaction, destructive actions
│   ├── browser.py           Playwright MCP client + gate for every tool call
│   ├── claude.py            One request of the agent loop (reuses ai_analysis config/errors)
│   ├── orchestrator.py      Job state machine: plan → explore → generate → validate (+1 repair)
│   ├── generator.py         Script validation + deterministic TypeScript / sandbox config
│   ├── runner.py, sandbox.py  Sandboxed `playwright test` run, resource limits
│   ├── results.py           Playwright JSON report → results and artifacts
│   ├── service.py, store.py Background jobs, ownership, persistence, approval
│   └── export.py            Evidence bundle, approved-tests Playwright project
theme_ui.py                  Design tokens, scoped CSS and small components (cards, badges, score bars)
shell_ui.py                  Sidebar navigation, AI status, page header
pages_ui.py                  Home, Requirements Analysis, Test Cases, RTM, Dashboard, Export, Settings
grill_ui.py                  Grill Mode page: interview + analysis panel (rendering only)
projects_ui.py               Project/document switcher (sidebar) and project settings
llm_ui.py                    AI settings, header AI menu and connection status (rendering only)
automation_ui.py             Automation tab of Test Cases (rendering only)
automation/runner/           Pinned Node toolchain: @playwright/test, @playwright/mcp
tests/                       Unit, integration, regression and Streamlit UI tests
docs/                        Exports, deployment, release checklist, QA documentation
```

**Data flow:** input → `input_parser` → `rule_engine` → `Workspace`
(+ `test_generator`) → saved in the current project (`projects`, `storage`). The RTM, dashboard, and exports are
computed from the same `Workspace` on every render, so an edit appears
everywhere at once.

---

## Testing

```bash
pytest                 # unit, integration, regression, and Streamlit AppTest UI tests
ruff check .           # lint
mypy                   # type check
```

Tests never touch your saved data or the network: `tests/conftest.py` points
storage at a temporary folder (in `local` mode, so persistence can be tested;
the `session` default has its own tests) and switches AI off (provider keys
from your shell are removed). AI tests use fake clients; the Ollama and
OpenAI-compatible clients and the real OpenAI SDK are exercised against a local HTTP server on
127.0.0.1, so no provider is ever contacted (the SDK tests skip themselves
when `openai` is not installed).
`pytest -m e2e` runs the Automation pipeline against a local page with the
real Playwright MCP server, Chromium and test runner (only the model is
scripted); these tests skip themselves when `automation/runner` is not
installed.
`tests/test_qa_agent_e2e.py` and `tests/test_qa_agent_ui.py` run the QA
Agent with real Chromium (Python Playwright) against the local Demo Shop; they
skip themselves when Playwright's Chromium is not installed
(`pip install -r requirements-qa.txt && python -m playwright install chromium`).
`tests/test_evaluation.py` runs the AI quality evaluation with the scripted
model and fails when a threshold is missed; `pytest -m live_ai` runs it
against a real provider (skipped unless `SPEC_TO_TEST_LIVE_AI=1`).
CI runs lint, type checks, tests on Python 3.11 and 3.12, the scripted and
rules-only evaluation (thresholds enforced, tables in the job summary, JSON
and Markdown uploaded as artifacts), and `pip-audit` on
every push and pull request ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

QA documentation for the app itself — test plan, test cases, bug reports, RTM,
and test summary report — is in [docs/qa/](docs/qa/).

---

## Deployment

The app is ready for **Streamlit Community Cloud**. See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for step-by-step instructions and
[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) for the v1.1.0 checklist.

---

## Security and privacy

- Uploaded files are untrusted: only `.txt`, `.md`, `.pdf`; size, encoding,
  page count, encryption, and binary content are checked.
- User text is escaped before display, so it is never rendered as Markdown
  (no injected links or images).
- CSV exports neutralise spreadsheet formulas (CSV injection).
- No data leaves your machine unless AI is configured **and** you consent for
  that run (with Ollama or a self-hosted OpenAI-compatible server, data goes only to that server). In Grill
  Mode, consent is asked for every one-off AI request; the AI interviewer's
  tick covers its follow-up questions in that Grill session only. Only the
  current draft, its linked requirement, and the questions so far with your
  replies are sent.
- Any session can switch AI off (header AI menu or **Settings**); the rule-based features
  never depend on it.
- Grill Mode keeps its interviews in your browser session only; nothing is
  written to disk, and a confirmed result you add to the workspace stays in
  your browser session too — unless you opted into `local` storage, where
  interviews are saved in the data folder like documents. A progress file you
  download contains your answers and drafts; treat it like the document.
- In every environment the default storage mode is `session`: documents are not
  read from or written to disk, so visitors of a shared deployment cannot see
  each other's work. `local` must be enabled explicitly with
  `SPEC_TO_TEST_STORAGE=local` and is meant for a single-user computer only.
  A `.env` file never changes the storage mode.
- Automation sends the test case, its requirement and staging page content
  to the AI provider only after a per-run consent; see
  [Automation → Security model](#security-model).
- Secrets live in `.env` or Streamlit secrets, both git-ignored. See
  [SECURITY.md](SECURITY.md).

---

## Limitations

- Rules are keyword heuristics: they can miss issues and produce false positives.
  Scope and condition detection (*premium users*, *если …*) uses word lists
  and clause markers, so a reworded condition can hide a real contradiction
  and an unlisted qualifier can let a different-context pair be flagged.
  Numbers count only next to a known unit or currency; an exceeded rate limit
  (*no more than once per 60 seconds*) gets no error-handling question.
- Generated test cases are drafts with generic steps; they need human review.
- Test design and contradiction checks understand numbers with these units
  only: characters, time (ms to weeks; months and years are not converted to
  days), KB/MB/GB, attempts, items, percent, USD/EUR/GBP/RUB/UAH. Currencies
  are never converted into each other. Decision tables support up to 3
  conditions joined only by `and` or only by `or`.
- IDs must start with capital letters (`REQ-1`). Scanned (image-only) PDFs are
  not supported. `**bold**` markers are removed from requirement text.
- Generated text uses the interface language at generation time.
- Saved work is matched by the exact document text.
- Rule findings can be marked as resolved only through a confirmed Grill
  Mode clarification (they can be reopened or undone by hand). Findings
  resolved before the change history existed have no recorded history.
- Jira priorities and TestRail types/priorities use default values.
- AI supports Anthropic only and was tested with a fake client, not the live API.
- Tables do not support column sorting (they wrap text instead of truncating it).
- Work is not saved between visits by default (`session` storage): closing or
  reloading the page loses it. Download the exports, or opt into `local`
  storage on your own computer.
- In `session` storage a page reload starts a new browser session, so an
  unfinished interview comes back only from a saved progress file; in
  `local` storage it reopens automatically. Finding status changes reach an
  open interview only when it runs on the analyzed document itself (same
  document and requirement texts); finished interviews are records and are
  not changed. An AI question that asks the same as a built-in one in other
  words is dropped only when the wording is close, when it names exactly a
  known contradicting pair, or when it offers one value in two units. A confirmed result can be added to the workspace, which
  needs an analyzed document and a link to one of its requirements. In the
  default `session` mode it is then kept only in the current browser session;
  it is saved to disk only with explicit `SPEC_TO_TEST_STORAGE=local`. A test
  case's *objective* and a bug's product details have no field in the
  workspace models: the objective is kept only in the Markdown download, the
  bug details as text in the report's context.
- Some labels inside Streamlit's file uploader ("Upload", size hint) come from
  Streamlit and stay in English.
- Automation: the agent loop was tested with a scripted model against the real
  MCP server, Chromium and runner, not with the live Claude API. One test case
  becomes one test in Chromium only; no multi-step login flows beyond typing
  configured secrets, no file uploads, no other browsers. Assertions are
  limited to visible/hidden, text, value, URL, title, enabled/disabled and
  checked. Destructive-action detection is keyword-based. Secrets are masked
  in text (logs, reports, traces) but not inside screenshot images, so a
  page that displays a credential in plain text shows it in screenshots. WebSocket traffic
  is not covered by the egress proxy rules. Job folders are kept on disk
  (pruned after a day in `session` mode). The Docker image was not built in
  the environment where this feature was developed. Windows is not supported
  for Automation (POSIX resource limits and process groups).

---

## Project status and license

Version **1.1.0** — adds Grill Mode (see [CHANGELOG.md](CHANGELOG.md) and
[docs/release-notes-v1.1.0.md](docs/release-notes-v1.1.0.md)).
Released under the [MIT License](LICENSE).
