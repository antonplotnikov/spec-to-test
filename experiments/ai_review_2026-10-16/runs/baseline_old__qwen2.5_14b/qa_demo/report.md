# QA analysis: requirements.md

- Trigger: requirements document changed (run cf79e8525853465d, 2026-10-16T09:08:17.319839+00:00)
- Document: examples/qa\_demo/requirements.md (b39ca78208f6fc30)
- Previous version: none
- Task: Full check
- AI review: Ollama · qwen2.5:14b
- Status: done

## Conclusions

- **Requirements analysis**: Checked 6 requirements: 0 possible contradictions, 0 with ambiguous wording, 1 without error handling, 1 without an expected result (open findings of the analysis).
- **Test Case Critic**: Checked 6 test cases; 6 have problems.
- **Scenario Coverage**: Checked 6 requirements: 0 fully covered by Approved test cases, 6 with missing scenarios.
- **Change Impact**: No previous version of this document in the project, so there is nothing to compare.
- **Traceability**: 6 requirements, 0 with an Approved test case; 0 traceability gaps.
- **Suite Planner**: Smoke: 0, Regression: 0, Full: 6 test cases.
- **AI review**: Ollama · qwen2.5:14b: 3 problems, 3 questions.

## Problems (9)

- **REQ-2 · Missing error handling**: no behavior for invalid input or errors stated for: sign in
- **REQ-5 · Missing expected result**: states no observable result: what the user or the system sees or gets afterwards
- **TC-001, TC-002, TC-003, TC-005, TC-006 · Steps**: these steps only refer to the requirement and name no concrete action or data: 1, 2, 3.
- **TC-004 · Steps**: these steps only refer to the requirement and name no concrete action or data: 2, 3.
- **REQ-3**: no test case at all, not even a Draft, for: Negative
- **REQ-4**: no test case at all, not even a Draft, for: Happy Path
- **REQ-2 · AI · Missing scenario**: The requirement does not specify what happens if a user tries to sign in with an invalid email.
- **REQ-5 · AI · Missing scenario**: The requirement does not specify what happens after a user deletes their account.
- **REQ-6 · AI · Missing scenario**: The requirement does not specify what happens if the user clicks the "go elsewhere" link while not signed in.

## Unknown (4)

- **TC-005 · Requirement match**: the requirement itself states no expected result, so the match cannot be checked.
- **REQ-2**: What should happen if a user tries to sign in with an invalid email?
- **REQ-5**: What should happen after a user deletes their account?
- **REQ-6**: What should happen if the user clicks the "go elsewhere" link while not signed in?

## Review status (not a problem of the requirements)

6 of 6 test cases are not Approved yet, and Scenario Coverage, Traceability, Suite Planner count only Approved test cases. Review and approve the test cases of REQ-1, REQ-2, REQ-3, REQ-4, REQ-5, REQ-6.

## Recommendations

- Clarify REQ-2, REQ-5 with the document author before writing or approving their test cases.
- Fix the problems in TC-001, TC-002, TC-003, TC-004, TC-005, TC-006 before approving them.
- Clarify the requirements behind the Unknown items, then review those test cases again.
- Add and approve test cases for the missing scenarios of REQ-3, REQ-4.
- Clarify the expected behavior for invalid email sign-in attempts, account deletion outcomes, and non-signed-in user actions on the "go elsewhere" link.
