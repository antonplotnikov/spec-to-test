# CSV exports and field mappings

All exports are generated from the current workspace, so they always include
your latest edits (titles, steps, review statuses, deleted test cases).

General rules for every file:

- UTF-8, comma-separated, RFC 4180 quoting (multi-line cells are quoted).
- Headers are always English so import wizards can auto-map them. Cell values
  keep the language you wrote them in.
- Cells starting with `=`, `+`, `-`, `@`, tab or carriage return get a leading
  apostrophe (`'`) so spreadsheet apps do not execute them as formulas.
- Test cases linked to a requirement that is not in the document are skipped.
- "Export only Approved test cases" limits the test case files to `Approved`.

## Jira: test cases (`jira_test_cases.csv`)

Import with **Jira Settings → System → External System Import → CSV**
(or a project's **Import issues from CSV**).

| CSV column   | Map to Jira field | Content |
|--------------|-------------------|---------|
| Summary      | Summary           | `[TC-001] <title>` |
| Issue Type   | Issue Type        | `Task` by default; change it in the Export tab (e.g. `Test` for Xray/Zephyr). The type must exist in the target project. |
| Description  | Description       | Jira wiki markup: requirement, preconditions, numbered steps, expected result, assumptions, open questions, test ID / type / review status |
| Labels (×3)  | Labels            | `spec-to-test`, the requirement ID, `test-<type>` (spaces replaced with `_`) |

Required by Jira: **Summary** and **Issue Type**. Jira has no built-in test
step field; tools such as Xray or Zephyr have their own step import format,
so steps are placed in the Description.

## Jira: bug reports (`jira_bug_reports.csv`)

| CSV column  | Map to Jira field | Content |
|-------------|-------------------|---------|
| Summary     | Summary           | `[BUG-001] <title>` |
| Issue Type  | Issue Type        | `Bug` |
| Priority    | Priority          | Severity mapped as High → `High`, Medium → `Medium`, Low → `Low` |
| Description | Description       | Description, *Expected behavior*, *Context* (requirement quote, source line, matched text), bug ID, requirement ID, source (rule / ai) |
| Labels (×2) | Labels            | `spec-to-test`, the requirement ID |

If your Jira uses other priority names, map the values in the import wizard's
"Map field values" step.

## TestRail: test cases (`testrail_test_cases.csv`)

Import with **Test Cases → Import Cases → Import from CSV**. Choose the
**Test Case (Text)** template and "Single row per test case".

| CSV column      | Map to TestRail field | Content |
|-----------------|-----------------------|---------|
| Title           | Title (required)      | Test case title |
| Section         | Section               | Requirement ID (one section per requirement) |
| Template        | Template              | `Test Case (Text)` |
| Type            | Type                  | `Functional` |
| Priority        | Priority              | `Medium` |
| Preconditions   | Preconditions         | One per line; unconfirmed assumptions are prefixed `Assumption (not confirmed):` |
| Steps           | Steps                 | Numbered steps (`1. …`), one per line |
| Expected Result | Expected Result       | Expected result text |
| References      | References            | Requirement ID |

Required by TestRail: **Title**. Review status is not a standard TestRail
field; use "Export only Approved test cases" to control what is imported.

## Traceability matrix (`rtm.csv`)

Saved with a UTF-8 BOM so Excel shows Cyrillic text correctly.

| Column              | Meaning |
|---------------------|---------|
| Requirement ID      | ID from the document (or generated `REQ-001`) |
| Requirement         | Original wording |
| Quality Score       | 0–100 (see README → Quality score) |
| Coverage            | `covered` (≥1 Approved test), `partial` (tests, none Approved), `not_covered` |
| Open Issues         | Open rule-based finding types, `;`-separated |
| Highest Severity    | `high` / `medium` / `low`, empty if no open issues |
| Test Cases          | Linked test case IDs |
| Approved Test Cases | Linked test case IDs with status Approved |
| Bug Reports         | Linked bug report IDs |

## Markdown QA report (`qa_report.md`)

A human-readable report in the current interface language, suitable for a
GitHub wiki page, a pull request, or an email:

1. **Summary** — requirements, open issues, test cases, bug reports, coverage %, average quality.
2. **Traceability (RTM)** — the same columns as `rtm.csv`.
3. **Test cases** — one section per case with requirement, type, review status,
   preconditions, numbered steps, expected result, assumptions, open questions.
4. **Bug reports** — one section per report with severity, source, description,
   expected behavior, and context.

User text is Markdown-escaped, so requirement wording appears exactly as
written and cannot inject links, images, or table breaks. Test cases linked to
unknown requirements are skipped, as in the CSV exports.
