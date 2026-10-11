# Spec-to-Test v1.1.0

Adds **Grill Mode**: an interactive QA interviewer that clarifies
requirements, builds or improves test cases and bug reports, and reviews
existing artifacts. Works fully without an API key; AI help is optional.

## Highlights
- Four workflows: clarify requirements, test case, bug report, QA review —
  from scratch (interview) or from your draft.
- One question at a time, each with the reason it matters; answers can be
  confirmed, kept as assumptions, marked unknown, or skipped. Back, edit and
  cancel at any point.
- Every value shows its origin (source, confirmed by you, assumption, AI
  suggestion, unknown). Unknown stays unknown; nothing is invented.
- Review with blocking issues, warnings and suggestions, reusing the rule
  engine. Nothing is finalized without explicit confirmation.
- Confirmed test cases and bug reports can be added to the workspace (RTM,
  coverage, Jira / TestRail / Markdown exports); every result can be
  downloaded as Markdown; clarified findings can be marked resolved, one by one.
- Optional AI assistant with consent for every request; AI questions are
  optional and AI findings never block.
- English, Ukrainian and Russian.

## Fixed
- BUG-008: Grill answers and draft fields are limited to 100,000 characters.

## Known limitations
See the "Limitations" section of the README. Grill Mode was tested headlessly
(Streamlit AppTest) and not yet in a real browser; AI was tested with a fake
client only.
