# QA Agent

The **QA Agent** page turns the open document's requirements and test cases
into an executable test plan, runs the approved cases in a real browser
(Python Playwright, headless Chromium) against a web app you are authorized to
test, and records what happened: status, screenshot, error, the text the page
showed, and a bug report for every failure. Runs are saved, can be reopened
and retested, and export as a QA report with requirement coverage.

It works without an AI key. AI is used only if you ask it to propose steps for
a case, and what it proposes is data that you review and approve.

The page has two modes. **Manual plan** (this document) starts from an
analyzed document. **Autonomous QA** starts from a URL: it explores the site
read-only, drafts evidence-based requirements and tests, and runs them after
your approval — see [AUTONOMOUS_QA.md](AUTONOMOUS_QA.md).

## Try it in two minutes (Demo Shop)

```bash
pip install -r requirements-qa.txt
python -m playwright install chromium

# Terminal 1: the demo web app (standard library only), http://127.0.0.1:8765
python examples/qa_demo/server.py

# Terminal 2: the app, allowed to test the demo app
AUTOMATION_ALLOWED_HOSTS=127.0.0.1:8765 \
AUTOMATION_ALLOW_PRIVATE_NETWORK=true \
AUTOMATION_SECRET_DEMO_PASSWORD=demo-pass-123 \
streamlit run app.py
```

1. **Home**: upload `examples/qa_demo/requirements.md` and analyze it.
2. **QA Agent → Test plan**: enter `http://127.0.0.1:8765/`. Under
   *Import / export the plan*, import `examples/qa_demo/plan.json`, then
   **Approve to run** each case (imports never carry approvals).
3. **Run**: tick *I am authorized to test 127.0.0.1:8765…* and run.
4. **History** shows each case with its screenshot; **QA report** has the
   coverage table and the downloads.

What you should see (this is what the real run produced on the development
machine; see "Verification" below):

| Case | Requirement | Result | Why |
|---|---|---|---|
| QA-001 | REQ-1 | Passed | Heading "Demo Shop" is visible |
| QA-002 | REQ-2 | Passed | Signs in with the password from `AUTOMATION_SECRET_DEMO_PASSWORD` |
| QA-003 | REQ-3 | Passed | "Invalid email or password" is shown |
| QA-004 | REQ-4 | **Failed** | Deliberate bug: an empty email is accepted ("Thanks, Alex!") — a bug report is created |
| QA-005 | REQ-5 | Blocked | The step would click "Delete account"; destructive actions are off |
| QA-006 | REQ-6 | Blocked | `/go-elsewhere` redirects to another local port; the browser is stopped |

![QA report of the Demo Shop run](screenshots/qa-agent-report.png)

Evidence captured for the failing case QA-004 (the app thanks the user even
though the email is empty):

![Screenshot taken by the QA Agent at the end of QA-004](screenshots/qa-agent-fail-evidence.png)

The same run from the command line (useful in CI):

```bash
cd src
AUTOMATION_ALLOWED_HOSTS=127.0.0.1:8765 AUTOMATION_ALLOW_PRIVATE_NETWORK=true \
AUTOMATION_SECRET_DEMO_PASSWORD=demo-pass-123 \
python -m spec_to_test.qa_agent --plan ../examples/qa_demo/plan.json \
  --requirements ../examples/qa_demo/requirements.md \
  --approve-all --authorized --out ../qa-output
```

It prints one line per case, writes `report.md` and `qa-report.zip` into the
run folder, and exits 0 only when nothing failed or was blocked.

## Workflow

| Step | Where | What happens |
|---|---|---|
| 1. Target | Test plan tab | Enter the web app URL. It is checked at once against the operator's allowlist and the network safety rules. |
| 2. Plan | Test plan tab | **Add cases from test cases** creates one plan case per test case (optionally only *Approved* ones), linked to its requirement and test case IDs. You can also add cases by hand or import a plan JSON. |
| 3. Edit | Each case | Title, requirement, steps, expected result. Steps are written in the step language below. |
| 4. Approve | Each case | A case needs steps and at least one check. Editing it afterwards revokes the approval. |
| 5. Run | Run tab | Confirm you are authorized to test the host, optionally allow destructive actions, and run. Progress is shown per case. |
| 6. Review | History tab | Results, screenshots, errors, console errors, blocked requests, bug reports (title and severity editable). **Retest failed and blocked cases** runs them again (using the current version of each case) as a new run linked to the old one. |
| 7. Report | QA report tab | Coverage by requirement and downloads: Markdown report, ZIP (report, run JSON, CSVs, screenshots), run JSON, results CSV, bug reports CSV. |

### From test cases to steps

Concrete test steps are converted deterministically, for example:

| Written step | Becomes |
|---|---|
| `Open /login` | `goto /login` |
| `Enter "demo@example.com" in the "Email" field` | `fill label=Email \| demo@example.com` |
| `Leave the Email field empty` | `fill label=Email \| {{empty}}` |
| `Click the "Sign in" button` | `click role=button[name=Sign in]` |
| `Select "Ukraine" from the "Country" list` | `select label=Country \| Ukraine` |
| Expected: `redirected to /dashboard and shows "Welcome"` | `expect_url /dashboard`, `expect_text Welcome` |

If **any** step of a test case cannot be read (for example the generic
"Perform the action described in the requirement." that rule-based generation
writes), the plan case gets **no steps** and lists the unreadable text. A
partly converted case would test something other than what was written, so
nothing is guessed. Write the steps yourself or ask AI to propose them.

## Step language

One step per line: `action target | value`. Lines starting with `#` are comments.

| Action | Form | Notes |
|---|---|---|
| `goto` | `goto /path` or `goto https://host/path` | Must stay on an allowed host. |
| `fill` | `fill <target> \| text` | `{{secret:NAME}}` types `AUTOMATION_SECRET_NAME`; `{{empty}}` clears the field. |
| `click` | `click <target>` | Refused if the element's text looks destructive (unless allowed). |
| `select` | `select <target> \| option` | Option value or label. |
| `check` / `uncheck` | `check <target>` | |
| `press` | `press Enter` or `press <target> \| Enter` | Key names only (`Enter`, `Tab`, `Control+A`). |
| `wait_for` | `wait_for <target>` | Waits until visible. |
| `expect_text` / `expect_no_text` | `expect_text text` or `expect_text <target> \| text` | Whole page when no target. |
| `expect_visible` / `expect_hidden` | `expect_visible <target>` | |
| `expect_url` | `expect_url /path` | Same path (query ignored) or the exact URL. |
| `expect_title` | `expect_title text` | Title contains the text. |
| `expect_value` | `expect_value <target> \| text` | |

Targets: `label=Email`, `role=button[name=Sign in]`, `text=Welcome`,
`placeholder=Search`, `testid=submit`, `css=…`, or a CSS selector starting
with `#`, `.` or `[`.

Every case first opens the target URL. Each step is one fixed Playwright call
chosen by its action; nothing in a plan is evaluated as code.

## Statuses

| Status | Meaning |
|---|---|
| **Passed** | Every step and check succeeded (a case cannot be approved without a check). |
| **Failed** | A check did not hold (`assertion`), a step could not be performed — element missing, timeout (`action_error`) — or a page answered 5xx (`http_status`). A bug report is generated. |
| **Blocked** | Safety stopped the case: navigation/redirect off the allowed hosts, a destructive action, a missing secret, the browser could not start, or the run ran out of time. No bug report: these are not product bugs. |
| **Not run** | Not approved, changed after approval, no steps or checks, too many steps, or the run limit was reached. |

Pass rate = passed / (passed + failed). Requirement coverage per run:
*Passed* (all linked cases passed), *Partly verified* (some passed, others not
run), *Failed*, *Blocked*, *Not run*, *No case*.

## Bug reports

Generated only for **Failed** cases, entirely from the run: steps to reproduce
(the steps executed up to the failing one, secrets shown by name), expected
(the case's expected result plus the failing check), actual (the step that
failed, page title and URL, and the visible text for text checks), the
Playwright error, evidence (screenshot file, console errors) and environment
(URL, browser version, viewport, run ID, time). Severity starts at High for a
5xx response and Medium otherwise; title and severity can be edited.

## Safety

| Control | How |
|---|---|
| **Authorization** | Only hosts in `AUTOMATION_ALLOWED_HOSTS` (operator setting, environment only — a `.env` file cannot widen it). Each run needs a fresh “I am authorized to test this host” confirmation; it resets after every run and retest. |
| **Approval** | Only approved cases run; the approval stores a fingerprint of the case, so any edit revokes it. Imported plans never carry approvals. The CLI needs `--approve`/`--approve-all` and `--authorized`. |
| **SSRF** | The target is validated by the same code as the Automation tab (`automation/security.py`): http(s) only, no credentials in the URL, every resolved address must be public (private/loopback only with `AUTOMATION_ALLOW_PRIVATE_NETWORK=true`), link-local and cloud metadata addresses always refused. |
| **Redirects and page requests** | Chromium resolves only the vetted hosts (pinned to the checked address); every other connection — loopback included (`<-loopback>`) — goes to a proxy that does not exist; requests to other hosts are aborted by a route guard; and every main-frame navigation, redirects included, is checked: leaving the allowed hosts blocks the case. The e2e tests prove that a redirect and a page script aimed at another local service never reach it. |
| **Destructive actions** | Off by default. Steps that click/select/press/open something matching the destructive word list (EN/UK/RU: delete, remove, pay, purchase, checkout, transfer, cancel order…) are blocked before the run, and before every click the element's own text, value, aria-label and title are checked. |
| **Secrets** | `{{secret:NAME}}` reads `AUTOMATION_SECRET_NAME` at run time; plans store only the name. Secret values and credential patterns are redacted from every stored text (errors, actual results, console output, URLs). Fields filled with a secret are masked in screenshots, and if a secret value appears anywhere on the page the screenshot is not taken at all. |
| **Form submissions** | Cases generated by Autonomous QA that submit a form carry a risk flag: they run only when the run allows form submissions (an extra checkbox on the Run and Retest controls); otherwise they are Blocked. |
| **Limits** | `QA_MAX_CASES` (25), `QA_MAX_STEPS` (40), `QA_STEP_TIMEOUT_MS` (10 000), `QA_NAV_TIMEOUT_MS` (20 000), `QA_RUN_TIMEOUT` (600 s), `QA_MAX_RUNS_KEPT` (50); one run at a time per server process. Values are clamped to safe ranges. |
| **Browser** | Fresh context per case (no shared cookies), downloads off, service workers blocked, dialogs dismissed, headless, Chromium sandbox on unless `AUTOMATION_CHROMIUM_SANDBOX=false`. |
| **No generated code** | The executor interprets a fixed set of actions. AI proposals are parsed into the same step model; one invalid step rejects the whole proposal; the result still needs your approval. |

## Storage

Plans and runs follow the storage mode:

- `session` (default): a private temp folder (mode 0700) known only to your
  browser session.
- `local`: `.spec_to_test_data/qa_agent/<project>/plans/<document>.json` and
  `…/runs/<run id>/run.json` with the screenshots.

Run IDs are random hex; evidence files are only served from inside their run
folder; the oldest runs beyond `QA_MAX_RUNS_KEPT` are removed.

## Optional AI step proposals

With an AI provider configured, each case has **Propose steps**. After you tick
the consent box, the provider receives the requirement, the test case text,
the target URL and the *names* of the configured secrets — never secret
values and never page content. It returns steps in a fixed JSON schema; they
are validated like hand-written steps and marked “Steps proposed by AI”.

## Architecture

```
qa_agent_ui.py                      Streamlit page (rendering and callbacks only)
src/spec_to_test/qa_agent/
  models.py      plan cases, runs, results, bug reports (pydantic)
  steps.py       step language, locators, written-step converter
  planner.py     plans from test cases, editing, approval, import
  safety.py      limits, preflight checks, run slot
  executor.py    Playwright interpreter, egress enforcement, evidence
  service.py     authorization + SSRF checks, worker thread, saving
  bugs.py        bug reports from failed results
  report.py      coverage, Markdown/CSV/ZIP exports
  store.py       plans and runs on disk (session or local mode)
  ai.py          optional LLM step proposals
  __main__.py    command line
examples/qa_demo/  Demo Shop server, requirements and plan
```

It reuses the project's storage helpers, host allowlist, SSRF checks,
redaction and destructive-word list from the Automation module, the LLM
provider layer, CSV formula protection and the UI theme.

## Verification

`tests/test_qa_agent_e2e.py` and `tests/test_qa_agent_ui.py` run real
Chromium against the Demo Shop (skipped when Playwright's Chromium is not
installed) and assert the statuses above, PNG screenshots, the bug report,
that the password never appears in stored files, that page scripts and
redirects do not reach another local service, HTTP 500 handling, run limits,
retests and the CLI.

## Limitations

- The written-step converter understands English phrasing only (the page and
  reports are translated; the converter is not).
- Bug report texts (step descriptions, "Verify …") are English.
- One browser (Chromium), one viewport (1280×800), no file uploads, no
  multi-tab flows, no iframes targeting, no visual comparison.
- A run executes while the page waits (one run at a time per server); there is
  no queue or scheduling.
- The destructive-action check is a word list: a button labelled with an
  unrelated word that still deletes data is not detected. Keep destructive
  actions off and use a disposable test environment.
- Screenshot masking covers fields filled with a secret; secrets the page
  shows in other ways are caught only if the exact value is in the page text
  or HTML.
- The Docker image does not install Python Playwright yet; install
  `requirements-qa.txt` and Chromium to use the QA Agent there.
