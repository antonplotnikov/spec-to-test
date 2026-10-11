# Spec-to-Test v1.0.0

First public release of Spec-to-Test — a Streamlit app that analyzes software
requirements, scores their quality, generates reviewable test cases, and tracks
coverage. Interface in English, Ukrainian, and Russian.

## Highlights
- Rule-based analysis of ambiguity, missing results/boundaries/error handling, and contradictions.
- Explainable 0–100 quality score per requirement.
- Test case editor with Draft → Reviewed → Approved workflow.
- Test design: boundary values, equivalence classes, decision tables (no invented rules).
- Bug reports for requirement defects, RTM, and a filterable QA dashboard.
- Exports: Jira CSV, TestRail CSV, RTM CSV, Markdown QA report.
- Optional AI review (Anthropic) with per-run consent.

## Fixed since 0.2.0
- User text rendered as Markdown in tables; cross-visitor data exposure on shared hosting;
  AI consent persisting between runs; vulnerable dependency lower bounds. Full list in CHANGELOG.md.

## Known limitations
See the "Limitations" section of the README.
