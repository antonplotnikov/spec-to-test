# Spec-to-Test

[![CI](https://github.com/<your-github-username>/spec-to-test/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-github-username>/spec-to-test/actions/workflows/ci.yml)
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
- export to Jira, TestRail, CSV, and Markdown.

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
| **Input** | Paste text or upload TXT/MD/PDF (≤ 2 MB, ≤ 50 PDF pages). Recognises IDs (`REQ-1:`, `FR-AUTH-01`, `[US-3]`), Markdown headings and tables, bullet and numbered lists, and plain sentences. |
| **Rule-based analysis** | Ambiguous wording, missing expected result, missing boundaries, missing error handling, possible contradictions — in EN, UK, and RU text. Every finding is a *hint* marked "Needs clarification". |
| **Quality score** | 0–100 per requirement from 7 fixed criteria, with the evidence that cost points. |
| **Test cases** | Draft cases generated per requirement; edit, add, delete (with confirmation), and review: Draft → Reviewed → Approved. |
| **Test design** | Boundary Value Analysis, Equivalence Partitioning, and Decision Tables — only from facts written in the requirement. Unstated outcomes are shown as "not specified", never guessed. |
| **Bug reports** | Editable reports for requirement defects: ID, severity, description, expected behavior, reproduction context. |
| **RTM** | Requirement → quality → open issues → test cases → approved tests → bug reports → coverage. |
| **QA dashboard** | Requirements, open issues, test cases, coverage %, average quality, severity / coverage / review charts, and filters. |
| **Exports** | Jira CSV (test cases, bugs), TestRail CSV, RTM CSV, and a Markdown QA report. |
| **AI analysis (optional)** | Anthropic Claude looks for ambiguities, contradictions, and missing scenarios. Consent is required for every run; results are labeled and kept apart from rule-based facts. |
| **Persistence** | Edits are saved locally and restored next time (or kept per browser session on shared hosting). |

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

## Quick start

Requires **Python 3.11+**.

```bash
git clone https://github.com/<your-github-username>/spec-to-test.git
cd spec-to-test
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
streamlit run app.py
```

Open http://localhost:8501 and try it with
[`examples/password_reset.md`](examples/password_reset.md).

### Optional: AI analysis

```bash
pip install -r requirements-ai.txt   # official anthropic SDK
cp .env.example .env                 # then set AI_PROVIDER and ANTHROPIC_API_KEY
```

- Nothing is sent until you tick the consent checkbox (it names the provider
  and the number of requirements). Consent is asked again for every run and
  for every new document, and it is also enforced in code.
- Only requirement IDs and texts are sent. The API key is never displayed,
  logged, or saved, and error messages contain no request data.
- Each suggestion must reference requirement IDs from your document; its quote
  is checked against the text (✅ found / ⚠️ not found).
- Default model: `claude-opus-5-5` (override with `AI_MODEL`).

---

## Usage

1. Paste requirements or upload a file, then click **Analyze**.
2. **Requirements / Findings** — review possible issues and the quality score
   breakdown.
3. **Test cases** — edit the generated drafts and move them to *Approved*.
4. **Test design** — inspect boundary values, classes, and decision tables.
5. **Bug reports** — generate reports from open findings and edit them.
6. **Traceability (RTM) / Dashboard** — check coverage; filter by severity,
   coverage, quality, or text.
7. **Export** — download Jira / TestRail / RTM CSV or the Markdown report.
   Field mappings: [docs/EXPORTS.md](docs/EXPORTS.md).

---

## Configuration

| Setting | Where | Default | Purpose |
|---|---|---|---|
| `AI_PROVIDER` | `.env` / env / Streamlit secrets | `none` | `anthropic` enables the AI tab |
| `ANTHROPIC_API_KEY` | `.env` / env / Streamlit secrets | — | API key for AI analysis |
| `AI_MODEL` | `.env` / env / Streamlit secrets | `claude-opus-5-5` | Model ID |
| `SPEC_TO_TEST_STORAGE` | env / Streamlit secrets | `local` (`session` on Streamlit Cloud) | `local` saves to disk; `session` keeps work only in the browser session |
| `SPEC_TO_TEST_DATA_DIR` | env | `.spec_to_test_data/` | Folder for saved work |

Environment variables override `.env`. Upload limits are in
`.streamlit/config.toml` and `src/spec_to_test/input_parser.py` (a test keeps
them in sync).

---

## Architecture

```
app.py                       Streamlit UI (tabs, editor forms, downloads)
src/spec_to_test/
├── models.py                Pydantic models: Requirement, Finding, TestCase, DefectReport, Workspace …
├── input_parser.py          File validation (type, size, encoding, PDF pages) + requirement extraction
├── rule_engine.py           Keyword rules → Findings (EN / UK / RU)
├── quality.py               Explainable 0–100 score
├── test_design.py           BVA, equivalence partitions, decision tables
├── test_generator.py        Draft test cases
├── bug_reports.py           Defect reports from findings / AI suggestions
├── rtm.py                   Traceability matrix, coverage, dashboard summary, filters
├── exports.py               Jira / TestRail / RTM CSV, Markdown report
├── formatting.py            Markdown escaping for user text
├── storage.py               Local JSON persistence and storage modes
├── ai_analysis.py           Optional LLM review (consent required)
└── i18n.py                  All UI text in EN / UK / RU
tests/                       Unit, integration, regression and Streamlit UI tests
docs/                        Exports, deployment, release checklist, QA documentation
```

**Data flow:** input → `input_parser` → `rule_engine` → `Workspace`
(+ `test_generator`) → saved by `storage`. The RTM, dashboard, and exports are
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
storage at a temporary folder and switches AI off; AI tests use a fake client.
CI runs lint, type checks, tests on Python 3.11 and 3.12, and `pip-audit` on
every push and pull request ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

QA documentation for the app itself — test plan, test cases, bug reports, RTM,
and test summary report — is in [docs/qa/](docs/qa/).

---

## Deployment

The app is ready for **Streamlit Community Cloud**. See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for step-by-step instructions and
[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) for the v1.0.0 checklist.

---

## Security and privacy

- Uploaded files are untrusted: only `.txt`, `.md`, `.pdf`; size, encoding,
  page count, encryption, and binary content are checked.
- User text is escaped before display, so it is never rendered as Markdown
  (no injected links or images).
- CSV exports neutralise spreadsheet formulas (CSV injection).
- No data leaves your machine unless AI is configured **and** you consent for
  that run.
- On shared hosting (Streamlit Cloud) documents are not written to disk by
  default, so visitors cannot see each other's work.
- Secrets live in `.env` or Streamlit secrets, both git-ignored. See
  [SECURITY.md](SECURITY.md).

---

## Limitations

- Rules are keyword heuristics: they can miss issues and produce false positives.
- Generated test cases are drafts with generic steps; they need human review.
- Test design understands numbers with these units only: characters, minutes,
  seconds, hours, days, attempts, MB. Decision tables support up to 3
  conditions joined only by `and` or only by `or`.
- IDs must start with capital letters (`REQ-1`). Scanned (image-only) PDFs are
  not supported. `**bold**` markers are removed from requirement text.
- Generated text uses the interface language at generation time.
- Saved work is matched by the exact document text.
- Rule findings cannot be marked as resolved in the UI.
- Jira priorities and TestRail types/priorities use default values.
- AI supports Anthropic only and was tested with a fake client, not the live API.
- Tables do not support column sorting (they wrap text instead of truncating it).
- Some labels inside Streamlit's file uploader ("Upload", size hint) come from
  Streamlit and stay in English.

---

## Project status and license

Version **1.0.0** — see [CHANGELOG.md](CHANGELOG.md).
Released under the [MIT License](LICENSE).
