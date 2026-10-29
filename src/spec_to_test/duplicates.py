"""Possible duplicate requirements: two requirements of one document that may say the same thing.

Found by wording only, so nothing about meaning is guessed:
- exact: the same words after ignoring case, punctuation and spacing;
- near:  a wording similarity of at least NEAR_THRESHOLD (one word changed, a copied sentence).

A pair is a question for the BA/PO, not a finding: nothing is merged or removed, and the
quality scores do not change.
"""

import re
from difflib import SequenceMatcher

from pydantic import BaseModel

from spec_to_test.models import Requirement
from spec_to_test.rule_engine import _normalize

NEAR_THRESHOLD = 0.9
_PUNCTUATION = re.compile(r"[\W_]+")


class DuplicatePair(BaseModel):
    first_id: str
    second_id: str
    similarity: float  # 0-1, of the wording after normalization
    exact: bool


def _wording(text: str) -> str:
    return _PUNCTUATION.sub(" ", _normalize(text).lower()).strip()


def find_duplicates(requirements: list[Requirement]) -> list[DuplicatePair]:
    """Pairs of requirements (in document order) whose wording is the same or nearly the same."""
    pairs = []
    wordings = [(req, _wording(req.text)) for req in requirements]
    for i, (first, first_text) in enumerate(wordings):
        for second, second_text in wordings[i + 1:]:
            if first.id == second.id or not first_text or not second_text:
                continue
            if first_text == second_text:
                pairs.append(DuplicatePair(first_id=first.id, second_id=second.id, similarity=1.0, exact=True))
                continue
            # The ratio is at most 2 * shorter / (both lengths), so a length gap below 0.8 cannot reach NEAR_THRESHOLD.
            if min(len(first_text), len(second_text)) / max(len(first_text), len(second_text)) < 0.8:
                continue
            ratio = SequenceMatcher(None, first_text, second_text).ratio()
            if ratio >= NEAR_THRESHOLD:
                pairs.append(DuplicatePair(first_id=first.id, second_id=second.id,
                                           similarity=round(ratio, 2), exact=False))
    return pairs
