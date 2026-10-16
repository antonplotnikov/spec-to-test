"""Run one AI review variant on the five eval documents through the local Ollama (no other network).

    cd experiments/ai_review_2026-10-16
    PYTHONPATH=../../src ../../.venv/bin/python run_variants.py <variant> [--model qwen2.5:14b]

Variants (the system prompt and the checks of the reply are the app's own):
- baseline_rerun: the app's message (title + expected result per test case), to check the old runs repeat;
- full: every test case field (test type, preconditions, steps), no assumptions/clarification questions;
- fewshot: "full" + three labelled examples (fewshot_examples.json) after the system prompt.

Every run writes runs/<variant>/<document>/: request.json, response_raw.json (Ollama's whole reply),
review.json (parsed reply), items.json (each item accepted or rejected, with the reason) and metrics.json.
An existing run directory is never overwritten: the script stops instead.
"""

import argparse
import json
import subprocess
import sys
import time

from common import GRILL_FIXTURES, HERE, eval_documents, full_message, sha

from spec_to_test.llm.providers import AIError, OllamaClient, _parse_json
from spec_to_test.models import Workspace
from spec_to_test.qa_agent.ai_review import (
    LANGUAGE_NAMES,
    MAX_TOKENS,
    SYSTEM,
    AIReview,
    _clean,
    _known,
    _normalized,
    _texts,
    build_message,
    to_step,
)
from spec_to_test.qa_agent.on_change import build_workspace

BASE_URL = "http://127.0.0.1:11434"
TIMEOUT = 900.0

FEWSHOT_HEADER = """

Examples of good reviews of other documents follow. Each example answer lists only the requirement
problems known for that document; it says nothing about the example's test cases, which you still review
as described above."""


def fewshot_system(language: str) -> str:
    data = json.loads((HERE / "fewshot_examples.json").read_text(encoding="utf-8"))
    parts = [SYSTEM.format(language=language), FEWSHOT_HEADER]
    for n, example in enumerate(data["examples"], 1):
        case = json.loads((GRILL_FIXTURES / f"{example['case']}.json").read_text(encoding="utf-8"))
        workspace = build_workspace(case["requirements"], example["case"], example["language"])
        answer = {key: [{k: v for k, v in item.items() if k != "source"} for item in items]
                  for key, items in example["answer"].items()}
        parts.append(f"\n\n### Example {n}\nInput:\n{full_message(workspace)}\nAnswer:\n"
                     + json.dumps(answer, ensure_ascii=False))
    parts.append("\n\n### End of examples. Review the specification in the user message.")
    return "".join(parts)


def judge_items(review: AIReview, workspace: Workspace) -> list[dict[str, object]]:
    """Each item of the reply with the decision of ai_review.to_step and its reason."""
    texts = _texts(workspace, None)
    out: list[dict[str, object]] = []
    for kind, items in (("problem", review.problems), ("question", review.questions),
                        ("recommendation", review.recommendations)):
        for n, item in enumerate(items):
            raw = item.model_dump()
            ids = _known(item.ids, texts)
            unknown = [i for i in item.ids if i.strip() not in texts]
            reason = ""
            if kind == "problem":
                quote = _clean(item.quote)  # type: ignore[union-attr]
                if not ids:
                    reason = "no known ID"
                elif not _clean(item.description):  # type: ignore[union-attr]
                    reason = "empty description"
                elif quote and not any(_normalized(quote) in _normalized(t) for i in ids for t in texts[i]):
                    reason = "quote not in the cited IDs' texts"
            elif kind == "question":
                if not ids:
                    reason = "no known ID"
            elif item.ids and not ids:
                reason = "only unknown IDs"
            out.append({"kind": kind, "n": n, "accepted": not reason, "reason": reason,
                        "dropped_unknown_ids": unknown, **raw})
    return out


def ollama_ps() -> str:
    return subprocess.run(["ollama", "ps"], capture_output=True, text=True, check=False).stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=["baseline_rerun", "full", "fewshot"])
    parser.add_argument("--model", default="qwen2.5:14b")
    parser.add_argument("--only", nargs="*", help="document names (default: all five)")
    args = parser.parse_args()
    client = OllamaClient(BASE_URL, timeout=TIMEOUT)
    for doc, workspace in eval_documents():
        if args.only and doc.name not in args.only:
            continue
        out = HERE / "runs" / f"{args.variant}__{args.model.replace(':', '_').replace('/', '_')}" / doc.name
        if out.exists():
            print(f"{out} exists, not overwriting", file=sys.stderr)
            return 1
        out.mkdir(parents=True)
        language = LANGUAGE_NAMES[doc.language]
        system = fewshot_system(language) if args.variant == "fewshot" else SYSTEM.format(language=language)
        message = build_message(workspace, None) if args.variant == "baseline_rerun" else full_message(workspace)
        request = {"model": args.model, "variant": args.variant, "document": doc.name, "language": doc.language,
                   "system": system, "message": message, "system_sha": sha(system), "message_sha": sha(message),
                   "options": {"temperature": 0, "num_predict": MAX_TOKENS}}
        (out / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=1), encoding="utf-8")
        started = time.time()
        error = ""
        try:
            data = client.chat(model=args.model, messages=[{"role": "system", "content": system},
                                                           {"role": "user", "content": message}],
                               schema=AIReview.model_json_schema(), max_tokens=MAX_TOKENS)
        except AIError as exc:
            data, error = {}, exc.code
        wall = round(time.time() - started, 1)
        (out / "response_raw.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        review = None
        if not error:
            if data.get("done_reason") == "length":
                error = "truncated"
            else:
                try:
                    review = _parse_json((data.get("message") or {}).get("content"), AIReview)
                except AIError as exc:
                    error = exc.code
        metrics: dict[str, object] = {
            "wall_s": wall, "error": error, "done_reason": data.get("done_reason"),
            "prompt_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count"),
            "total_s": round(data.get("total_duration", 0) / 1e9, 1), "ollama_ps": ollama_ps(),
        }
        if review is not None:
            (out / "review.json").write_text(review.model_dump_json(indent=1), encoding="utf-8")
            items = judge_items(review, workspace)
            (out / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
            step = to_step(review, workspace, None, f"Ollama · {args.model}")
            metrics |= {"accepted_problems": len(step.problems), "accepted_questions": len(step.unknowns),
                        "rejected": int(step.summary.params["rejected"]) if step.summary else 0,
                        "rejected_by_reason": [i["reason"] for i in items if not i["accepted"]]}
        (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
        print(doc.name, json.dumps({k: v for k, v in metrics.items() if k != "ollama_ps"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
