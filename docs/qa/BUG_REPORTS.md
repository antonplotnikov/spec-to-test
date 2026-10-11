# Bug Reports — Spec-to-Test

These are **real defects** found in Spec-to-Test while preparing v1.0.0
and v1.1.0 and after v1.1.0 (code audit, security review, automated tests,
and checks in a browser preview). Each one is fixed in the version shown (or
marked as fixed but unreleased) and has a regression test. The last section is
a clearly labelled **example** showing the template only.

| ID | Title | Severity | Status | Regression test |
|---|---|---|---|---|
| BUG-001 | Last analyzed document restored for other visitors on shared hosting | Critical | Fixed in 1.0.0 | test_storage.py::test_session_mode_never_writes_or_reads, test_app_features.py::test_session_storage_mode_keeps_nothing_on_disk |
| BUG-002 | Requirement text rendered as Markdown in result tables | High | Fixed in 1.0.0 | test_formatting.py, test_app_features.py::test_user_text_is_not_rendered_as_markdown |
| BUG-003 | AI consent stays ticked after a run and for a new document | High | Fixed in 1.0.0 | test_app_features.py::test_ai_consent_is_required_again_for_every_run, ::test_new_document_resets_ai_consent |
| BUG-004 | Dependency ranges allow versions with known vulnerabilities | Medium | Fixed in 1.0.0 | test_release.py::test_runtime_dependencies_exclude_vulnerable_versions |
| BUG-005 | Long text cut off in result tables on large screens | Medium | Fixed in 1.0.0 | Manual: TEST_CASES.md TC-020 |
| BUG-006 | Confirmation messages disappear after saving | Low | Fixed in 1.0.0 | test_app_features.py::test_save_confirmation_survives_rerun |
| BUG-007 | Bug report created from AI suggestion not visible until next click | Low | Fixed in 1.0.0 | test_app_features.py::test_ai_suggestion_to_bug_report_appears_immediately |
| BUG-008 | Grill Mode answers and draft fields have no length limit | Low | Fixed in 1.1.0 | test_grill_security.py::test_too_long_answers_and_fields_are_rejected |
| BUG-009 | Grill result can be added to another document with the same requirement ID | High | Fixed, unreleased (branch `fix/p0-2-grill-context-binding`, not merged) | test_grill_integration.py::test_same_requirement_id_in_another_document_is_not_linked, test_grill_ui.py::test_changing_the_document_mid_session_does_not_move_the_result |

---

## BUG-001 — Last analyzed document restored for other visitors on shared hosting

| Field | Value |
|---|---|
| Severity | Critical (privacy) |
| Component | `app.py` startup, `storage.py` |
| Found by | Code review (deployment readiness); the existing UI test "work is restored in a new session" shows that a fresh session loads the last workspace |
| Environment | Any shared deployment (e.g. Streamlit Community Cloud), v0.2.0 |

**Description.** On start, the app loads `latest.json` from the data folder
and restores that workspace. On a shared server, the data folder is shared by
all visitors, so a new visitor would see the requirements, test cases, and bug
reports of the previous visitor.

**Steps to reproduce (v0.2.0)**
1. Run the app on one server; open it in browser A and analyze a document.
2. Open the app in browser B (another person / private window).

**Actual:** browser B shows "Restored your saved work…" with A's document.
**Expected:** browser B starts empty; documents are not stored on a shared server.

**Fix.** Storage modes: `local` (default on a personal computer) and
`session` (default on Streamlit Community Cloud, configurable with
`SPEC_TO_TEST_STORAGE`). In `session` mode nothing is written or restored.

---

## BUG-002 — Requirement text rendered as Markdown in result tables

| Field | Value |
|---|---|
| Severity | High |
| Component | `app.py` tables, warnings, test design headings |
| Found by | Code review after switching tables to `st.table`; confirmed in the DOM (cells contain `stMarkdownContainer`) |
| Environment | v1.0.0 development build, Streamlit 1.65 |

**Description.** Streamlit renders table cells, warnings, and `st.markdown`
as Markdown. Requirement text such as `[help](http://x)` or `*all*` was shown
as a link or italics, so the tool did not show the original wording and a
document could inject links/images into the page.

**Steps to reproduce**
1. Analyze `REQ-1: The system must show [help](http://localhost:9/x) and *all* items.`
2. Open the Requirements tab.

**Actual:** the cell is rendered through Streamlit's Markdown renderer
(confirmed in the DOM: the table cell contains `stMarkdownContainer`), so the
link syntax and `*…*` are interpreted instead of being shown as typed.
**Expected:** text appears exactly as written.

**Fix.** `formatting.escape_markdown()` is applied to all user text shown in
Markdown-rendered places; the Markdown export escapes cells as well.

---

## BUG-003 — AI consent stays ticked after a run and for a new document

| Field | Value |
|---|---|
| Severity | High (privacy) |
| Component | `app.py`, AI analysis tab |
| Found by | Code review against the requirement "require consent before sending documents" |
| Environment | v0.2.0 with AI configured |

**Steps to reproduce**
1. Configure AI. Analyze document A, tick consent, run AI analysis.
2. Analyze a different document B, open the AI analysis tab.

**Actual:** consent is still ticked and **Run AI analysis** is enabled for document B.
**Expected:** consent must be given again for each run and each document.

**Fix.** Consent is reset after every run and on every new analysis.

---

## BUG-004 — Dependency ranges allow versions with known vulnerabilities

| Field | Value |
|---|---|
| Severity | Medium (security) |
| Component | `requirements.txt` |
| Found by | `pip-audit` on the minimum versions allowed by `requirements.txt` |

**Description.** `pypdf>=5.0` and `streamlit>=1.50` allowed releases with
published advisories (pypdf fixed by 6.19.0, streamlit by 1.54.0). The
installed versions were not affected, but a fresh install could resolve to a
vulnerable version.

**Fix.** `pypdf>=6.19,<7`, `streamlit>=1.65,<2` (the tested version);
`pip-audit` added to CI.

---

## BUG-005 — Long text cut off in result tables on large screens

| Field | Value |
|---|---|
| Severity | Medium (usability) |
| Component | `app.py` layout |
| Found by | User feedback |

**Actual:** content limited to 1200 px; table cells truncated long requirement
text and questions, requiring manual column resizing.
**Expected:** full text visible without manual resizing.
**Fix.** Full-width layout and wrapping tables; IDs kept on one line.

---

## BUG-006 — Confirmation messages disappear after saving

| Field | Value |
|---|---|
| Severity | Low |
| Component | `app.py` (toasts before `st.rerun()`) |

**Actual:** "TC-001 saved." and "could not save" messages were created
immediately before a page rerun and could be lost.
**Expected:** the confirmation is visible after the page updates.
**Fix.** Messages are queued and shown after the rerun.

---

## BUG-007 — Bug report created from AI suggestion not visible until next click

| Field | Value |
|---|---|
| Severity | Low |
| Component | `app.py`, AI analysis tab |

**Actual:** after "Create bug report from suggestion", the Bug reports tab
(rendered earlier in the same run) did not show the new report.
**Expected:** the report appears immediately.
**Fix.** The page reruns after the report is created.

---

## BUG-008 — Grill Mode answers and draft fields have no length limit

| Field | Value |
|---|---|
| Severity | Low |
| Status | Fixed in 1.1.0 (found before release, in unreleased code) |
| Component | Grill Mode (`grill/workflow.py`, `grill/drafts.py`, `grill_ui.py`) |
| Found by | Security review during release preparation (2026-10-11) |

**Description.** Pasted documents and drafts are limited to 100,000
characters, but answers to Grill questions and direct edits of draft fields
were not. A single session could grow without bound, and a confirmed test case
or bug report added to the workspace would write that text to the save file.

**Steps to reproduce (before the fix).**
1. Start **Test case → Interview** in Grill Mode.
2. Paste 200,000 characters as an answer and click **Save answer**.

**Expected.** The answer is rejected with a clear message.
**Actual.** The answer was accepted and stored in the draft.

**Fix.** Answers and draft fields are checked against the same limit as an
analyzed document (`MAX_TEXT_CHARS`) in the domain code, with a translated
error; text inputs also set `max_chars`.

**Regression tests.** test_grill_security.py::test_too_long_answers_and_fields_are_rejected,
::test_assumed_answers_are_bounded_too

---

## BUG-009 — Grill result can be added to another document with the same requirement ID

| Field | Value |
|---|---|
| Severity | High (wrong traceability: coverage, RTM and exports show a test or bug under a requirement it was not written for) |
| Status | Fixed, unreleased: branch `fix/p0-2-grill-context-binding`, not merged or released |
| Component | Grill Mode (`grill/integration.py` `add_blocker`, `grill_ui.py`) |
| Found by | Code review of the hand-over to the workspace (2026-10-11) |
| Environment | v1.1.0 |

**Description.** A Grill session lives in the browser session and is not reset
when another document is analyzed. "Add to the workspace" only checked that a
requirement with the same ID exists in the current workspace, so a result made
for document A could be attached to a different requirement of document B that
happens to have the same ID. Nothing told the user that the document had changed.

**Steps to reproduce (before the fix).**
1. Analyze document A, which contains `REQ-2: The password must be at least 10 characters.`
2. In Grill Mode run **QA review → Test case** with a draft linked to REQ-2;
   confirm it (do not add it yet).
3. Switch **Mode** to **Requirements analysis** and analyze document B, which
   contains `REQ-2: The system must send a reset email within 5 minutes.`
4. Switch back to Grill Mode and click **Add to the workspace as a Draft test case**.

**Actual.** The test case is added to document B under its REQ-2 (also for bug
reports, which then reach the RTM and the Jira CSV).
**Expected.** Nothing is added to document B; the user is told why.

**Fix.** The session already stores the requirements it was started on
(`context_requirements`). `context_blocker()` compares that snapshot (IDs and
texts of all requirements) with the workspace's requirements, and `add_blocker()`
uses it before any other link check:
- `context_changed` — the documents differ: nothing is added;
- `context_unknown` — the session was started without an analyzed document,
  so it cannot be tied to the current one: nothing is added.

The add button is disabled with the translated reason (EN / UK / RU). In test
case and bug report sessions a warning is shown while the session is open
(checked by tests on the question, review and final steps; the check does not
depend on the step) but not for a cancelled session, which has no result left to
add or download. It appears as soon as the analyzed document differs from the session's (`context_changed`) or a document
is analyzed after a session that was started without one (`context_unknown`).
Requirements Grill sessions show no such warning: they have no snapshot by
design and are not added as items. The session is not reset and answers are
kept; the result can be downloaded as Markdown once the session is confirmed
(the download is offered only on the final step). Re-analyzing the same
document, or returning to it, makes adding possible again. Provenance (`Source.USER`), Draft status, approval
and resolving findings are unchanged.

**Regression tests.**
- test_grill_integration.py::test_same_requirement_id_in_another_document_is_not_linked
  (two documents with `REQ-2`, test case and bug report),
  ::test_whole_context_is_compared_not_just_the_linked_requirement,
  ::test_session_without_a_document_snapshot_is_not_linked_to_a_later_document,
  ::test_test_case_that_cannot_be_linked_is_not_added,
  ::test_reanalyzing_the_same_document_keeps_the_session_valid,
  ::test_added_and_approved_test_case_still_covers_its_requirement
- test_grill_ui.py::test_changing_the_document_mid_session_does_not_move_the_result,
  ::test_returning_to_the_original_document_makes_the_result_addable_again,
  ::test_interview_answers_survive_a_document_change_and_the_result_stays_out,
  ::test_session_started_without_a_document_warns_as_soon_as_one_is_analyzed,
  ::test_cancelled_session_gets_no_context_warning
- Unchanged behavior of resolving: test_grill_integration.py::test_resolve_still_compares_requirement_text_not_the_whole_context,
  ::test_requirements_grill_on_pasted_text_has_no_snapshot_and_still_resolves,
  ::test_findings_of_another_document_are_not_resolved;
  test_grill_ui.py::test_requirements_grill_on_pasted_text_still_resolves_findings

**Known limitations of the fix.**
1. `context_blocker()` compares IDs and texts only. Two different documents
   with identical requirements (same IDs and texts) cannot be told apart, and
   adding is allowed.
2. The whole requirement list must match. If the same document is re-analyzed
   after any requirement was edited, the session is treated as belonging to
   another document; the way out is the Markdown download or a new session.
3. A session started when no document was analyzed (`context_unknown`) can
   never be added to a document analyzed later. Before the fix this worked
   when the IDs happened to match.
4. `resolve_blocker()` is **unchanged**: it checks that every requirement in the
   Requirements Grill draft exists in the workspace with the same text. It does
   not compare the whole document, so a draft whose requirements are a subset
   with identical IDs and texts is still accepted for another document that
   contains them. This keeps Requirements Grill on pasted text (which has no
   snapshot) working; a stricter check is a separate task.
5. The error code `requirement_not_in_workspace` is now only a defensive check
   in `add_blocker()` and is normally unreachable.
6. This fix does not change local or shared storage. Isolation of saved
   workspaces between users (P0-1) is a separate item and is **not** fixed here.

## EXAMPLE (template only — not a real defect)

> The report below is **fictional example data** that shows the format used
> above. It does not describe a real problem in Spec-to-Test.

| Field | Value |
|---|---|
| ID | BUG-EXAMPLE |
| Title | Dashboard coverage shows 100 % when no test case is approved |
| Severity | High |
| Environment | v1.0.0, Chrome 130, macOS 15, language English |

**Steps to reproduce**
1. Analyze `examples/password_reset.md`.
2. Leave all test cases in Draft. Open Dashboard.

**Actual (example):** Coverage = 100 %.
**Expected:** Coverage = 0 %, because coverage counts only Approved test cases.
**Attachments:** screenshot, browser console log.
