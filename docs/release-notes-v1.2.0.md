# Spec-to-Test v1.2.0

Adds the **QA Agent** (browser tests, autonomous QA, plain-text QA tasks), the
**Automation** tab, **projects**, more **AI providers** (including local models)
and a redesigned interface. Everything keeps working without an API key; AI
stays optional and asks for consent.

## Highlights
- **QA Agent page**
  - Plan, run and report browser tests from test cases (Python Playwright),
    with an allowlist, SSRF checks and a local Demo Shop to try it.
  - **Autonomous QA**: from a URL to discovered requirements, test cases, runs,
    triage and bug reports, each step reviewed by you.
  - **QA task** mode: a task in plain words (EN / UK / RU) is routed to the
    rule-based checks (requirement findings, Test Case Critic, Scenario
    Coverage, Change Impact, Traceability, Suite Planner) and summed up in one
    report that quotes the requirements and test cases it names, compares a
    rerun with the previous run, and keeps per-project memory.
  - **Generate missing test cases** from the result: the existing generator
    fills only the gaps, as Drafts, without duplicates and without guessing
    expected results of requirements that need clarification.
  - `on_change` CLI: run the QA task when a requirements document changes,
    with an optional AI review and a rule-based evaluation suite.
- **Automation tab**: an Approved test case becomes a validated Playwright
  test (Claude + Playwright MCP), approved by a person.
- **Projects**: group requirement documents by product or application.
- **AI providers**: Claude, OpenAI, any OpenAI-compatible server (LM Studio,
  vLLM, llama.cpp, LocalAI) and Ollama.
- **Grill Mode**: saved interviews, findings history with undo, audit trail,
  reactive questions, context-aware contradictions and a 30-case evaluation.
- **Test generation and design**: time and size limits ("within", "after",
  "не повинен перевищувати") are treated as limits, partial checks are marked,
  positive steps quote the user's action; TestRail export carries the
  requirement and open questions.
- Redesigned interface (dark sidebar, project/document switcher) and a macOS
  app build (`macos/build_app.sh`).

## Behavior changes
- Storage: `session` is the default mode; work is saved to disk only with
  `SPEC_TO_TEST_STORAGE=local` (see the CHANGELOG).
- Workspace and Grill session files are upgraded automatically on load.

## Known limitations
See the "Limitations" sections of the README and `docs/QA_AGENT.md`. The
missing-test-case generator only makes the case kinds the rule-based generator
already knows (positive, boundary, equivalence, decision table); permissions,
state transitions, recovery and negative cases without numbers are listed for
writing by hand. Full details are in [CHANGELOG.md](../CHANGELOG.md).
