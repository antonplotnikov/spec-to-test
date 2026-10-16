"""Shared helpers of the 2026-10-16 AI review experiment (local Ollama only).

Run from the repository root with PYTHONPATH=src. Nothing here changes the app:
the production prompt and checks (spec_to_test.qa_agent.ai_review) are reused,
the experimental variants only build a different system prompt or message.
"""

import hashlib
import json
from pathlib import Path

from spec_to_test.evaluation.qa_agent_eval import GoldDocument, load_gold
from spec_to_test.models import Workspace
from spec_to_test.qa_agent.on_change import build_workspace

HERE = Path(__file__).resolve().parent
GRILL_FIXTURES = HERE.parents[1] / "src" / "spec_to_test" / "evaluation" / "fixtures"
# Grill eval cases that are (or contain) one of the five QA Agent eval documents:
# never used for few-shot examples or training (leakage).
EVAL_OVERLAP = {"01_password_reset", "03_checkout_ru", "04_password_reset_resumed", "24_uk_units_ranges"}


def eval_documents() -> list[tuple[GoldDocument, Workspace]]:
    """The five gold documents with the workspace the QA Agent eval builds for them."""
    return [(doc, build_workspace(doc.text(), doc.name, doc.language)) for doc in load_gold().documents]


def full_payload(workspace: Workspace) -> dict[str, object]:
    """Requirements and test cases with every field a reviewer needs; no assumptions,
    clarification questions or rule findings (they are derived from the rule engine)."""
    return {
        "document": workspace.title,
        "requirements": [{"id": r.id, "text": r.text} for r in workspace.requirements],
        "test_cases": [
            {"id": tc.id, "requirement_id": tc.requirement_id, "test_type": tc.test_type.value, "title": tc.title,
             "preconditions": tc.preconditions, "steps": tc.steps, "expected_result": tc.expected_result,
             "review_status": tc.review_status.value}
            for tc in workspace.test_cases
        ],
        "changes_since_previous_version": None,
    }


def full_message(workspace: Workspace) -> str:
    return ("Review this specification (JSON):\n<specification>\n"
            + json.dumps(full_payload(workspace), ensure_ascii=False, indent=1) + "\n</specification>")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
