# QA Agent evaluation (task “Full check”, rule-based)

| Kind | Precision | TP/reported | Recall | found/required |
|---|---|---|---|---|
| contradiction | 1.00 | 5/5 | 1.00 | 5/5 |
| ambiguous_wording | 1.00 | 5/5 | 0.80 | 4/5 |
| missing_error_handling | 1.00 | 5/5 | 0.62 | 5/8 |
| missing_boundary | — | — | 0.33 | 1/3 |
| missing_expected_result | 1.00 | 10/10 | 0.91 | 10/11 |
| template_test_case | 1.00 | 46/46 | 1.00 | 46/46 |
| expectation_conflict | 1.00 | 3/3 | 0.75 | 3/4 |
| boundary_semantics | — | — | 1.00 | 9/9 |
| **total (micro)** | 1.00 | | 0.91 | |
| **mean of kinds (macro)** | 1.00 | | 0.80 | |

| Document | Precision | Recall | Problem lines | Duplicates | Status noise | Not Approved (apart) | Unknown only |
|---|---|---|---|---|---|---|---|
| password_reset | 1.00 | 0.84 | 11 | 0 | 0 | 19 | 0 |
| qa_demo | 1.00 | 1.00 | 6 | 0 | 0 | 13 | 0 |
| reference_spec | 1.00 | 0.93 | 15 | 0 | 0 | 38 | 1 |
| checkout_ru | 1.00 | 1.00 | 6 | 0 | 0 | 10 | 0 |
| uk_units_ranges | 1.00 | 0.86 | 4 | 0 | 0 | 13 | 0 |

Status noise: 0 of 42 problem lines (0.00) only say that test cases are not Approved; 93 such lines are summed up apart from the problems.

Resolved in the generated test cases (counted in recall): 9. Regressions of correct test cases: 0.

| Trap | Found | False alarms |
|---|---|---|
| contradiction | 8/9 | 0/2 |
| within_after | 7/7 | — |
| numeric_boundary | 3/5 | 0/2 |
| error_handling | 5/8 | 0/2 |
| template_test_case | 46/46 | 0/1 |
| other | — | 0/2 |

## password_reset
- missed: ambiguous_wording REQ-4 — "contain one digit": exactly one or at least one
- missed: missing_error_handling REQ-3 — what an expired link shows
- missed: missing_error_handling REQ-4, REQ-7 — what a password that breaks the rules gets
- resolved: boundary_semantics TC-004, TC-005 — "expires after 30 minutes": 29 min is valid and 31 min expired, not "not specified"

## reference_spec
- missed: missing_boundary REF-09 — "a minimum length" without a value [Unknown only: qatask.coverage.unknown_categories REF-09]
- missed: missing_boundary REF-19 — "ограничено" without a number
- missed: expectation_conflict TC-018, TC-021 — implicit: TC-018 accepts 8 and 9 characters, REF-12 (TC-021) rejects everything under 12; no shared probe value
- resolved: boundary_semantics TC-002, TC-003 — "within 60 seconds": 59 s is in time, 61 s too late
- resolved: boundary_semantics TC-006, TC-007 — "expire 30 minutes after": 29 min valid, 31 min expired
- resolved: boundary_semantics TC-009, TC-010 — "locked for 15 minutes": still locked at 14 min, unlocked at 16
- resolved: boundary_semantics TC-026, TC-027 — "протягом 5 хвилин" (within): 4 min in time, 6 min too late

## uk_units_ranges
- missed: missing_error_handling REQ-3 — аватар більший за ліміт
- missed: missing_expected_result REQ-5 — що бачить користувач після завершення сесії
- resolved: boundary_semantics TC-008, TC-009 — «не повинен перевищувати 1 МБ» is an upper limit, not equality: ≤ 1 МБ accepted, more rejected; 0/2 МБ steps are too coarse
- resolved: boundary_semantics TC-011, TC-012 — «не повинен перевищувати 1024 КБ»: 1023 КБ accepted, 1025 КБ rejected
- resolved: boundary_semantics TC-014, TC-015 — «через 15 хвилин»: session active at 14 min, ended at 16
- resolved: boundary_semantics TC-017, TC-018 — «через 5 хвилин»: session active at 4 min, ended at 6

## Thresholds

- all thresholds met
