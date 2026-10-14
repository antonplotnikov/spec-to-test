# Autonomous QA

**Autonomous QA** is a mode of the [QA Agent](QA_AGENT.md) page. You enter the
address of a website you are authorized to test and click **Start Autonomous
QA**. The agent then does as much of the QA workflow as it safely can:

```
URL → Website discovery → Draft requirements → Test plan → Approval → Execution → Bug reports → Final report
```

- **Automatic and read-only:** discovery of the site, drafting requirements
  from what it observed, generating test cases for them.
- **Needs a person:** confirming you may test the host (before discovery and
  before every run), approving requirements, approving the test plan
  (separately for cases that submit forms), answering questions where the
  expected behaviour is unknown.
- **Never automated:** anything destructive or consequential (delete, pay,
  purchase, transfer, sign out, …), leaving the allowed hosts, storing
  passwords, cookies or tokens.

It works without AI. An AI provider, if configured, can optionally add
interpretations — always as *Inferred*, never as facts.

## Try it with the Demo Shop

```bash
pip install -r requirements-qa.txt
python -m playwright install chromium

# Terminal 1: the demo web app, http://127.0.0.1:8765
python examples/qa_demo/server.py

# Terminal 2: the app, allowed to test the demo app
AUTOMATION_ALLOWED_HOSTS=127.0.0.1:8765 \
AUTOMATION_ALLOW_PRIVATE_NETWORK=true \
streamlit run app.py
```

1. Open **QA Agent** and switch to **Autonomous QA** (no document needs to be open).
2. Enter `http://127.0.0.1:8765/`, tick *I am authorized to test 127.0.0.1:8765…*
   and click **Start Autonomous QA**.
3. **1 · Site map**: 7 pages, 3 forms, ~28 evidence items. `/go-elsewhere` is
   shown as *redirect outside the allowed hosts (stopped)*; the "Delete account"
   form is listed but never submitted.
4. **2 · Requirements**: click **Approve all proposed Observed**. Open
   *WEB-014 · Inferred · "The form "Contact us" should not be accepted while
   "Email" is empty"* and *WEB-006 · Inferred · /broken should open without a
   server error*, and approve them too.
5. **3 · Test plan**: **Approve read-only cases**; open the "Form is not
   accepted with "Email" empty" case, tick the confirmation and approve it
   (it submits the form). Click **Send to workspace**.
6. **4 · Run & bugs**: tick the authorization, tick *Also run the approved
   cases that submit forms*, and run.
7. **5 · Final report**: download the Markdown report or the ZIP bundle.

What the run produces on the Demo Shop (asserted by
`tests/test_qa_auto_e2e.py` against real Chromium):

| Requirement | Basis | Result | Meaning |
|---|---|---|---|
| Pages open with their title and heading (/, /login, /contact, /account) | Observed | Passed | — |
| /dashboard without sign-in leads to /login | Observed | Passed | — |
| Navigation links Home / Sign in / Contact open their pages | Observed | Passed | — |
| Sign-in and contact forms show their fields and buttons | Observed | Passed | — |
| "Name" accepts at most 40 characters (boundary, from `maxlength`) | Observed | Passed | — |
| Sign-in with wrong credentials is rejected | Inferred | Passed | — |
| /broken (linked as "Order history") opens without a server error | Inferred | **Failed** (HTTP 500) | **Defect** → bug report, severity High |
| Contact form not accepted with an empty "Email" | Inferred | **Failed** | **Uncertain expectation** → bug report "[Needs confirmation]", severity Low |

If you answer the question of the contact-form requirement (for example with
"Email is required"), the expectation is confirmed: the test also checks that
text, and a failure becomes a **Defect**.

## How each step works

### 1. Discovery (read-only)

Python Playwright opens the start page in headless Chromium and follows links
breadth-first. On each page one fixed extraction script (part of the
code, never generated) reads the title, headings, links, forms, fields
(label, type, `required`, `maxlength`/`minlength`, options) and buttons. It
never reads field values, cookies or storage.

- Only `GET`/`HEAD` requests are allowed; anything else a page script tries
  (for example a `POST`) is aborted and listed.
- Links outside the allowed hosts are recorded, not opened. Links whose text
  or address contains a destructive word or that sign out are recorded, not
  opened. `mailto:`, `javascript:` and similar are ignored.
- The same egress policy as test runs applies (pinned DNS, dead proxy for
  everything else, every main-frame navigation and redirect checked): a
  redirect elsewhere is recorded as *blocked* and stopped.
- Every fact becomes **evidence** with an ID (`EV-001`, …): the URL, the text
  quoted from the page, and a locator. Page text is clipped and redacted
  (configured secret values and credential patterns) before it is stored.
- The session is saved after every page. If discovery is interrupted (time
  limit, restart), **Resume discovery** continues from the saved queue
  without opening pages twice.

### 2. Draft requirements

Rules in `qa_agent/inference.py` turn evidence into requirements. Each has a
stable ID (`WEB-001`, …), a description, the source URL, its evidence IDs, a
confidence, and questions where something is not known:

| Basis | Confidence | Examples |
|---|---|---|
| **Observed** — directly supported | 80–95% | page opens with title/heading; nav links lead to their pages; a form has these fields; `required`, `type=email`, `maxlength` attributes; a page redirects visitors to sign-in |
| **Inferred** — plausible, needs confirmation | 35–60% | wrong credentials are rejected; an email field of a contact form should not be accepted empty; a linked page should not answer 5xx |
| **Unknown** — not established by the evidence | 0–20% | what a form does after a valid submission; what a destructive action does; where an external link should lead; how sign-in succeeds |

Descriptions only quote what was observed (labels, texts, addresses); no rule
invents a business rule. Drafting again keeps IDs, decisions and edits.

You **approve, reject, defer or edit** each requirement and can **answer** its
questions. An answer that states expected text (for example the exact error
message) makes the expectation testable and *confirmed*. Bulk actions:
*Approve all proposed Observed*, *Defer all proposed Unknown*.

**Optional AI** (*Interpret with AI*, needs a consent tick): sends a summary of
the evidence (paths, titles, headings, field labels and types, link texts —
never values, cookies or secrets) to the configured provider. The prompt marks
the content as untrusted data. Returned candidates must cite existing
evidence IDs, are added as *Inferred* with confidence capped at 60%, and get no
automatic test. Questions can be added to existing requirements.

### 3. Test plan

`qa_agent/autoplan.py` builds cases in the QA Agent step language from each
requirement's template and the locators discovery found — positive,
negative, validation and boundary scenarios where the evidence supports them:

| Requirement | Case |
|---|---|
| page | open, check title and heading |
| navigation | click each nav link, check the URL |
| sign-in redirect | open the protected page, check it lands on sign-in |
| server error | open the page (a 5xx fails the case) |
| form fields | every field and the submit button are visible |
| `maxlength` (boundary) | type max and max+1 characters, check the value is cut at max |
| `required` / inferred required | fill the other fields, submit, check the form is still shown (+ the answer text) |
| `type=email` | type `not-an-email`, submit, check the form is still shown |
| wrong credentials | sign in with a deliberately wrong literal password, check the sign-in form is still shown (+ the answer text) |
| submission outcome (Unknown) | only after you answer: fill valid values, submit, check the answered text |

A case can be approved only once its requirement is approved. Cases that
**submit a form** carry a risk flag: they need their own confirmation, and
they run only when you allow form submissions for that run (otherwise they
are reported *Blocked*). Destructive forms get no cases at all.

**Send to workspace** creates (or updates) one document per session:
approved requirements keep their `WEB-…` IDs, the rule-based analysis runs on
them (so **Requirements Analysis**, **Grill Mode**, **Test Cases**, **RTM**
and **Dashboard** work as for an uploaded document), each approved case
becomes a workspace test case (approved, with the website evidence and any
open questions attached) and a QA plan case linked to it (origin *From
discovery*). Sending again updates the same records — no duplicates.

### 4. Execution

Runs use the existing QA Agent service: allowlist, SSRF checks, egress
policy, redirect checks, secrets, limits, one browser at a time, a fresh
authorization for every run. Autonomous runs never allow destructive actions.
Progress is saved after every case; an interrupted run can be **resumed**
(the remaining cases run as a linked run), and failed or blocked cases can be
**retested**.

### 5. Results and bug reports

Every result keeps its QA Agent status (Passed, Failed, Blocked, Not run) and
gets a **meaning**:

| Meaning | When |
|---|---|
| Defect | a check failed (or the server answered 5xx) and the expectation is Observed or confirmed by you |
| Uncertain expectation | a check failed, but the expectation was only Inferred/Unknown and not confirmed |
| Timeout | an element did not appear in time, or the run ran out of time |
| Environment | the browser could not start or the page could not load |
| Security block | allowed hosts, redirect, destructive action, form submissions not allowed, missing secret |

Bug reports are created only for **defects** and **uncertain expectations**
(the latter at Low severity, titled "[Needs confirmation]"). Each has title,
severity, steps to reproduce, expected and actual behaviour, environment,
evidence (screenshot, console errors, the website evidence behind the
requirement, your answer) and the requirement, test case and plan case IDs.
Reports are editable (title, severity) and never state a root cause.

### 6. Final report

The **Final report** tab and its downloads (Markdown, ZIP with the session
JSON and the run's own report bundle with screenshots, session JSON) contain
the site map, links not opened and why, all requirements with basis,
confidence, decision, evidence and questions, the latest run, the bug reports,
limitations, and the traceability table:

```
Website evidence → Requirement → Test case → Execution result → Bug report
   EV-025            WEB-006        TC-006 / QA-006   Failed (HTTP 500)   BUG-…-01
```

Screenshots, step tables and console output of each case are in **Manual
plan → History** for the session's document, as for any QA Agent run.

## Configuration

Everything from the QA Agent applies (`AUTOMATION_ALLOWED_HOSTS`,
`AUTOMATION_ALLOW_PRIVATE_NETWORK`, `AUTOMATION_SECRET_<NAME>`, `QA_*`
limits). Discovery adds:

| Setting | Default | Range | Meaning |
|---|---|---|---|
| `QA_DISCOVERY_MAX_PAGES` | 15 | 1–100 | pages opened per discovery |
| `QA_DISCOVERY_MAX_DEPTH` | 2 | 0–5 | link depth from the start page |
| `QA_DISCOVERY_TIMEOUT` | 180 | 20–1800 s | time for one discovery (resume continues) |
| `QA_DISCOVERY_MAX_ELEMENTS` | 150 | 10–1000 | links / headings read per page |

Sessions are stored next to plans and runs
(`.spec_to_test_data/qa_agent/<project>/autonomous/<session id>.json` in
`local` mode; a private temp folder in `session` mode).

## Security summary

| Control | How |
|---|---|
| Authorization | Only allowlisted hosts; an explicit confirmation before discovery, before resuming it and before every run (resets after use). |
| Read-only discovery | GET/HEAD only; no typing, clicking or submitting; destructive and sign-out links not opened. |
| SSRF / redirects | Same validation, DNS pinning, dead proxy and navigation checks as QA Agent runs; off-host redirects stopped and recorded. |
| Untrusted content | Page text is stored as clipped, redacted data and shown escaped (the report preview is shown as source). The AI prompt marks it as untrusted; AI output is validated data, never code or instructions. |
| No generated code | Tests are steps of the fixed QA Agent language; the only script run in pages is the fixed extraction script. |
| Consequential actions | Form submissions need per-case approval and a per-run permission; destructive actions are never allowed in autonomous runs. |
| Secrets | Field values, cookies and storage are never read; secret values are redacted from everything stored; screenshots follow the QA Agent rules. |
| Limits | Page, depth, time and element limits for discovery; the QA Agent limits for runs; one browser at a time. |

## Limitations (MVP)

- Discovery sees what a **signed-out** visitor sees. Signing in during
  discovery, multi-step flows, single-page-app states that need clicks,
  iframes and shadow DOM forms are not explored. A successful sign-in is
  recorded as an *Unknown* requirement (deferred).
- Requirement and test templates cover pages, navigation, sign-in redirects,
  server errors, forms (fields, `required`, `type=email`, `maxlength`, wrong
  credentials, answered outcomes). Other behaviour is left to your review,
  the optional AI interpretation (without automatic tests) or manual steps in
  the plan.
- Locators are chosen from labels, placeholders, ids and names; a field
  without a unique one gets no tests.
- The extraction script runs in the page's own JavaScript context, so a
  hostile page can feed it false structure; sizes are capped on the Python
  side and everything it returns is treated as untrusted text.
- Inferred "required email" and "wrong credentials rejected" expectations are
  heuristics: they stay *Inferred* until you confirm them.
- Rejecting or deferring a requirement after it was sent to the workspace
  revokes its plan cases and sets its test cases back to Draft on the next
  *Send to workspace*; the requirement itself stays in the document (edit or
  delete it there). Re-approving reuses the same records.
- Step descriptions in bug reports are English, like the rest of the QA Agent.

## Architecture

```
qa_auto_ui.py                          Autonomous QA mode (rendering and callbacks)
src/spec_to_test/qa_agent/
  auto_models.py   evidence, pages, forms, draft requirements, cases, session
  discovery.py     read-only crawler (Playwright) + Recorder (pure)
  inference.py     evidence → Observed / Inferred / Unknown requirements
  autoplan.py      requirements → cases; approvals; sync to workspace + QA plan
  autonomous.py    orchestration: sessions, discovery thread, resume, runs
  triage.py        result meaning, bug report refinement
  auto_report.py   final report and bundle
  auto_ai.py       optional, validated AI interpretation
  auto_translations.py   EN / UK / RU text
```

Tests: `tests/test_qa_auto_unit.py` (rules, gates, sync, triage, safety,
persistence, AI validation, report), `tests/test_qa_auto_e2e.py` (real
Chromium against the Demo Shop: read-only discovery verified at the server,
blocked redirect never reaching another service, full flow, form-submission
gate, resume) and `tests/test_qa_auto_ui.py` (the page in Streamlit AppTest).
