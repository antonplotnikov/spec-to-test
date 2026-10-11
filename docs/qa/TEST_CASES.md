# Test Cases — Spec-to-Test v1.1.0

Manual test cases for the application itself. Most of them are also covered
by automated tests (column **Automated by**); manual execution focuses on
what automation cannot see: real browser rendering, layout, and file dialogs.

**Status values:** `Pass` / `Fail` — executed, with date and executor;
`Not executed` — not run yet (no result is assumed).

Test data: `examples/password_reset.md` (9 requirements, REQ-1 … REQ-9).

| ID | Title | Req. | Priority | Automated by | Manual status |
|---|---|---|---|---|---|
| TC-001 | Analyze pasted requirements | PR-01, PR-03 | High | test_app.py::test_analyze_shows_requirements_and_findings | Not executed |
| TC-002 | Empty input shows translated error | PR-02, PR-15 | High | test_app.py::test_empty_input_shows_translated_error | Not executed |
| TC-003 | Upload a Markdown file | PR-01 | High | test_app.py::test_uploaded_markdown_file_is_analyzed | Not executed |
| TC-004 | Reject an invalid / oversized file | PR-02, PR-16 | High | test_file_formats.py, test_app.py::test_uploaded_invalid_pdf_shows_translated_error | Not executed |
| TC-005 | Findings for flawed requirements | PR-04 | High | test_reference_spec.py, test_app.py::test_findings_table_uses_original_requirement_ids | Not executed |
| TC-006 | Quality score breakdown | PR-05 | Medium | test_quality.py, test_app_features.py::test_requirements_show_quality_score | Not executed |
| TC-007 | Edit and approve a test case | PR-07, PR-10 | High | test_app_features.py::test_edit_and_approve_test_case_updates_rtm_and_persists | Not executed |
| TC-008 | Validation when editing a test case | PR-07 | Medium | test_app_features.py::test_invalid_edit_is_rejected | Not executed |
| TC-009 | Add and delete a test case | PR-07 | Medium | test_app_features.py::test_add_and_delete_test_case | Not executed |
| TC-010 | Boundary values and decision table | PR-08 | High | test_test_design.py, test_app_features.py::test_test_design_tab_shows_boundaries | Not executed |
| TC-011 | Generate and edit bug reports | PR-09 | High | test_bug_reports.py, test_app_features.py::test_generate_bug_reports | Not executed |
| TC-012 | Dashboard filters | PR-11 | Medium | test_rtm_dashboard.py::test_filters | Not executed |
| TC-013 | Export files and requirement links | PR-12 | High | test_exports.py | Not executed |
| TC-014 | AI tab without configuration | PR-13 | High | test_app_features.py::test_ai_tab_without_key_explains_setup | Not executed |
| TC-015 | AI consent required per run | PR-13 | High | test_app_features.py::test_ai_consent_is_required_again_for_every_run | Not executed |
| TC-016 | Work restored after reload (local mode) | PR-14 | High | test_app_features.py::test_work_is_restored_in_a_new_session | Pass — 2026-10-11, browser preview (see note 1) |
| TC-017 | Session mode keeps nothing on disk | PR-14, PR-16 | Critical | test_app_features.py::test_session_storage_mode_keeps_nothing_on_disk | Not executed (manual check belongs to post-deployment) |
| TC-018 | All tabs in Ukrainian and Russian | PR-15 | High | test_localization.py | Not executed |
| TC-019 | User text is shown literally | PR-16 | High | test_formatting.py, test_app_features.py::test_user_text_is_not_rendered_as_markdown | Pass — 2026-10-11, browser preview (see note 2) |
| TC-020 | Full text visible on a large screen | PR-17 | Medium | — (visual) | Pass — 2026-10-11, browser preview 1920×1080 (see note 3) |
| TC-021 | Layout on a phone-sized screen | PR-17 | Medium | — (visual) | Pass — 2026-10-11, browser preview 375×812 (see note 4) |
| TC-022 | Import CSV into Jira and TestRail | PR-12 | Medium | — (external tools) | Not executed |
| TC-023 | Requirements Grill: clarify and confirm | PR-18, PR-19 | High | test_grill_ui.py::test_requirements_grill_end_to_end_requires_explicit_confirmation | Not executed |
| TC-024 | Test Case Grill interview with back and edit | PR-18 | High | test_grill_ui.py::test_test_case_interview_validates_answers_and_supports_back, ::test_test_case_interview_reaches_draft_and_edits_mark_user_values | Not executed |
| TC-025 | Bug Report Grill from a pasted draft | PR-18, PR-19 | High | test_grill_ui.py::test_bug_draft_review_shows_unparsed_lines_and_asks_only_for_gaps | Not executed |
| TC-026 | QA Review blocks confirmation on blocking issues | PR-19 | High | test_grill_ui.py::test_qa_review_blocks_confirmation_until_blocking_issues_are_fixed | Not executed |
| TC-027 | Grill AI assistant needs consent per request | PR-20 | High | test_grill_ai_ui.py::test_ai_buttons_need_consent_and_consent_resets_after_each_request, ::test_without_ai_configuration_nothing_ai_is_offered | Not executed |
| TC-028 | Confirmed Grill test case appears in Test cases, RTM and exports | PR-21 | High | test_grill_ui.py::test_confirmed_test_case_is_added_to_the_analyzed_workspace, test_grill_integration.py::test_added_test_case_reaches_rtm_coverage_and_every_export | Not executed |
| TC-029 | Clarified findings are resolved only when ticked | PR-21 | High | test_grill_ui.py::test_requirements_grill_resolves_only_ticked_findings | Not executed |
| TC-030 | Grill Mode in Ukrainian and Russian | PR-15, PR-18 | Medium | test_grill_ui.py::test_every_grill_screen_is_translated, test_grill_ai_ui.py::test_ai_screens_are_translated | Not executed |

Notes on executed cases (executed by the AI coding assistant during release
preparation, in a Chromium-based preview of the desktop app; not yet
re-executed by a human tester):

1. TC-016: after analyzing a document and reloading the page, the workspace and
   the "Restored your saved work" message appeared.
2. TC-019: requirement `… show [help](http://localhost:9/x) …` was displayed
   literally in the Requirements table (link syntax not rendered as a
   Markdown link).
3. TC-020: at 1920 px the content used the full width and long cells wrapped;
   requirement IDs stayed on one line.
4. TC-021: at 375 px the layout stacked into one column with no horizontal
   page scroll (document scroll width = 375 px).

---

## Detailed steps

### TC-001 Analyze pasted requirements
**Preconditions:** app open, language English.
1. Paste the content of `examples/password_reset.md` into "Paste requirements".
2. Click **Analyze**.

**Expected:** "Requirements" = 9; Requirements tab lists REQ-1 … REQ-9 with
original wording; no error is shown.

### TC-002 Empty input shows translated error
1. Switch language to Русский.
2. Leave the text field empty and click **Анализировать**.

**Expected:** error "Поле пустое. Пожалуйста, введите требования."; no results.

### TC-003 Upload a Markdown file
1. Upload `examples/password_reset.md`.
2. Click **Analyze**.

**Expected:** message that the uploaded file is used; 9 requirements.

### TC-004 Reject an invalid / oversized file
| Input (equivalence class / boundary) | Expected |
|---|---|
| `spec.docx` (unsupported type) | "Unsupported file type …" |
| empty `spec.txt` | "The uploaded file is empty." |
| 2 MB + 1 byte `.txt` | "The file is too large (maximum 2 MB)." |
| `spec.pdf` that is plain text | "The file is not a valid PDF." |
| password-protected PDF | "Password-protected PDFs are not supported." |

### TC-005 Findings for flawed requirements
1. Analyze the example. Open **Findings**.

**Expected:** REQ-5 and REQ-6 have "Ambiguous wording"; REQ-4 and REQ-7 have
"Possible contradiction" referencing each other; every finding is labelled
"Rule-based" and "Needs clarification".

### TC-006 Quality score breakdown
1. Analyze the example. In Requirements, open "Why does a requirement get this quality score?".
2. Select REQ-5.

**Expected:** score below 100; "Unambiguous" lost points with evidence
"fast, user-friendly"; points of all criteria add up to the score.

### TC-007 Edit and approve a test case
1. Analyze. Open **Test cases**, select the first case.
2. Change the title, set Review status = Approved, click **Save**.
3. Open **Traceability (RTM)** and **Dashboard**.

**Expected:** "saved" confirmation; RTM row shows the case under "Approved
tests" and Coverage "Covered"; dashboard coverage > 0 %.

### TC-008 Validation when editing a test case
1. Clear the title (or all steps, or the expected result) and click **Save**.

**Expected:** error "Title, at least one step and the expected result are
required."; the case is unchanged.

### TC-009 Add and delete a test case
1. Click **Add test case**. 2. Tick "Yes, delete TC-…" and click **Delete**.

**Expected:** Delete is disabled until confirmed; the new case appears, then
disappears from the list, RTM, and exports.

### TC-010 Boundary values and decision table
1. Open **Test design**, select REQ-4.
2. Select REQ-8.

**Expected:** REQ-4: values 7 (rejected), 8 and 9 (accepted). REQ-8: decision
table with rule R1 (condition true → generic message) and R2 marked "not
specified — needs clarification" plus a warning.

### TC-011 Generate and edit bug reports
1. Open **Bug reports**, click **Generate bug reports from open findings**.
2. Edit the first report's severity and click **Save**. 3. Click generate again.

**Expected:** reports BUG-001 …; one report for the REQ-4/REQ-7
contradiction; edits persist; no duplicates after the second click.

### TC-012 Dashboard filters
1. Open **Dashboard**, filter Issue severity = High. 2. Add search "REQ-4".

**Expected:** metrics, charts, and table show only matching requirements;
clearing filters restores all 9.

### TC-013 Export files and requirement links
1. Approve one test case. 2. Download all five exports.

**Expected:** each CSV opens in a spreadsheet; every test case references an
existing requirement ID; "Export only Approved" leaves one test case; the
Markdown report lists all requirements, test cases, and bugs.

### TC-014 AI tab without configuration
**Precondition:** no `AI_PROVIDER` / key.

**Expected:** info explaining how to enable AI; no Run button; the rest of the
app works.

### TC-015 AI consent required per run (decision table)
| AI configured | Consent ticked | Expected |
|---|---|---|
| No | — | No Run button |
| Yes | No | Run button disabled |
| Yes | Yes | Run allowed; consent unticked afterwards |
| Yes (new document analyzed) | was Yes | Consent reset to No |

### TC-016 Work restored after reload (local mode)
1. Analyze the example, generate bug reports. 2. Reload the browser page.

**Expected:** "Restored your saved work …"; bug reports still present.

### TC-017 Session mode keeps nothing on disk
**Precondition:** `SPEC_TO_TEST_STORAGE=session` (default on Streamlit Cloud).
1. Analyze. 2. Open the app in a private window.

**Expected:** sidebar says work is kept only for this browser session; the
private window starts empty; no `.spec_to_test_data/` folder is created.

### TC-018 All tabs in Ukrainian and Russian
1. Analyze, generate bugs. 2. Switch to Українська, open every tab; repeat for Русский.

**Expected:** no English UI labels (except data and Streamlit's own uploader
text), no technical keys such as `tab.rtm`, no layout breaks.

### TC-019 User text is shown literally
1. Analyze `REQ-1: The system must show [help](http://localhost:9/x) and *all* items.`

**Expected:** the Requirements table shows the brackets and asterisks as
typed; no link or italics.

### TC-020 Full text visible on a large screen
1. Open the app at 1920 px width. 2. Check Findings and RTM tables.

**Expected:** content uses the screen width; long text wraps; IDs on one line.

### TC-021 Layout on a phone-sized screen
1. Open the app at 375 px width.

**Expected:** single column; no horizontal page scrolling; tables scroll
inside their own area.

### TC-022 Import CSV into Jira and TestRail
1. Import `jira_test_cases.csv` and `jira_bug_reports.csv` into a Jira test project.
2. Import `testrail_test_cases.csv` into a TestRail project (template "Test Case (Text)").

**Expected:** fields map as documented in docs/EXPORTS.md; Cyrillic text and
multi-line steps are preserved.

### TC-023 Requirements Grill: clarify and confirm
**Preconditions:** `examples/password_reset.md` analyzed; sidebar **Mode → Grill Mode**.
1. Choose **Clarify requirements**; keep "Use the 9 requirements from the analyzed document" ticked; click **Start**.
2. Answer the first question; click **Keep as assumption** for the next one; click **Go to the draft**.
3. Click **Run review**, tick the acceptance of the warnings, click **Continue to confirmation**, then **Confirm and finalize**.

**Expected:** each question shows why it matters and the linked requirement
text; the draft shows the 9 requirements unchanged plus clarifications labeled
*Confirmed by you* / *Assumption (not confirmed)*; nothing is finalized before
**Confirm and finalize**.

### TC-024 Test Case Grill interview with back and edit
1. Choose **Test case → Start from scratch (interview)**, click **Start**.
2. Click **Save answer** with an empty answer; then answer two questions.
3. Click **Back**, change the answer; open **Your answers** and **Change** another one.

**Expected:** empty answer → translated error; the previous answer is shown for
editing; answered questions are not asked again; changed draft fields are
labeled *Confirmed by you*.

### TC-025 Bug Report Grill from a pasted draft
1. Choose **Bug report → Improve my draft**, paste a labeled draft with one
   unlabeled line (e.g. "Note to self: check logs"), click **Start**.

**Expected:** labeled fields are filled and labeled *From the source*; the
unlabeled line is shown literally as not recognized; only missing fields are
asked about; no severity, steps or environment are filled in by the app.

### TC-026 QA Review blocks confirmation on blocking issues
1. Choose **QA review → Bug report**, paste a draft without an expected result, click **Start**.

**Expected:** blocking findings are listed separately from warnings and
suggestions; **Continue to confirmation** is disabled until they are fixed.

### TC-027 Grill AI assistant needs consent per request
**Preconditions:** run once without AI configured, once with a test key.
1. Without AI: open Grill Mode.
2. With AI: open the *AI assistant (optional)* panel, tick consent, request
   questions; open the panel again.

**Expected:** without AI no AI controls are offered and the deterministic mode
is labeled; with AI the buttons are disabled until consent is ticked and the
tick is cleared after every request; AI questions are labeled and skippable.

### TC-028 Confirmed Grill test case appears in Test cases, RTM and exports
**Preconditions:** `examples/password_reset.md` analyzed.
1. In Grill Mode run **QA review → Test case** on a complete draft linked to
   REQ-2; confirm it (**Confirm and finalize**); click **Add to the workspace as a Draft test case**.
2. Switch **Mode** to **Requirements analysis**; open Test cases, RTM and Export.

**Expected:** a new `TC-…` with source *User-provided* and status *Draft* is
listed for REQ-2 and in all exports; REQ-2 coverage is *Partial* until the case
is approved; the add button is disabled afterwards ("already in the workspace").

### TC-029 Clarified findings are resolved only when ticked
**Preconditions:** `examples/password_reset.md` analyzed.
1. Run **Clarify requirements**, answer the first question (REQ-1), confirm.
2. In **Use the result**, check that nothing is ticked; tick the clarification;
   click **Mark selected as resolved**; switch to **Requirements analysis**.

**Expected:** only clarifications you confirmed are listed (assumptions are
not); after resolving, the REQ-1 finding answered by it is no longer an open
issue and the quality score of REQ-1 increases; other findings stay open.

### TC-030 Grill Mode in Ukrainian and Russian
1. Repeat TC-023 and TC-024 in Українська and Русский.

**Expected:** no English text or raw translation keys on any Grill screen;
user-entered text is shown as typed.
