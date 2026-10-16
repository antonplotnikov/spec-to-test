"""Score the judged AI variants against qa_agent_gold.json and the rule-based eval (rules_eval.json).

    cd experiments/ai_review_2026-10-16 && PYTHONPATH=../../src ../../.venv/bin/python score.py

Metric definitions follow evaluation/qa_agent_eval.py: precision = TP / (TP + FP) where every line that is
not a required gold problem, a duplicate or an optional problem is a false positive; recall = required gold
problems found / required. "Manual precision" additionally credits lines checked by hand as real problems
outside the gold and leaves disputed lines out. Writes results.json and prints a Markdown summary.
"""

import json
from collections import Counter
from typing import Any

from common import HERE

from spec_to_test.evaluation.qa_agent_eval import REQUIREMENT_KINDS, load_gold

DOCS = ["password_reset", "qa_demo", "reference_spec", "checkout_ru", "uk_units_ranges"]
# Wall time of the old runs (ai-runs.log of the earlier session; reference_spec from its run log).
OLD_WALL = {"password_reset": 30.4, "qa_demo": 16.1, "reference_spec": 49.0, "checkout_ru": 23.2,
            "uk_units_ranges": 50.8}


def key(problem: Any) -> str:
    return f"{problem.kind} {','.join(problem.ids)}"


def ai_lines(variant: str, doc: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Accepted AI problem lines (with their quote) and the run's metrics."""
    folder = HERE / "runs" / f"{variant}__qwen2.5_14b" / doc
    if variant == "baseline_old":
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        step = next(s for s in result["steps"] if s["tool"] == "ai")
        lines = [{"quote": p["params"].get("quote", ""), "category": p["topic"].rsplit(".", 1)[-1]}
                 for p in step["problems"]]
        return lines, {"wall_s": OLD_WALL[doc], "rejected": int(step["summary"]["params"]["rejected"]),
                       "questions": len(step["unknowns"])}
    items = json.loads((folder / "items.json").read_text(encoding="utf-8"))
    metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
    lines = [i for i in items if i["kind"] == "problem" and i["accepted"]]
    metrics["questions"] = sum(1 for i in items if i["kind"] == "question" and i["accepted"])
    return lines, metrics


def main() -> None:
    gold = {d.name: d for d in load_gold().documents}
    rules = {d["name"]: d for d in json.loads((HERE / "rules_eval.json").read_text(encoding="utf-8"))["documents"]}
    judgements = json.loads((HERE / "judgements.json").read_text(encoding="utf-8"))["variants"]
    required = {doc: {key(p): p for p in gold[doc].problems if not p.optional} for doc in DOCS}
    optional = {doc: {key(p) for p in gold[doc].problems if p.optional} for doc in DOCS}
    rule_missed = {doc: {m.split(" — ")[0].replace(", ", ",") for m in rules[doc]["missed"]} for doc in DOCS}
    rule_missed = {doc: {k for k in required[doc] if k in missed} for doc, missed in rule_missed.items()}
    n_required = sum(len(r) for r in required.values())
    n_required_req = sum(1 for r in required.values() for p in r.values() if p.kind in REQUIREMENT_KINDS)
    n_rule_missed = sum(len(m) for m in rule_missed.values())
    out: dict[str, Any] = {"required": n_required, "required_requirement_level": n_required_req,
           "rules_found": n_required - n_rule_missed, "rule_missed": {d: sorted(m) for d, m in rule_missed.items()},
           "variants": {}}
    for variant, docs in judgements.items():
        verdicts: Counter[str] = Counter()
        traps: list[str] = []
        found: set[tuple[str, str]] = set()
        category_wrong = quotes = lines_total = rejected = questions = 0
        wall: list[float] = []
        prompt_tokens: list[int] = []
        for doc in DOCS:
            lines, metrics = ai_lines(variant, doc)
            judged = docs[doc]
            assert [j["n"] for j in judged] == list(range(len(lines))), (variant, doc, len(lines))
            lines_total += len(lines)
            quotes += sum(1 for line in lines if line.get("quote"))
            rejected += int(metrics.get("rejected", 0))
            questions += metrics["questions"]
            wall.append(metrics["wall_s"])
            if metrics.get("prompt_tokens"):
                prompt_tokens.append(metrics["prompt_tokens"])
            for j in judged:
                verdicts[j["verdict"]] += 1
                if j["verdict"] == "tp":
                    assert j["gold"] in required[doc], (variant, doc, j)
                    assert (doc, j["gold"]) not in found, ("tp twice", variant, doc, j)
                    found.add((doc, j["gold"]))
                    category_wrong += j.get("category_ok") is False
                if j["verdict"] == "optional":
                    assert j["gold"] in optional[doc], (variant, doc, j)
                if "trap" in j:
                    traps.append(f"{doc}: {j['trap']}")
        tp, fp = verdicts["tp"], verdicts["fp"]
        strict_den = tp + fp + verdicts["outside"] + verdicts["disputed"]
        manual_den = tp + verdicts["outside"] + fp
        found_req = sum(1 for doc, k in found if required[doc][k].kind in REQUIREMENT_KINDS)
        beyond = sorted(f"{doc}: {k}" for doc, k in found if k in rule_missed[doc])
        out["variants"][variant] = {
            "lines": lines_total, **{v: verdicts[v] for v in ("tp", "dup", "optional", "outside", "disputed", "fp")},
            "precision": round(tp / strict_den, 2) if strict_den else None,
            "precision_manual": round((tp + verdicts["outside"]) / manual_den, 2) if manual_den else None,
            "recall": round(len(found) / n_required, 3), "recall_requirement_level": f"{found_req}/{n_required_req}",
            "rule_misses_found": f"{len(beyond)}/{n_rule_missed}", "rule_misses_found_list": beyond,
            "recall_rules_or_ai": round((n_required - n_rule_missed + len(beyond)) / n_required, 3),
            "trap_lines": traps, "units_trap": any("contradiction REQ-3,REQ-4" in t for t in traps),
            "admin_session_trap": any("contradiction REQ-5,REQ-6" in t for t in traps),
            "category_wrong_on_tp": category_wrong, "lines_with_quote": quotes, "rejected": rejected,
            "questions": questions, "wall_s_total": round(sum(wall), 1),
            "prompt_tokens_max": max(prompt_tokens) if prompt_tokens else None,
        }
    (HERE / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = ["lines", "tp", "dup", "optional", "outside", "disputed", "fp", "precision", "precision_manual",
            "recall", "recall_requirement_level", "rule_misses_found", "recall_rules_or_ai", "units_trap",
            "admin_session_trap", "category_wrong_on_tp", "lines_with_quote", "rejected", "questions",
            "wall_s_total", "prompt_tokens_max"]
    names = list(out["variants"])
    print(f"Rules: precision 1.00, found {out['rules_found']}/{n_required}; misses {n_rule_missed}\n")
    print("| metric | rules | " + " | ".join(names) + " |")
    print("|---|---|" + "---|" * len(names))
    rule_col = {"precision": "1.00", "recall": f"{out['rules_found'] / n_required:.3f}", "fp": "0",
                "recall_rules_or_ai": f"{out['rules_found'] / n_required:.3f}", "units_trap": "False",
                "admin_session_trap": "False"}
    for row in rows:
        print(f"| {row} | {rule_col.get(row, '')} | " + " | ".join(str(out["variants"][n][row]) for n in names) + " |")
    for name in names:
        v = out["variants"][name]
        print(f"\n{name}: rule misses found {v['rule_misses_found_list']}; trap lines {v['trap_lines']}")


if __name__ == "__main__":
    main()
