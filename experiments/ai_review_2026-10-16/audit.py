"""Data audit: what labelled data the project has for the AI review (prints a summary)."""

import json
import re
from collections import Counter

from common import EVAL_OVERLAP, GRILL_FIXTURES, eval_documents

print("## QA Agent gold (5 eval documents)")
req_kinds = {"contradiction", "ambiguous_wording", "missing_error_handling", "missing_boundary", "missing_expected_result"}
tot: Counter[str] = Counter()
for doc, ws in eval_documents():
    req = [p for p in doc.problems if not p.optional and p.kind in req_kinds]
    tc = [p for p in doc.problems if not p.optional and p.kind not in req_kinds]
    opt = [p for p in doc.problems if p.optional]
    clear = {i for m in doc.must_not if m.kind == "requirement" for i in m.ids}
    flagged = {i for p in doc.problems for i in p.ids if i.startswith(("REQ", "REF"))}
    no_label = [r.id for r in ws.requirements if r.id not in flagged and r.id not in clear]
    print(f"{doc.name}: reqs {len(ws.requirements)}, TCs {len(ws.test_cases)}, required req-problems {len(req)}, "
          f"required TC-problems {len(tc)} ({Counter(p.kind for p in tc)}), optional {len(opt)}, must_not {len(doc.must_not)}, "
          f"explicitly clear reqs {len(clear)}, reqs with no label at all {no_label}")
    tot.update({"docs": 1, "reqs": len(ws.requirements), "tcs": len(ws.test_cases), "req_problems": len(req),
                "tc_problems": len(tc), "optional": len(opt), "must_not": len(doc.must_not)})
print(dict(tot))

print("\n## Grill eval cases (requirement-level gold only, no test case labels)")
pool: Counter[str] = Counter()
langs: Counter[str] = Counter()
families: Counter[str] = Counter()
for path in sorted(GRILL_FIXTURES.glob("*.json")):
    if path.stem in EVAL_OVERLAP:
        continue
    case = json.loads(path.read_text(encoding="utf-8"))
    gold = case["gold"]
    n_req = len(re.findall(r"^REQ-\d+", case["requirements"], re.M))
    langs[case["language"]] += 1
    families[re.sub(r"^\d+_(en|ru|uk|mixed)_", "", path.stem)] += 1
    untyped = sum(1 for i in gold.get("issues", []) if not i["topics"])
    pool.update({"docs": 1, "reqs": n_req, "issues": len(gold.get("issues", [])), "issues_without_topic": untyped,
                 "contradictions": len(gold.get("contradictions", [])),
                 "non_contradictions": len(gold.get("non_contradictions", [])),
                 "must_not_ask": len(gold.get("must_not_ask", [])), "has_settled": bool(case.get("settled")),
                 "has_steps": bool(case.get("steps"))})
print(dict(pool), dict(langs))
print("families:", dict(families))
