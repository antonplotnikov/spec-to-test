# AI review (Ollama qwen2.5:14b) vs gold vs rule-based — 2026-10-16

Setup: on_change CLI `--ai`, AI_PROVIDER=ollama, OLLAMA_MODEL=qwen2.5:14b, AI_TIMEOUT=900,
server OLLAMA_CONTEXT_LENGTH=16384 (ollama ps: ctx 16384, 100% GPU). One run per document, prompt/code unchanged
(ai_review.py mtime 10:27 local, before all runs). reference_spec from the earlier run f983f7e945094f37 (11:00 local).
Rule-based: `python -m spec_to_test.evaluation.qa_agent_eval` → rule-eval.json / rule-eval.md (all thresholds met).

| Doc | time | AI problems | rejected | verdict per line |
|---|---|---|---|---|
| password_reset | 30 s | 3 | 0 | contra REQ-4/7 TP; REQ-5 "fast/user-friendly" TP (labelled test_gap); REQ-6 no number TP (labelled test_gap) |
| qa_demo | 16 s | 3 | 0 | REQ-2 invalid email = optional (neutral); REQ-5 outcome of deletion TP; REQ-6 "while not signed in" FP (invented dimension) |
| reference_spec | 49 s | 7 | 0 | REF-13/14 TP; REF-11/12 TP (labelled ambiguity); REF-01 invalid email FP per gold (real issue, belongs to REF-20); REF-04 FP; REF-18 "no test" FP (TC-030); TC-017, TC-020 "test gap" FP |
| checkout_ru | 23 s | 3 | 0 | contra REQ-3/4 TP; TC-006 vs REQ-3 FP ×2 (same text, IDs REQ-4 vs REQ-3) |
| uk_units_ranges | 51 s | 6 | 0 | contra REQ-1/2 TP; REQ-3/4 "contradiction" FP (must_not trap 1 МБ = 1024 КБ); TC-003/006/009/012 "test gap" FP ×4 |

Totals: 22 lines = 8 TP + 1 neutral + 13 FP → precision 0.38 (rule-based 1.00).
Requirement-level recall: AI 8/32 = 0.25, rule-based 25/32 = 0.78. TC-level: expectation_conflict AI 0/4 (rule 3/4),
template_test_case AI 0/46 (steps not in the prompt; rule 46/46). AI found 0 required gold problems the rules missed.
Not in gold, missed by both: REF-04 (5 attempts) vs REF-18 (3 attempts).
