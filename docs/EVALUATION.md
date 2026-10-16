# Grill AI quality evaluation

The evaluation suite measures the Grill Mode interviewer and its AI helpers on
fixed requirement documents, through exactly the code the app runs. It answers
two questions with numbers instead of impressions:

1. Does the interview ask the right questions — relevant, not repeated, covering
   what a reviewer would ask, never re-asking what was already resolved (before
   or during the interview), never asking what a reviewer would not ask?
2. Does the rule engine find the real contradictions — and only those?
3. Does anything the model invents reach the user?

## Running it

```bash
cd src
python -m spec_to_test.evaluation              # scripted model (deterministic, offline)
python -m spec_to_test.evaluation --rules-only # no AI: the built-in questions only
python -m spec_to_test.evaluation --live       # the provider configured by AI_PROVIDER + key
python -m spec_to_test.evaluation --json out.json --markdown out.md
```

The command prints a Markdown table per case and in total, lists every
uncovered gold issue, every hallucination the filters caught and every model
error, and exits with 1 when a threshold for the mode is missed (2 when
`--live` has no provider).

In pytest, `tests/test_evaluation.py` runs the scripted and rule-only suites and
checks thresholds, determinism, API-failure recovery, that every planted
hallucination is caught, that findings changed mid-interview update the queue,
that one answer can settle another question, and that model repeats and false
dilemmas are dropped. In CI both deterministic suites run after the tests; the
step fails when a threshold is missed, and both tables are appended to the job
summary (JSON and Markdown are uploaded as artifacts). `tests/test_evaluation_live.py` (marker `live_ai`) runs
the live suite; it is skipped unless `SPEC_TO_TEST_LIVE_AI=1` and a provider is
configured, and is never run in CI:

```bash
SPEC_TO_TEST_LIVE_AI=1 AI_PROVIDER=anthropic ANTHROPIC_API_KEY=... pytest -m live_ai -s
```

## What one case run does

1. Parse the case's requirements with the app's input parser and start a
   Requirements Grill (`settled` findings are passed as already resolved).
2. Loop: apply the case's `steps` that are due (findings resolved or reopened
   in the document after N answers, through `GrillWorkflow.sync_settled`, as
   the page does); ask the AI interviewer once per interview state (like the
   page), merge its question into the ranked queue, then answer the current
   question as the scripted author would (by question ID or a phrase in the
   question; anything else is answered *unknown* — the author never invents).
3. Run the deterministic review and the AI review, then the rule-based and AI
   test case suggestions.
4. Score: every asked question, every raw model item (seen through the
   `on_response` hook before any filtering), every accepted AI item, the
   contradicting pairs the rule engine reports for the document, and the
   numbers in the clarified requirements.

The scripted model (`evaluation/scripted.py`) answers through the same
`messages.parse(...)` call as the Anthropic SDK, so `request_structured`,
schema validation and error mapping are exercised as in production. A reply
`{"error": "rate_limit"}` simulates an API failure.

## Metrics

| Metric | Numerator / denominator |
|---|---|
| relevance | asked questions that address a gold issue / asked questions |
| duplication | asked questions repeating an earlier one about the same requirement / asked |
| coverage | gold issues addressed by an asked question / gold issues |
| resolved_reasked | asked questions whose finding was resolved in the document when asked (before the interview or by a `steps` change) / asked |
| false_positive_rate | `must_not_ask` traps an asked question fell into / traps |
| contradiction_recall | gold contradicting pairs the rule engine reports / gold pairs |
| contradiction_precision | reported pairs that are gold pairs / reported pairs (a `non_contradictions` pair, or any pair nobody judged contradictory, counts against it) |
| hallucination_raw | raw model items with an invented requirement ID, a number not in the input, or a quote/basis not in the input / raw items |
| hallucination_accepted | the same check on what passed the trust filters / accepted AI items |
| test_case_quality | passed checks / checks over suggested test cases (steps, expected result, real requirement, traceable basis, no invented number — for rule-based tests, values derived by the test design from the requirement count as known) |
| test_coverage | requirements with a suggested test case / requirements |
| invented_requirements | requirement IDs in the trace, findings or test cases that the document lacks (count) |
| invented_values | numbers in the clarified requirements that neither the document nor an answer contains (count) |
| progress_regressions | times the number of handled questions went down during the interview (count) |
| ai_errors | failed model calls (count) |

A question *addresses* a gold issue when it is linked to one of the issue's
requirements and its category (rule finding type, `contradiction`, `clarity`,
`boundary`) is one of the issue's topics or its text contains one of the
issue's keywords. Ratios with nothing to measure are reported as `—` and not
checked.

## The cases

Thirty cases (13 English, 10 Russian — one mixing Latin and Cyrillic units —
and 7 Ukrainian), each judged by a person:

| Scenario | Cases |
|---|---|
| ambiguity and missing outcomes / limits / error paths | all |
| contradictions, incl. ranges, units and currencies | `password_reset`, `checkout_ru`, `en_free_shipping_contexts`, `en_equivalent_units`, `en_ranges`, `ru_currency_contexts`, `ru_time_units`, `ru_duplicates_ai`, `uk_currency_contexts`, `uk_units_ranges`, `mixed_attachments_currencies` |
| look-alikes that are not contradictions (other scope or condition, equal values in other units, other currencies) | the same, via `non_contradictions` |
| irrelevant-question traps (`must_not_ask`) | `en_irrelevant_traps`, `ru_irrelevant_traps`, `uk_irrelevant_traps`, and traps in 12 more cases |
| one answer settles another question | `en_answered_elsewhere`, `ru_answered_elsewhere`, `uk_answered_elsewhere` |
| multi-step interviews (an answer contradicts a requirement, a vague answer gets a follow-up) | `en_answer_conflict_multistep`, `ru_answer_conflict_multistep`, `uk_answer_conflict_multistep` |
| findings resolved / reopened during the interview (`steps`) | `en_reopen_mid_interview`, `ru_reopen_steps`, `uk_reopen_steps`; resolved before: `password_reset_resumed` |
| duplicates (duplicate requirements, model repeats, false dilemmas) | `en_duplicates`, `ru_duplicates_ai`, `en_equivalent_units`, `uk_units_ranges` |
| hallucinations (invented IDs, numbers, quotes, unsupported tests) | `password_reset`, `en_hallucinations`, `ru_hallucinations`, `uk_hallucinations_api` |
| model failures (rate limit, connection, server, authentication) | `file_upload_api_failure`, `en_api_failures`, `ru_hallucinations`, `uk_hallucinations_api` |

## Current results

Totals over the 30 cases. "Before" is the same suite run against the code
before Grill Mode v2.1 (mid-interview finding changes had no effect then, as in
the app).

| | relevance | coverage | false positives | contradiction recall / precision | resolved re-asked | duplication | hallucination raw → accepted | invented IDs / values | progress regressions |
|---|---|---|---|---|---|---|---|---|---|
| rules only, before | 0.67 | 0.72 | 0.62 | 0.33 / 0.83 | 0.02 | 0 | — | 0 / 0 | 0 |
| rules only, after | 0.97 | 0.83 | 0 | 1.00 / 1.00 | 0 | 0 | — | 0 / 0 | 0 |
| with AI (scripted), before | 0.70 | 0.89 | 0.62 | 0.33 / 0.83 | 0.02 | 0 | 0.31 → 0 | 0 / 0 | 0 |
| with AI (scripted), after | 0.96 | 0.99 | 0 | 1.00 / 1.00 | 0 | 0 | 0.29 → 0 | 0 / 0 | 0 |

On the original four cases alone, rules-only relevance went from 0.76 to 0.89
and scripted relevance from 0.81 to 0.91 (coverage unchanged: 1.00 with AI).

What is still not covered (rules only): expiry and lock-out paths (*what
happens with an expired link*, *how is a locked account unlocked*), behavior
outside a stated length when the requirement names no input action, duplicate
requirements, and the violation path of a rate limit — the scripted AI
questions close all of these except the last one (`ru_time_units`, REQ-5).

These numbers describe the fixtures and the scripted replies, not a real
model. The fixtures were written together with the v2.1 rule changes, so the
"after" numbers are an upper bound for unseen documents; they guard against
regressions in the pipeline, the rules and the trust filters. Run `--live` to
measure a real provider.

## Adding a case

Add a JSON file to `src/spec_to_test/evaluation/fixtures/` (see the existing
ones and `evaluation/cases.py`): the requirements text; gold issues judged by a
person (requirement IDs, acceptable topics, keywords, a note); the
contradicting pairs and the look-alike pairs that must not be flagged;
`must_not_ask` traps (same shape as an issue); optional `settled` findings and
`steps` (`{"after": 2, "resolve": [...], "reopen": [...]}`); the scripted
answers; and scripted model replies per request type (`interview`,
`questions`, `review`, `test_cases`, `{"error": "<code>"}` for a failure).
Label what a reviewer would ask, not what the engine happens to ask. Then run
the suite and, if the new case changes the totals, adjust `thresholds.json`
deliberately.

## QA Agent evaluation

A separate, rule-based evaluation of the QA task agent (`qa_agent/tasks.py`)
against the known problems of five documents: `examples/password_reset.md`,
`examples/qa_demo/requirements.md`, `tests/fixtures/reference_spec.md` and the
requirements of the Grill cases `03_checkout_ru` and `24_uk_units_ranges`.

```bash
cd src
python -m spec_to_test.evaluation.qa_agent_eval
python -m spec_to_test.evaluation.qa_agent_eval --json out.json --markdown out.md
```

Each document is analyzed as the on-change run does (rule engine and generated
test cases), the agent runs "Full check", and its output is scored against
`evaluation/qa_agent_gold.json`: per document, the problems of the requirements
(contradiction, ambiguous wording, missing error handling, missing boundary,
missing expected result) and of the generated test cases (template test case,
expectation conflict, boundary semantics — "within / after / not exceed"
treated as equality), with the affected IDs and the trap each belongs to, plus
`must_not` traps (equal values in other units, another scope, clear
requirements, correct boundary probes). Requirement problems of the reference
spec are those of `tests/test_reference_spec.py`; those of the Grill cases agree
with their gold (checked by `tests/test_qa_agent_eval.py`).

Scoring rules: only explicit problems count as found — an Unknown pointing at a
gold problem is listed as "Unknown only" and does not raise recall; a problem
reported again (both sides of a contradiction, two test cases of one boundary
problem, an identical line) is a duplicate, neither a true nor a false positive;
optional (debatable) gold problems are neutral; a line the agent merged (one
remark on several IDs) is scored as one line per ID; lines that only say a test
case is not Approved yet (coverage, traceability, suites) are outside
precision — the agent sums them up apart from the problems (column "Not
Approved (apart)"), and any left among the problems is status noise; scenarios
no generated test case covers are not in the gold and not scored. Precision and recall are reported per kind, in total
(micro) and as the mean over kinds (macro), and per trap.

A boundary problem of generated test cases carries `expect`: its note restated
as probe value → whether the requirement's statement holds there (`"29": false,
"31": true` for "expires after 30 minutes"). When the generated test cases give
every listed value that outcome and leave no value "not specified", the problem
is *resolved*: it counts towards recall (the reader no longer has it), is listed
apart and adds nothing to precision. A `must_not` boundary entry with `expect`
is a correct test case (the "не менее 500" or "8–64" probes); if the generated
test cases stop matching it, that is a *regression* (threshold `regressions`
max 0).

A document whose content changed, or a gold test case ID that now names
another requirement or test type, stops the run with exit code 2: the gold is
stale and has to be checked again. Thresholds are in the gold file (exit code 1
when one is missed); they are a regression floor at the current level, not a
quality target.

Limits of the gold: one reviewer's judgement on five small documents; problems
of generated test cases are tied to the current generator's test case IDs;
missing boundary tests (e.g. no test for "after 5 failed attempts") and
non-executable QA steps are not labeled.
