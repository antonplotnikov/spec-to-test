"""Rule-based critic for test cases.

Checks one test case against its requirement and the other test cases:

- steps:             each step is a concrete action (no placeholder, no step
                     that only points back at the requirement, no vague words)
- expected_result:   the expected result is observable and checkable
- requirement_match: the test case talks about what its requirement says
- duplicate:         no other test case of the requirement has the same
                     steps and expected result
- unsupported:       the expected result does not add values or messages
                     the requirement never states

Only the texts at hand are used. Where they are not enough to judge (no
requirement, a requirement without an expected result, an outcome the
requirement leaves open) the issue is reported as Unknown instead of guessed.
"""

import re
from typing import Literal

from pydantic import BaseModel

from spec_to_test.i18n import TRANSLATIONS
from spec_to_test.models import ClarificationStatus, FindingType, TestCase, TestType, Workspace
from spec_to_test.rule_engine import _AMBIGUOUS, _OUTCOME, _QUOTED, STOPWORDS, _compile, _normalize, _stems

Criterion = Literal["steps", "expected_result", "requirement_match", "duplicate", "unsupported"]

# Steps shorter than this many words cannot say what to do and with what.
MIN_STEP_WORDS = 2

# Observable states missing from the shared outcome vocabulary, which also drives the
# requirement analyzer's rules: "otherwise the button must be hidden".
_OBSERVABLE_STATE = _compile(["hide", "hides", "hidden", "hiding", "скрыт*", "скрыва*", "прихов*"])
_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?")
_WORD = re.compile(r"\w+")
# Words plus what tells probe values apart: a minus sign ("-6" vs "6") and comparators ("> 5" vs "< 5").
_TOKEN = re.compile(r"(?<!\w)[-−](?=\d)|\w+|[<>≤≥=≠]")
# Test design derives its own probe values (limit ± 1, class representatives).
_DERIVED_VALUES = {TestType.BOUNDARY, TestType.EQUIVALENCE}


def _all_languages(key: str, **params: object) -> set[str]:
    return {text.format(**params).strip().lower() for text in TRANSLATIONS[key].values()}


class CriticIssue(BaseModel):
    criterion: Criterion
    # Translated as critic.<code>; params fill its placeholders.
    code: str
    # True when the texts are not enough to judge, as opposed to a found problem.
    unknown: bool = False
    params: dict[str, str] = {}


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) >= 4 and not w.isdigit() and w not in STOPWORDS}


def _normalized(text: str) -> str:
    return " ".join(_TOKEN.findall(text.lower().replace("−", "-")))


def _signature(tc: TestCase) -> tuple[str, ...]:
    return (*(_normalized(s) for s in tc.steps), _normalized(tc.expected_result))


def _step_issues(tc: TestCase) -> list[CriticIssue]:
    placeholders = _all_languages("tests.new_step")
    generic = (
        _all_languages("tc.step_prepare", req=tc.requirement_id)
        | _all_languages("tc.step_perform")
        | _all_languages("tc.step_observe")
    )
    issues = []
    generic_steps = []
    for n, step in enumerate(tc.steps, start=1):
        text = step.strip().lower()
        if text in placeholders:
            issues.append(CriticIssue(criterion="steps", code="step_placeholder", params={"step": str(n)}))
        elif text in generic:
            generic_steps.append(str(n))
        elif vague := _AMBIGUOUS.search(_QUOTED.sub(" ", _normalize(step))):
            issues.append(CriticIssue(criterion="steps", code="step_vague",
                                      params={"step": str(n), "term": vague.group(0)}))
        elif len(_WORD.findall(step)) < MIN_STEP_WORDS:
            issues.append(CriticIssue(criterion="steps", code="step_too_short", params={"step": str(n)}))
    if generic_steps:
        issues.append(CriticIssue(criterion="steps", code="step_generic", params={"steps": ", ".join(generic_steps)}))
    return issues


def _expected_issues(tc: TestCase) -> list[CriticIssue]:
    expected = _normalize(tc.expected_result)
    lowered = expected.lower()
    if lowered.strip() in _all_languages("tests.new_expected"):
        return [CriticIssue(criterion="expected_result", code="expected_placeholder")]
    if any(text in lowered for text in _all_languages("design.unspecified")):
        return [CriticIssue(criterion="expected_result", code="expected_unspecified", unknown=True)]
    if vague := _AMBIGUOUS.search(_QUOTED.sub(" ", expected)):
        return [CriticIssue(criterion="expected_result", code="expected_vague", params={"term": vague.group(0)})]
    if not (_OUTCOME.search(expected) or _OBSERVABLE_STATE.search(expected) or _NUMBER.search(expected)
            or _QUOTED.search(expected)):
        return [CriticIssue(criterion="expected_result", code="expected_not_observable")]
    return []


def critique(tc: TestCase, workspace: Workspace) -> list[CriticIssue]:
    """Problems and unknowns found in one test case, in criterion order."""
    issues = _step_issues(tc) + _expected_issues(tc)

    req = workspace.requirement(tc.requirement_id)
    if req is None:
        issues.append(CriticIssue(criterion="requirement_match", code="requirement_missing", unknown=True))
    else:
        no_expected = any(
            f.requirement_id == req.id and f.type == FindingType.MISSING_EXPECTED_RESULT
            and f.status == ClarificationStatus.NEEDS_CLARIFICATION
            for f in workspace.findings
        )
        own_text = " ".join([tc.title, *tc.steps, tc.expected_result])
        source = _normalize(req.text).lower()
        # Quoting the requirement's own wording ("boundary values for “not exceed 10 MB”") is a match.
        quotes_requirement = any(
            (quote := q[1:-1].strip().lower()) and quote in source for q in _QUOTED.findall(_normalize(own_text))
        )
        if no_expected:
            issues.append(CriticIssue(criterion="requirement_match", code="requirement_no_expected", unknown=True))
        elif not quotes_requirement and not _stems(_words(own_text)) & _stems(_words(req.text)):
            issues.append(CriticIssue(criterion="requirement_match", code="requirement_mismatch"))

    duplicates = [
        other.id for other in workspace.test_cases
        if other.id != tc.id and other.requirement_id == tc.requirement_id and _signature(other) == _signature(tc)
    ]
    if duplicates:
        issues.append(CriticIssue(criterion="duplicate", code="duplicate", params={"ids": ", ".join(duplicates)}))

    if req is not None:
        source = _normalize(req.text).lower()
        expected = _normalize(tc.expected_result)
        if tc.test_type not in _DERIVED_VALUES:
            stated = set(_NUMBER.findall(source))
            if invented := [n for n in dict.fromkeys(_NUMBER.findall(expected)) if n not in stated]:
                issues.append(CriticIssue(criterion="unsupported", code="invented_value",
                                          params={"values": ", ".join(invented)}))
        for quote in _QUOTED.findall(expected):
            if quote[1:-1].strip().lower() not in source:
                issues.append(CriticIssue(criterion="unsupported", code="invented_text", params={"text": quote}))
    return issues
