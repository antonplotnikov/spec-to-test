Rules: precision 1.00, found 83/91; misses 8

| metric | rules | baseline_old | baseline_rerun | full | fewshot |
|---|---|---|---|---|---|
| lines |  | 22 | 23 | 19 | 26 |
| tp |  | 8 | 8 | 7 | 14 |
| dup |  | 0 | 0 | 3 | 0 |
| optional |  | 1 | 1 | 1 | 1 |
| outside |  | 0 | 0 | 0 | 1 |
| disputed |  | 0 | 0 | 1 | 1 |
| fp | 0 | 13 | 14 | 7 | 9 |
| precision | 1.00 | 0.38 | 0.36 | 0.47 | 0.56 |
| precision_manual |  | 0.38 | 0.36 | 0.5 | 0.62 |
| recall | 0.912 | 0.088 | 0.088 | 0.077 | 0.154 |
| recall_requirement_level |  | 8/32 | 8/32 | 7/32 | 13/32 |
| rule_misses_found |  | 0/8 | 1/8 | 1/8 | 0/8 |
| recall_rules_or_ai | 0.912 | 0.912 | 0.923 | 0.923 | 0.912 |
| units_trap | False | True | True | True | True |
| admin_session_trap | False | False | False | False | False |
| category_wrong_on_tp |  | 3 | 2 | 1 | 1 |
| lines_with_quote |  | 16 | 19 | 15 | 26 |
| rejected |  | 0 | 0 | 0 | 0 |
| questions |  | 11 | 13 | 13 | 10 |
| wall_s_total |  | 169.5 | 172.0 | 179.1 | 267.5 |
| prompt_tokens_max |  | None | 3848 | 6029 | 10727 |

baseline_old: rule misses found []; trap lines ['reference_spec: requirement REF-01', 'reference_spec: requirement REF-04', 'reference_spec: requirement REF-18', 'uk_units_ranges: contradiction REQ-3,REQ-4']

baseline_rerun: rule misses found ['reference_spec: missing_boundary REF-09']; trap lines ['reference_spec: requirement REF-01', 'reference_spec: requirement REF-04', 'reference_spec: requirement REF-15', 'uk_units_ranges: contradiction REQ-3,REQ-4']

full: rule misses found ['reference_spec: missing_boundary REF-09']; trap lines ['reference_spec: requirement REF-01', 'uk_units_ranges: contradiction REQ-3,REQ-4']

fewshot: rule misses found []; trap lines ['reference_spec: requirement REF-02', 'reference_spec: requirement REF-18', 'uk_units_ranges: contradiction REQ-3,REQ-4']
