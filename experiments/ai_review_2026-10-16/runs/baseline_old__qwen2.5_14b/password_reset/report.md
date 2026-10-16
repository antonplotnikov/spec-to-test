# QA analysis: password\_reset.md

- Trigger: requirements document changed (run ad0a43a12375ae36, 2026-10-16T09:07:46.823856+00:00)
- Document: examples/password\_reset.md (3e307f986ed38c0c)
- Previous version: none
- Task: Full check
- AI review: Ollama · qwen2.5:14b
- Status: done

## Conclusions

- **Requirements analysis**: Checked 9 requirements: 1 possible contradictions, 2 with ambiguous wording, 1 without error handling, 2 without an expected result (open findings of the analysis).
- **Test Case Critic**: Checked 15 test cases; 11 have problems.
- **Scenario Coverage**: Checked 9 requirements: 0 fully covered by Approved test cases, 9 with missing scenarios.
- **Change Impact**: No previous version of this document in the project, so there is nothing to compare.
- **Traceability**: 9 requirements, 0 with an Approved test case; 0 traceability gaps.
- **Suite Planner**: Smoke: 0, Regression: 0, Full: 15 test cases.
- **AI review**: Ollama · qwen2.5:14b: 3 problems, 3 questions.

## Problems (14)

- **REQ-1, REQ-9 · Missing expected result**: states no observable result: what the user or the system sees or gets afterwards
- **REQ-1 · Missing error handling**: no behavior for invalid input or errors stated for: entering
- **REQ-4 · Possible contradiction**: conflicts with REQ-7: “at least 8 characters” ↔ “at least 10 characters”
- **REQ-5 · Ambiguous wording**: vague wording: fast, user-friendly
- **REQ-6 · Ambiguous wording**: vague wording: many
- **TC-001, TC-002, TC-003, TC-006, TC-009, TC-010, TC-011, TC-015 · Steps**: these steps only refer to the requirement and name no concrete action or data: 1, 2, 3.
- **TC-007 · Conflicting expectation**: TC-012 expects the opposite outcome for the same input: 9 characters. Decide which outcome is right before approving either test case.
- **TC-014 · Steps**: these steps only refer to the requirement and name no concrete action or data: 2, 3.
- **REQ-3**: no test case at all, not even a Draft, for: State Transitions
- **REQ-6**: no test case at all, not even a Draft, for: Negative, State Transitions
- **REQ-8**: no test case at all, not even a Draft, for: Happy Path
- **REQ-4, REQ-7 · AI · Contradiction**: The requirements specify different minimum lengths for the new password. (“The new password must be at least 8 characters long and contain one digit.”)
- **REQ-5, TC-009 · AI · Test gap**: The test case does not specify how to measure 'fast' or 'user-friendly'. (“The reset page should load fast and be user-friendly.”)
- **REQ-6, TC-010 · AI · Test gap**: The test case does not specify how many failed attempts lock the account. (“After too many failed attempts, the account is locked.”)

## Unknown (5)

- **TC-001, TC-015 · Requirement match**: the requirement itself states no expected result, so the match cannot be checked.
- **REQ-6**: unclear whether these apply: Boundary
- **REQ-4, REQ-7**: Which minimum length should be enforced for the new password?
- **REQ-5**: How should 'fast' and 'user-friendly' be defined for the reset page?
- **REQ-6**: How many failed attempts should lock the account?

## Review status (not a problem of the requirements)

15 of 15 test cases are not Approved yet, and Scenario Coverage, Traceability, Suite Planner count only Approved test cases. Review and approve the test cases of REQ-1, REQ-2, REQ-3, REQ-4, REQ-5, REQ-6, REQ-7, REQ-8, REQ-9.

## Recommendations

- Clarify REQ-1, REQ-4, REQ-5, REQ-6, REQ-7, REQ-9 with the document author before writing or approving their test cases.
- Fix the problems in TC-001, TC-002, TC-003, TC-006, TC-007, TC-009, TC-010, TC-011, TC-012, TC-014, TC-015 before approving them.
- Clarify the requirements behind the Unknown items, then review those test cases again.
- Add and approve test cases for the missing scenarios of REQ-3, REQ-6, REQ-8.
- Clarify the minimum password length requirement.
- Define specific criteria for 'fast' and 'user-friendly' in the reset page test case.
- Specify the number of failed attempts that lock the account.
