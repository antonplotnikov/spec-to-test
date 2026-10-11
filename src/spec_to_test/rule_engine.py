"""Rule-based requirement analysis (works offline, no AI).

Rules are simple keyword heuristics. They report *possible* issues; every
finding is marked "Needs clarification" until a person reviews it.

Term notation: a trailing "*" means "word starting with", so "quick*"
matches "quick", "quickly" and "quicker". Terms for all three languages are
checked for every requirement, which keeps mixed-language documents working.
"""

import re
from itertools import combinations
from typing import NamedTuple

from spec_to_test.models import (
    AnalysisResult,
    Finding,
    FindingType,
    Language,
    Requirement,
    Severity,
)

# ---------------------------------------------------------------------------
# Keyword lists (one per language)
# ---------------------------------------------------------------------------

AMBIGUOUS_TERMS: dict[Language, list[str]] = {
    Language.EN: [
        "fast", "quick*", "slow*", "user-friendly", "easy", "easily", "simple",
        "intuitive*", "appropriate*", "adequate*", "sufficient*", "reasonable",
        "as soon as possible", "asap", "etc", "and/or", "some", "several",
        "many", "few", "various", "usually", "normally", "often", "sometimes",
        "approximately", "flexible", "robust", "efficient*", "seamless*",
        "optimal*", "if possible", "as needed", "where applicable", "tbd",
        "properly", "correctly",
    ],
    Language.UK: [
        "швидк*", "повільн*", "зручн*", "легк*", "простий", "просто",
        "інтуїтивн*", "відповідний", "відповідна", "відповідне", "відповідні",
        "відповідних", "відповідним", "відповідну", "відповідного",
        "належн*", "достатн*", "розумн*",
        "якомога швидше", "тощо", "і/або", "деяк*", "кілька", "декільк*",
        "багато", "зазвичай", "часто", "іноді", "приблизно", "гнучк*",
        "ефективн*", "оптимальн*", "за потреби", "по можливості",
        "коректно", "правильно",
    ],
    Language.RU: [
        "быстр*", "медленн*", "удобн*", "легк*", "простой", "просто",
        "интуитивн*", "соответствующ*", "надлежащ*", "достаточн*", "разумн*",
        "как можно скорее", "и т.д.", "и т. д.", "и/или", "некотор*",
        "несколько", "много", "обычно", "часто", "иногда", "приблизительно",
        "примерно", "гибк*", "эффективн*", "оптимальн*", "при необходимости",
        "по возможности", "корректно", "правильно",
    ],
}

# Words describing an observable outcome or a required state.
OUTCOME_TERMS: dict[Language, list[str]] = {
    Language.EN: [
        "display*", "show*", "return*", "send*", "sent", "receive*", "redirect*",
        "save*", "creat*", "block*", "reject*", "accept*", "lock*", "notif*",
        "logged", "error*", "message*", "appear*", "expire*", "allow*",
        "grant*", "disable*", "enable*", "delete*", "update*", "succe*",
        "fail*", "respond*", "response*", "generat*", "store*",
    ],
    Language.UK: [
        "відображ*", "показ*", "поверта*", "поверне*", "надсила*", "надіслан*",
        "надішле*", "отрима*", "отриму*", "перенаправ*", "зберіга*", "збереж*",
        "створ*", "блоку*", "заблоков*", "відхиля*", "відхилен*", "прийма*",
        "сповіщ*", "повідомлен*", "помилк*", "з'явля*", "з'явит*", "дозвол*",
        "заборон*", "видал*", "оновл*", "вимкн*", "увімкн*", "успішн*",
        "діє", "дійсн*",
    ],
    Language.RU: [
        "отображ*", "показ*", "возвращ*", "вернет*", "отправ*", "получ*",
        "перенаправ*", "сохран*", "созда*", "блокир*", "заблокир*", "отклон*",
        "принима*", "приня*", "уведом*", "сообщени*", "ошибк*", "появля*",
        "появит*", "истека*", "разреш*", "запрещ*", "удал*", "обновл*",
        "отключ*", "включ*", "успешн*", "действ*",
    ],
}

# "The system must encrypt data" states the required behavior itself.
OBLIGATION_TERMS: dict[Language, list[str]] = {
    Language.EN: [
        "must", "shall", "should", "will", "has to", "have to", "needs to",
        "need to", "required to", "is required", "are required",
    ],
    Language.UK: [
        "повин*", "має", "мають", "необхідно", "потрібно", "слід", "буде",
        "будуть", "зобов'язан*",
    ],
    Language.RU: [
        "долж*", "необходимо", "нужно", "следует", "обязан*", "будет", "будут",
    ],
}

# "The user can reset the password" names a capability but not its result.
CAPABILITY_TERMS: dict[Language, list[str]] = {
    Language.EN: ["can", "may", "able to", "allowed to", "possible to", "permitted to"],
    Language.UK: [
        "може", "можуть", "можна", "мати змогу", "має змогу", "мають змогу",
        "мати можливість", "має можливість", "мають можливість", "здатн*",
    ],
    Language.RU: [
        "может", "могут", "можно", "иметь возможность", "имеет возможность",
        "имеют возможность", "способн*", "в состоянии",
    ],
}

# Concepts that normally need a concrete number or limit.
BOUNDARY_TRIGGERS: dict[Language, list[str]] = {
    Language.EN: [
        "length", "character*", "size", "limit*", "attempt*", "times",
        "minutes", "seconds", "hours", "days", "amount", "number of", "count",
        "maximum", "minimum", "max", "min", "age", "quantity", "expire*",
        "timeout", "at least", "up to", "no more than", "more than",
        "less than",
    ],
    Language.UK: [
        "довжин*", "символ*", "розмір*", "ліміт*", "обмежен*", "спроб*",
        "разів", "хвилин*", "секунд*", "годин*", "днів", "кількість",
        "максимал*", "мінімал*", "максимум", "мінімум", "вік", "термін*",
        "не менше", "не більше", "щонайменше",
    ],
    Language.RU: [
        "длин*", "символ*", "размер*", "лимит*", "ограничен*", "попыт*",
        "минут*", "секунд*", "часов", "дней", "количеств*", "максимальн*",
        "минимальн*", "максимум", "минимум", "возраст", "срок*", "не менее",
        "не более", "как минимум",
    ],
}

NUMBER_WORDS: dict[Language, list[str]] = {
    Language.EN: [
        "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "twelve", "fifteen", "twenty", "thirty", "hundred",
    ],
    Language.UK: [
        "один", "одна", "одну", "два", "дві", "три", "чотири", "п'ять",
        "шість", "сім", "вісім", "дев'ять", "десять", "двадцять", "тридцять",
    ],
    Language.RU: [
        "один", "одна", "одну", "два", "две", "три", "четыре", "пять",
        "шесть", "семь", "восемь", "девять", "десять", "двадцать", "тридцать",
    ],
}

# User input or actions that can fail and therefore need error rules.
INPUT_TRIGGERS: dict[Language, list[str]] = {
    Language.EN: [
        "enter*", "input*", "submit*", "upload*", "log in", "login", "sign in",
        "field*", "form", "type*", "fill*",
    ],
    Language.UK: [
        "введ*", "вводит*", "поле", "поля", "полі", "форм*", "завантаж*",
        "вхід", "увійт*", "заповн*",
    ],
    Language.RU: [
        "ввод*", "введ*", "поле", "поля", "форм*", "загруж*", "вход", "войт*",
        "заполн*",
    ],
}

ERROR_TERMS: dict[Language, list[str]] = {
    Language.EN: [
        "error*", "invalid*", "fail*", "incorrect*", "wrong", "reject*",
        "otherwise", "exception*", "denied", "deny", "not found",
        "does not exist", "expired", "unsuccessful*", "not valid", "warning*",
        "if not", "unavailable", "is not", "are not", "does not", "unregistered",
    ],
    Language.UK: [
        "помилк*", "невірн*", "неправильн*", "некоректн*", "недійсн*",
        "відхил*", "інакше", "виняток", "відмов*", "не знайдено", "не існує",
        "прострочен*", "неуспішн*", "невдал*", "попередженн*", "якщо не",
        "не зареєстрован*",
    ],
    Language.RU: [
        "ошибк*", "неверн*", "неправильн*", "некорректн*", "недействител*",
        "отклон*", "иначе", "исключени*", "отказ*", "не найден*",
        "не существует", "просроч*", "неудач*", "неуспешн*", "предупрежден*",
        "если не", "не зарегистрирован*",
    ],
}

NEGATIVE_MODALS = [
    "must not", "shall not", "should not", "cannot", "can't", "never",
    "is not allowed", "не повин*", "не може", "не можна", "заборонено",
    "ніколи", "не долж*", "не может", "нельзя", "запрещено", "никогда",
]
POSITIVE_MODALS = [
    "must", "shall", "should", "can", "is allowed", "повин*", "може", "можна",
    "дозволено", "долж*", "может", "можно", "разрешено",
]

# Ignored when comparing what two requirements are about.
STOPWORDS = {
    "must", "shall", "should", "will", "would", "could", "with", "from",
    "that", "this", "have", "been", "when", "then", "than", "after",
    "before", "into", "each", "user", "users", "system", "least", "more",
    "less", "most", "within", "only", "also", "their", "there", "which",
    "повинен", "повинна", "повинно", "мають", "може", "можна", "після",
    "перед", "якщо", "тоді", "цього", "який", "яка", "які", "користувач",
    "користувача", "система", "системи", "щонайменше", "менше", "більше",
    "також", "лише", "должен", "должна", "должно", "могут", "может",
    "можно", "после", "если", "тогда", "этого", "который", "которая",
    "пользователь", "пользователя", "системы", "менее", "более", "только",
    "минимум", "максимум", "мінімум",
}

# Units used to compare numeric limits between requirements.
UNITS: dict[str, str] = {
    "characters": r"characters?|chars?|символ\w*|знак\w*",
    "minutes": r"minutes?|mins?|хвилин\w*|минут\w*",
    "seconds": r"seconds?|secs?|секунд\w*",
    "hours": r"hours?|годин\w*|час(?:а|ов)?",
    "days": r"days?|дн(?:і|ів|я|ей)|день",
    "attempts": r"attempts?|tries|спроб\w*|попыт\w*",
    "megabytes": r"mb|megabytes?|мб",
}
MIN_WORDS = r"at least|minimum|min\.?|не менше|щонайменше|мінімум|не менее|минимум|как минимум"
MAX_WORDS = r"at most|maximum|max\.?|up to|no more than|не більше|максимум|до|не более|не больше"


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _term_pattern(term: str) -> str:
    if term.endswith("*"):
        return rf"(?<!\w){re.escape(term[:-1])}\w*"
    return rf"(?<!\w){re.escape(term)}(?!\w)"


def _compile(terms: list[str]) -> re.Pattern[str]:
    return re.compile("|".join(_term_pattern(t) for t in terms), re.IGNORECASE)


def _compile_all(terms_by_language: dict[Language, list[str]]) -> re.Pattern[str]:
    merged = [term for terms in terms_by_language.values() for term in terms]
    return _compile(merged)


_AMBIGUOUS = _compile_all(AMBIGUOUS_TERMS)
_OUTCOME = _compile_all(OUTCOME_TERMS)
_BOUNDARY = _compile_all(BOUNDARY_TRIGGERS)
_NUMBER_WORD = _compile_all(NUMBER_WORDS)
_INPUT = _compile_all(INPUT_TRIGGERS)
_ERROR = _compile_all(ERROR_TERMS)
_OBLIGATION = _compile_all(OBLIGATION_TERMS)
_CAPABILITY = _compile_all(CAPABILITY_TERMS)
_NEGATIVE = _compile(NEGATIVE_MODALS)
_POSITIVE = _compile(POSITIVE_MODALS)
_UNIT_WORD = re.compile("|".join(UNITS.values()), re.IGNORECASE)
_QUANTITIES = {
    unit: re.compile(
        rf"(?:(?<!\w)(?P<min>{MIN_WORDS})|(?<!\w)(?P<max>{MAX_WORDS}))?\s*"
        rf"(?P<number>\d+(?:[.,]\d+)?)\s*(?:{pattern})(?!\w)",
        re.IGNORECASE,
    )
    for unit, pattern in UNITS.items()
}


def _normalize(text: str) -> str:
    """Unify apostrophes so Ukrainian words like з'явиться match."""
    return text.replace("’", "'").replace("ʼ", "'").replace("`", "'")


def _matches(pattern: re.Pattern[str], text: str) -> list[str]:
    """Return unique matched phrases in order of appearance."""
    found: list[str] = []
    for match in pattern.finditer(text):
        phrase = match.group(0)
        if phrase.lower() not in (f.lower() for f in found):
            found.append(phrase)
    return found


def _has_number(text: str) -> bool:
    return bool(re.search(r"\d", text) or _NUMBER_WORD.search(text))


def _content_words(text: str) -> set[str]:
    """Words that describe what a requirement is about (no units or filler)."""
    words = re.findall(r"\w+", text.lower())
    return {
        w
        for w in words
        if len(w) >= 4
        and not w.isdigit()
        and w not in STOPWORDS
        and not _UNIT_WORD.fullmatch(w)
    }


def _quantities(text: str) -> dict[tuple[str, str], tuple[str, str]]:
    """Map (unit, comparator) to (number, original phrase).

    Example: {("characters", "min"): ("8", "at least 8 characters")}
    """
    found: dict[tuple[str, str], tuple[str, str]] = {}
    for unit, pattern in _QUANTITIES.items():
        for match in pattern.finditer(text):
            comparator = "min" if match.group("min") else "max" if match.group("max") else "exact"
            number = match.group("number").replace(",", ".")
            found.setdefault((unit, comparator), (number, match.group(0).strip()))
    return found


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _single_requirement_findings(req: Requirement) -> list[Finding]:
    text = _normalize(req.text)
    findings: list[Finding] = []

    def add(kind: FindingType, severity: Severity, terms: list[str]) -> None:
        findings.append(
            Finding(requirement_id=req.id, type=kind, severity=severity, matched_terms=terms)
        )

    if ambiguous := _matches(_AMBIGUOUS, text):
        add(FindingType.AMBIGUOUS_WORDING, Severity.MEDIUM, ambiguous)

    states_behavior = _OBLIGATION.search(text) and not _CAPABILITY.search(text)
    if not states_behavior and not _OUTCOME.search(text):
        add(FindingType.MISSING_EXPECTED_RESULT, Severity.HIGH, [])

    if (boundary := _matches(_BOUNDARY, text)) and not _has_number(text):
        add(FindingType.MISSING_BOUNDARY, Severity.MEDIUM, boundary)

    if (inputs := _matches(_INPUT, text)) and not _ERROR.search(text):
        add(FindingType.MISSING_ERROR_HANDLING, Severity.MEDIUM, inputs)

    return findings


# Minimum share of topic words two requirements need before they are compared.
NUMERIC_SIMILARITY = 0.4
NEGATION_SIMILARITY = 0.6


class _Features(NamedTuple):
    """Pre-computed facts about one requirement, reused for every pair."""

    words: set[str]
    quantities: dict[tuple[str, str], tuple[str, str]]
    modal: tuple[bool, str] | None


def _features(req: Requirement) -> _Features:
    text = _normalize(req.text)
    return _Features(_content_words(text), _quantities(text), _modal(text))


def _contradiction_terms(a: _Features, b: _Features) -> list[str] | None:
    """Return the conflicting phrases if two requirements seem to conflict."""
    shared = a.words & b.words
    if not shared:
        return None
    similarity = len(shared) / len(a.words | b.words)

    # Same topic, unit and comparator, different numbers:
    # "password at least 8 characters" vs "password at least 10 characters".
    if similarity >= NUMERIC_SIMILARITY:
        for key, (number_a, phrase_a) in a.quantities.items():
            if key in b.quantities and b.quantities[key][0] != number_a:
                return [phrase_a, b.quantities[key][1]]

    # Nearly identical statements where one is negated: "must" vs "must not".
    if similarity >= NEGATION_SIMILARITY and a.modal and b.modal and a.modal[0] != b.modal[0]:
        return [a.modal[1], b.modal[1]]
    return None


def _modal(text: str) -> tuple[bool, str] | None:
    """Return (is_negative, phrase) for the requirement's modal verb."""
    if match := _NEGATIVE.search(text):
        return True, match.group(0)
    if match := _POSITIVE.search(text):
        return False, match.group(0)
    return None


def _contradiction_findings(requirements: list[Requirement]) -> list[Finding]:
    features = {req.id: _features(req) for req in requirements}
    findings: list[Finding] = []
    for a, b in combinations(requirements, 2):
        terms = _contradiction_terms(features[a.id], features[b.id])
        if terms is None:
            continue
        for req, other in ((a, b), (b, a)):
            findings.append(
                Finding(
                    requirement_id=req.id,
                    type=FindingType.CONTRADICTION,
                    severity=Severity.HIGH,
                    matched_terms=terms if req is a else terms[::-1],
                    related_requirement_ids=[other.id],
                )
            )
    return findings


def analyze_requirements(requirements: list[Requirement]) -> AnalysisResult:
    """Run all rules and return findings ordered by requirement."""
    findings = [f for req in requirements for f in _single_requirement_findings(req)]
    findings += _contradiction_findings(requirements)

    order = {req.id: index for index, req in enumerate(requirements)}
    findings.sort(key=lambda f: order.get(f.requirement_id, len(order)))
    return AnalysisResult(requirements=requirements, findings=findings)
