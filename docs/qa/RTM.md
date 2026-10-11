# Requirements Traceability Matrix — Spec-to-Test v1.0.0

Links the product requirements of Spec-to-Test to manual test cases
([TEST_CASES.md](TEST_CASES.md)), automated tests (`tests/`), and defects
([BUG_REPORTS.md](BUG_REPORTS.md)).

**Automated status** is the result of the final local `pytest` run on
2026-10-11 (Python 3.11, macOS); see [TEST_SUMMARY_REPORT.md](TEST_SUMMARY_REPORT.md).
**Manual status** is copied from TEST_CASES.md; "Not executed" means no result
is claimed.

| Req. | Product requirement | Manual test cases | Automated tests | Defects | Automated status | Manual status |
|---|---|---|---|---|---|---|
| PR-01 | Accept requirements as pasted text or TXT/MD/PDF upload | TC-001, TC-003 | test_app.py, test_file_formats.py | — | Pass | Not executed |
| PR-02 | Reject invalid, empty, oversized, encrypted, or binary input with a clear message | TC-002, TC-004 | test_input_parser.py, test_file_formats.py, test_security.py | — | Pass | Not executed |
| PR-03 | Extract requirements with stable, original IDs | TC-001 | test_input_parser.py, test_id_mapping.py, test_audit_regressions.py | — | Pass | Not executed |
| PR-04 | Detect ambiguity, missing result/boundary/error handling, contradictions (EN/UK/RU) | TC-005 | test_rule_engine.py, test_reference_spec.py | — | Pass | Not executed |
| PR-05 | Explainable 0–100 quality score | TC-006 | test_quality.py | — | Pass | Not executed |
| PR-06 | Generate draft test cases without inventing rules | TC-007 | test_test_generator.py | — | Pass | Not executed |
| PR-07 | Edit, add, delete, review test cases (Draft → Reviewed → Approved) | TC-007, TC-008, TC-009 | test_app_features.py | BUG-006 | Pass | Not executed |
| PR-08 | BVA, equivalence partitioning, decision tables; unstated outcomes not guessed | TC-010 | test_test_design.py, test_app_features.py | — | Pass | Not executed |
| PR-09 | Editable bug reports with ID, severity, description, expected behavior, context | TC-011 | test_bug_reports.py, test_app_features.py | BUG-007 | Pass | Not executed |
| PR-10 | RTM linking requirements, tests, bugs, coverage | TC-007 | test_rtm_dashboard.py | — | Pass | Not executed |
| PR-11 | Dashboard with metrics, distributions, filters | TC-012 | test_rtm_dashboard.py, test_app_features.py | — | Pass | Not executed |
| PR-12 | Jira / TestRail / RTM CSV and Markdown exports with correct links | TC-013, TC-022 | test_exports.py | — | Pass | Not executed |
| PR-13 | Optional AI analysis: works without a key, consent per run, AI kept separate from facts | TC-014, TC-015 | test_ai_analysis.py, test_app_features.py | BUG-003 | Pass | Not executed |
| PR-14 | Persist edits locally; no shared storage on public hosting | TC-016, TC-017 | test_storage.py, test_app_features.py | BUG-001 | Pass | TC-016 Pass, TC-017 Not executed |
| PR-15 | Full UI in English (default), Ukrainian, Russian | TC-002, TC-018 | test_i18n.py, test_localization.py | — | Pass | Not executed |
| PR-16 | Security: untrusted input, no secret exposure, escaping, CSV injection | TC-004, TC-017, TC-019 | test_security.py, test_formatting.py, test_exports.py, test_release.py | BUG-002, BUG-004 | Pass | TC-019 Pass |
| PR-17 | Readable on large and small screens | TC-020, TC-021 | — (visual) | BUG-005 | n/a | Pass |

## Coverage summary

- Product requirements: 17
- With at least one automated test: 16 (PR-17 is visual only)
- With at least one executed manual test case: 3 (PR-14, PR-16, PR-17)
