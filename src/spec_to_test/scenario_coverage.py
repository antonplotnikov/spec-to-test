"""Scenario coverage: which kinds of test scenarios a requirement needs, and
which of them its test cases already exercise.

Applicability comes only from the requirement text. A category is applicable
when the text names what it needs (a stated behavior, a limit with a value, a
role, a state, a failure); categories the text does not mention are not
applicable and do not lower the percentage. Where the text hints at a category
but gives too little to test it (a limit without a value, no stated behavior),
the category is Unknown and counts neither as applicable nor as covered.

Only Approved test cases count as coverage. A test case covers a category
through its test type, or through what its own text says (the requirement
quote is ignored, so restating the requirement is not coverage). Test cases
that cannot be classified cover nothing.

Conditions are not analyzed one by one. The one exception is a numeric limit joined
to other conditions ("at least 8 characters long and contain one digit"): boundary
and equivalence cases vary only the number, so the other parts are listed in
`unchecked_conditions` when no test case of the requirement (in any status) names
a word of them in its own text. That is a check of wording, not of meaning.
"""

import re
from enum import StrEnum

from pydantic import BaseModel

from spec_to_test.i18n import TRANSLATIONS
from spec_to_test.models import Requirement, ReviewStatus, TestCase, TestType
from spec_to_test.quantities import GT_WORDS, LT_WORDS, MAX_WORDS, MIN_WORDS, NUMBER
from spec_to_test.rule_engine import (
    _BOUNDARY,
    _CAPABILITY,
    _ERROR,
    _NEGATIVE,
    _OBLIGATION,
    _OUTCOME,
    _compile,
    _normalize,
    _quantities,
)
from spec_to_test.test_design import design_tests
from spec_to_test.test_generator import _short, other_conditions


class ScenarioCategory(StrEnum):
    HAPPY_PATH = "happy_path"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    PERMISSIONS = "permissions"
    STATE_TRANSITIONS = "state_transitions"
    RECOVERY = "recovery"


_PERMISSIONS = _compile([
    "admin*", "role", "roles", "permission*", "privilege*", "authoriz*", "authoris*", "unauthoriz*",
    "unauthoris*", "authenticated", "unauthenticated", "logged in", "logged-in", "signed in", "access",
    "owner", "moderator*", "guest", "guests", "anonymous",
    "админ*", "роль", "роли", "ролью", "доступ", "доступа", "доступу", "авториз*", "неавториз*",
    "привилег*", "владел*", "модератор*", "гость", "гостя", "гости", "гостевой", "аноним*",
    "адмін*", "ролі", "привіле*", "власник*", "гість", "гості", "анонім*",
])
_STATE = _compile([
    "status", "statuses", "state", "states", "transition*", "becomes", "become", "changes to",
    "change to", "moves to", "set to", "pending", "active", "inactive", "activated", "deactivat*",
    "locked", "unlocked", "blocked", "expired", "expires", "suspended", "archived", "cancel*",
    "статус*", "состояни*", "переход*", "переводит*", "становит*", "станет", "заблокир*",
    "разблокир*", "активир*", "деактивир*", "неактив*", "истек*", "истёк*", "отмен*", "архив*",
    "стан", "стану", "стані", "перехід*", "стає", "стане", "заблоков*", "розблоков*", "активов*",
    "деактивов*", "неактивн*", "скасов*", "архів*",
])
# A count of something limited ("5 failed login attempts", "3 retries"), for
# limits the shared quantity parser has no unit for. A bare number is not one.
_COUNTED_LIMIT = re.compile(
    r"(?<![\w.])\d+(?:\s+[^\W\d]+){0,2}?\s+"
    r"(?:attempts?|tries|retries|requests|попыт\w*|раз|запрос\w*|спроб\w*|разів|запит\w*)(?!\w)",
    re.IGNORECASE,
)
# A comparator with a number ("up to 3 files", "не более 5 фото", "between 1 and 10"),
# for limits whose unit neither of the above knows. The value is stated, so it is not Unknown.
_COMPARED_LIMIT = re.compile(
    rf"(?<!\w)(?:(?:{MIN_WORDS}|{MAX_WORDS}|{GT_WORDS}|{LT_WORDS})\s*(?<![\w.,])(?:{NUMBER})"
    rf"|(?:between|між|между)\s+(?:{NUMBER})\s+(?:and|і|и)\s+(?:{NUMBER}))(?![\w.,]?\d)",
    re.IGNORECASE,
)
_RECOVERY = _compile([
    "retry", "retries", "retried", "rollback", "roll back", "resume*", "reconnect*", "timeout",
    "time out", "times out", "unavailable", "offline", "outage", "connection lost", "lost connection",
    "crash*", "backup", "failover", "restart*",
    "повторить попытку", "повторная попытка", "повторной попытки", "откат*", "недоступ*", "сбой",
    "сбоя", "сбое", "таймаут*", "офлайн", "переподключ*", "возобнов*", "перезапуск*",
    "повторити спробу", "повторна спроба", "відкат*", "недоступн*", "збій", "збою", "збої",
    "перепідключ*", "поновл*", "перезапуск*",
])

# Generated equivalence cases list each partition as "value → accepted/rejected".
_VALID = list(TRANSLATIONS["design.valid"].values())
_INVALID = list(TRANSLATIONS["design.invalid"].values())

_BY_TYPE = {
    TestType.POSITIVE: ScenarioCategory.HAPPY_PATH,
    TestType.NEGATIVE: ScenarioCategory.NEGATIVE,
    TestType.ERROR_HANDLING: ScenarioCategory.NEGATIVE,
    TestType.BOUNDARY: ScenarioCategory.BOUNDARY,
}
# Categories a test case can earn through its own wording.
_BY_TEXT = {
    ScenarioCategory.NEGATIVE: [_ERROR, _NEGATIVE],
    ScenarioCategory.PERMISSIONS: [_PERMISSIONS],
    ScenarioCategory.STATE_TRANSITIONS: [_STATE],
    ScenarioCategory.RECOVERY: [_RECOVERY],
}


class ScenarioCoverage(BaseModel):
    applicable: list[ScenarioCategory]
    covered: list[ScenarioCategory]  # always a subset of applicable
    # Hinted at by the requirement, but too little to say whether it applies.
    unknown: list[ScenarioCategory]
    # Category -> the requirement wording it was derived from.
    reasons: dict[ScenarioCategory, str]
    # Parts of the requirement no test case names: see unchecked_conditions.
    unchecked_conditions: list[str] = []

    @property
    def missing(self) -> list[ScenarioCategory]:
        return [c for c in self.applicable if c not in self.covered]

    @property
    def percent(self) -> float | None:
        """Covered share of the applicable categories; None when nothing is known to apply."""
        if not self.applicable:
            return None
        return round(100 * len(self.covered) / len(self.applicable), 1)


def _first(patterns: list[re.Pattern[str]], text: str) -> str | None:
    for pattern in patterns:
        if match := pattern.search(text):
            return match.group(0)
    return None


def applicable_categories(
    requirement: Requirement,
) -> tuple[list[ScenarioCategory], list[ScenarioCategory], dict[ScenarioCategory, str]]:
    """Return (applicable, unknown, reasons) for one requirement."""
    text = _normalize(requirement.text)
    applicable: list[ScenarioCategory] = []
    unknown: list[ScenarioCategory] = []
    reasons: dict[ScenarioCategory, str] = {}

    def add(category: ScenarioCategory, term: str | None, target: list[ScenarioCategory]) -> None:
        if term:
            target.append(category)
            reasons[category] = term

    behavior = _first([_OBLIGATION, _CAPABILITY, _OUTCOME], text)
    if behavior:
        add(ScenarioCategory.HAPPY_PATH, behavior, applicable)
    else:
        unknown.append(ScenarioCategory.HAPPY_PATH)
    add(ScenarioCategory.NEGATIVE, _first([_NEGATIVE, _ERROR], text), applicable)
    if limits := _quantities(text):
        add(ScenarioCategory.BOUNDARY, next(iter(limits.values()))[1], applicable)
    elif counted := _COUNTED_LIMIT.search(text) or _COMPARED_LIMIT.search(text):
        add(ScenarioCategory.BOUNDARY, counted.group(0), applicable)
    else:
        add(ScenarioCategory.BOUNDARY, _first([_BOUNDARY], text), unknown)
    add(ScenarioCategory.PERMISSIONS, _first([_PERMISSIONS], text), applicable)
    add(ScenarioCategory.STATE_TRANSITIONS, _first([_STATE], text), applicable)
    add(ScenarioCategory.RECOVERY, _first([_RECOVERY], text), applicable)
    order = list(ScenarioCategory)
    return sorted(applicable, key=order.index), sorted(unknown, key=order.index), reasons


def categories_of_test_case(test_case: TestCase, requirement: Requirement) -> set[ScenarioCategory]:
    """Categories a test case exercises; empty when it cannot be classified."""
    found: set[ScenarioCategory] = set()
    if category := _BY_TYPE.get(test_case.test_type):
        found.add(category)
    if test_case.test_type == TestType.POSITIVE:
        return found  # a positive case is the happy path, whatever the requirement mentions
    if test_case.test_type == TestType.EQUIVALENCE:
        if any(v in test_case.expected_result for v in _VALID):
            found.add(ScenarioCategory.HAPPY_PATH)
        if any(v in test_case.expected_result for v in _INVALID):
            found.add(ScenarioCategory.NEGATIVE)
    own_text = "\n".join(
        [test_case.title, *test_case.preconditions, *test_case.steps, test_case.expected_result]
    ).replace(requirement.text, "")
    own_text = _normalize(own_text)
    for category, patterns in _BY_TEXT.items():
        if _first(patterns, own_text):
            found.add(category)
    return found


# Words that say how a condition applies, not what it is about.
_FUNCTION_WORDS = frozenset({
    "must", "should", "shall", "will", "have", "also", "with", "that", "this", "than", "then", "from",
    "должен", "должна", "должно", "должны", "может", "также", "повинен", "повинна", "повинно", "повинні",
    "може", "також",
})
_WORD = re.compile(r"[^\W\d_]{4,}")


def _stems(text: str) -> set[str]:
    return {word[:5] for word in _WORD.findall(_normalize(text).lower()) if word not in _FUNCTION_WORDS}


def unchecked_conditions(requirement: Requirement, test_cases: list[TestCase]) -> list[str]:
    """Parts of a numeric requirement that its boundary and equivalence cases do not vary
    (test_generator.other_conditions) and that no test case names. A test case names a part
    when its own text (title, preconditions, steps, expected result, without the requirement
    quote) has a word of it, compared by the first five letters; words the rest of the
    requirement also uses do not count. Empty without test cases: then nothing is covered anyway."""
    if not test_cases:
        return []
    conditions = other_conditions(requirement.text, design_tests(requirement))
    if not conditions:
        return []
    quotes = (requirement.text, _short(requirement.text))  # a positive case's title quotes it shortened
    named: set[str] = set()
    for tc in test_cases:
        own_text = "\n".join([tc.title, *tc.preconditions, *tc.steps, tc.expected_result])
        for quote in quotes:
            own_text = own_text.replace(quote, "")
        named |= {word[:5] for word in _WORD.findall(_normalize(own_text).lower())}
    unchecked = []
    for condition in conditions:
        rest = _stems(_normalize(requirement.text).replace(condition, " "))
        if (stems := _stems(condition) - rest) and not stems & named:
            unchecked.append(condition)
    return unchecked


def scenario_coverage(requirement: Requirement, test_cases: list[TestCase]) -> ScenarioCoverage:
    applicable, unknown, reasons = applicable_categories(requirement)
    approved = [tc for tc in test_cases if tc.review_status == ReviewStatus.APPROVED]
    exercised = set().union(*(categories_of_test_case(tc, requirement) for tc in approved))
    return ScenarioCoverage(
        applicable=applicable,
        covered=[c for c in applicable if c in exercised],
        unknown=unknown,
        reasons=reasons,
        unchecked_conditions=unchecked_conditions(requirement, test_cases),
    )
