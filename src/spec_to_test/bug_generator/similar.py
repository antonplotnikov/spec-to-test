"""Possible duplicates of a product bug: saved reports whose text overlaps with a report being written.

Compared by the words of title, What, Where and Actual result (case ignored, short and common
words left out), as the overlap of the two word sets (Jaccard). A match is a question for the
reporter, not a verdict: nothing is merged, and the reports stay as they are.
"""

import re

from pydantic import BaseModel

from spec_to_test.bug_generator.models import ProductBugReport

SIMILAR_THRESHOLD = 0.5
MAX_MATCHES = 3
_WORD = re.compile(r"\w+")
_STOPWORDS = frozenset({
    # English
    "the", "and", "for", "with", "not", "that", "this", "from", "when", "after", "before", "are", "was",
    "were", "has", "have", "but", "its", "into", "than", "then", "there", "they", "their", "does", "did",
    # Russian
    "при", "что", "это", "как", "для", "или", "все", "его", "она", "они", "если", "после", "когда",
    # Ukrainian
    "або", "що", "це", "як", "коли", "після", "його", "вона", "вони", "якщо",
})


class SimilarReport(BaseModel):
    report_id: str
    title: str
    similarity: float  # 0-1


def _words(report: ProductBugReport) -> set[str]:
    text = " ".join([report.title, report.what, report.where, report.actual_result]).lower()
    return {word for word in _WORD.findall(text) if len(word) >= 3 and word not in _STOPWORDS}


def find_similar(report: ProductBugReport, saved: list[ProductBugReport]) -> list[SimilarReport]:
    """Saved reports (other than `report` itself) that may describe the same bug, most similar first."""
    words = _words(report)
    if not words:
        return []
    matches = []
    for other in saved:
        if other.id == report.id:
            continue
        other_words = _words(other)
        union = words | other_words
        if not other_words:
            continue
        similarity = len(words & other_words) / len(union)
        if similarity >= SIMILAR_THRESHOLD:
            matches.append(SimilarReport(report_id=other.id, title=other.title, similarity=round(similarity, 2)))
    return sorted(matches, key=lambda m: m.similarity, reverse=True)[:MAX_MATCHES]
