# QA analysis: reference\_spec.md

- Trigger: requirements document changed (run f983f7e945094f37, 2026-10-16T09:00:10.232308+00:00)
- Document: tests/fixtures/reference\_spec.md (2235af266b1669b5)
- Previous version: none
- Task: Full check
- AI review: Ollama · qwen2.5:14b
- Status: done

## Conclusions

- **Requirements analysis**: Checked 20 requirements: 2 possible contradictions, 2 with ambiguous wording, 3 without error handling, 6 without an expected result (open findings of the analysis).
- **Test Case Critic**: Checked 32 test cases; 20 have problems.
- **Scenario Coverage**: Checked 20 requirements: 0 fully covered by Approved test cases, 17 with missing scenarios.
- **Change Impact**: No previous version of this document in the project, so there is nothing to compare.
- **Traceability**: 20 requirements, 0 with an Approved test case; 0 traceability gaps.
- **Suite Planner**: Smoke: 0, Regression: 0, Full: 32 test cases.
- **AI review**: Ollama · qwen2.5:14b: 7 problems, 2 questions.

## Problems (22)

- **REF-07 · Ambiguous wording**: vague wording: quickly, user-friendly
- **REF-08, REF-10, REF-13, REF-17, REF-19, REF-20 · Missing expected result**: states no observable result: what the user or the system sees or gets afterwards
- **REF-10 · Missing error handling**: no behavior for invalid input or errors stated for: enters
- **REF-11 · Possible contradiction**: conflicts with REF-12: “at least 8 characters” ↔ “at least 12 characters”
- **REF-13 · Possible contradiction**: conflicts with REF-14: “must” ↔ “must not”
- **REF-16 · Ambiguous wording**: vague wording: зручним
- **REF-17 · Missing error handling**: no behavior for invalid input or errors stated for: завантажити
- **REF-20 · Missing error handling**: no behavior for invalid input or errors stated for: вводит, форму
- **TC-001, TC-005, TC-008, TC-011, TC-012, TC-013, TC-014, TC-015, TC-016, TC-017, TC-020, TC-023, TC-024, TC-025, TC-028, TC-029, TC-030, TC-031, TC-032 · Steps**: these steps only refer to the requirement and name no concrete action or data: 1, 2, 3.
- **TC-004 · Steps**: these steps only refer to the requirement and name no concrete action or data: 2, 3.
- **REF-02**: no test case at all, not even a Draft, for: Happy Path
- **REF-04**: no test case at all, not even a Draft, for: Negative, State Transitions
- **REF-13**: no test case at all, not even a Draft, for: Permissions
- **REF-14**: no test case at all, not even a Draft, for: Negative, Permissions
- **REF-18**: no test case at all, not even a Draft, for: Negative, Boundary, State Transitions
- **REF-13, REF-14 · AI · Contradiction**: Requirements REF-13 and REF-14 contradict each other regarding whether admins can export the audit log. (“Admins must be able to export the audit log.”)
- **REF-11, REF-12 · AI · Ambiguity**: Requirements REF-11 and REF-12 both specify minimum password lengths, but it's unclear which takes precedence. (“The new password must be at least 12 characters long.”)
- **REF-01 · AI · Missing scenario**: There is no requirement or test case covering the scenario where the email address is invalid or incorrectly formatted.
- **REF-04 · AI · Missing scenario**: There is no requirement or test case covering the scenario where the account is locked and the user tries to log in again.
- **REF-18 · AI · Missing scenario**: There is no requirement or test case covering the scenario where the account is locked after 3 failed login attempts.
- **TC-017, REF-12 · AI · Test gap**: Test case TC-017 checks for a minimum password length of 8 characters, but requirement REF-12 specifies 12 characters. (“The new password must be at least 12 characters long.”)
- **TC-020, REF-11 · AI · Test gap**: Test case TC-020 checks for a minimum password length of 12 characters, but requirement REF-11 specifies 8 characters. (“The new password must be at least 8 characters long.”)

## Unknown (5)

- **TC-014, TC-016, TC-023, TC-029, TC-031, TC-032 · Requirement match**: the requirement itself states no expected result, so the match cannot be checked.
- **REF-09**: unclear whether these apply: Boundary
- **REF-10, REF-19, REF-20**: the text is not enough to tell which scenarios apply
- **REF-11, REF-12**: Which minimum password length should take precedence: 8 characters or 12 characters?
- **REF-13, REF-14**: Should admins be able to export the audit log or not?

## Review status (not a problem of the requirements)

32 of 32 test cases are not Approved yet, and Scenario Coverage, Traceability, Suite Planner count only Approved test cases. Review and approve the test cases of REF-01, REF-02, REF-03, REF-04, REF-05, REF-06, REF-07, REF-08, REF-09, REF-10, REF-11, REF-12, REF-13, REF-14, REF-15, REF-16, REF-17, REF-18, REF-19, REF-20.

## Recommendations

- Clarify REF-07, REF-08, REF-10, REF-11, REF-12, REF-13, REF-14, REF-16, REF-17, REF-19, REF-20 with the document author before writing or approving their test cases.
- Fix the problems in TC-001, TC-004, TC-005, TC-008, TC-011, TC-012, TC-013, TC-014, TC-015, TC-016, TC-017, TC-020, TC-023, TC-024, TC-025, TC-028, TC-029, TC-030, TC-031, TC-032 before approving them.
- Clarify the requirements behind the Unknown items, then review those test cases again.
- Add and approve test cases for the missing scenarios of REF-02, REF-04, REF-13, REF-14, REF-18.
- Clarify the minimum password length requirement to avoid ambiguity between REF-11 and REF-12.
- Resolve the contradiction between REF-13 and REF-14 regarding admin audit log export.
- Add test cases for scenarios where the email address is invalid or incorrectly formatted.
- Add test cases for scenarios where the account is locked after 3 failed login attempts.
- Add test cases for scenarios where the account is locked and the user tries to log in again.
