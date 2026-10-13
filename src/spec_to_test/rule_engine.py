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

from spec_to_test import quantities
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
        "проста", "простою", "просте", "прості", "простим", "простого", "кількох", "кільком", "кількома",
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
        "простым", "простая", "простое", "простые", "простого", "простую",
        "нескольких", "нескольким", "несколькими",
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
        "fail*", "respond*", "response*", "generat*", "store*", "see", "sees", "visible",
    ],
    Language.UK: [
        "відображ*", "показ*", "поверта*", "поверне*", "надсила*", "надіслан*",
        "надішле*", "отрима*", "отриму*", "перенаправ*", "зберіга*", "збереж*",
        "створ*", "блоку*", "заблоков*", "відхиля*", "відхилен*", "прийма*",
        "сповіщ*", "повідомлен*", "помилк*", "з'явля*", "з'явит*", "дозвол*",
        "заборон*", "видал*", "оновл*", "вимкн*", "увімкн*", "успішн*",
        "діє", "дійсн*", "заверш*", "бачить", "бачать", "побачит*", "видн*", "формує*", "генеру*",
    ],
    Language.RU: [
        "отображ*", "показ*", "возвращ*", "вернет*", "отправ*", "получ*",
        "перенаправ*", "сохран*", "созда*", "блокир*", "заблокир*", "отклон*",
        "принима*", "приня*", "уведом*", "сообщени*", "ошибк*", "появля*",
        "появит*", "истека*", "разреш*", "запрещ*", "удал*", "обновл*",
        "отключ*", "включ*", "успешн*", "действ*", "заверш*", "видит", "видят", "увидит", "видн*", "формир*",
        "сформир*", "генерир*",
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
        "field*", "form", "type*", "fill*", "attach*",
    ],
    Language.UK: [
        "введ*", "вводит*", "поле", "поля", "полі", "форм*", "завантаж*",
        "вхід", "увійт*", "заповн*", "прикріп*",
    ],
    Language.RU: [
        "ввод*", "введ*", "поле", "поля", "форм*", "загруж*", "вход", "войт*",
        "заполн*", "прикреп*",
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
    # Comparators and size words say how much, not what about.
    "between", "over", "under", "above", "below", "maximum", "minimum",
    "exceed", "exceeds", "между", "свыше", "больше", "меньше", "превышать", "длиной", "між",
    "понад", "довжиною", "перевищувати", "дольше", "довше",
}

# Units, comparators and number formats live in spec_to_test.quantities (shared
# with the test design and Grill Mode); re-exported here for older imports.
UNITS = quantities.UNITS
MIN_WORDS = quantities.MIN_WORDS
MAX_WORDS = quantities.MAX_WORDS

# Words that narrow who or what a rule applies to. Two requirements with
# different qualifiers ("orders over 50 USD" vs "international orders over
# 100 USD") describe different contexts, not a contradiction. Prefixes.
SCOPE_QUALIFIERS = [
    "admin", "guest", "anonymous", "premium", "vip", "international", "domestic", "mobile", "desktop",
    "tablet", "business", "corporate", "enterprise", "trial", "wholesale", "retail", "partner",
    "moderator", "manager", "employee", "staff", "internal", "external", "registered", "unregistered",
    "verified", "unverified", "child", "minor", "student", "senior", "foreign", "express", "weekend",
    "weekday", "night", "holiday",
    "админ", "гост", "аноним", "премиум", "международн", "внутренн", "мобильн", "корпоратив", "оптов",
    "розничн", "партнер", "партнёр", "модератор", "менеджер", "сотрудник", "зарегистрирован",
    "незарегистрирован", "верифицирован", "иностранн", "экспресс", "выходн", "ночн", "праздничн",
    "адмін", "гість", "гост", "анонімн", "преміум", "міжнародн", "внутрішн", "мобільн", "оптов",
    "роздрібн", "партнер", "модератор", "менеджер", "співробітник", "працівник", "зареєстрован",
    "незареєстрован", "верифікован", "іноземн", "експрес", "вихідн", "нічн", "святков",
]
# Words that start a condition clause ("if ...", "for premium users", "при оплате ...").
CONDITION_MARKERS = (
    r"if|when|whenever|unless|while|during|in case of|only for|for|якщо|коли|поки|під час|у разі|в разі|"
    r"для|если|когда|пока|во время|в случае|при"
)

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
_CONDITION = re.compile(rf"(?<!\w)(?:{CONDITION_MARKERS})(?!\w)(?P<clause>[^,.;:!?]*)", re.IGNORECASE)
# Not what a condition is about: comparators around a number.
_CONDITION_FILLER = {"over", "under", "above", "below", "between", "понад", "свыше", "более", "менее", "більше", "менше"}


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


# Quoted labels ("Quick pay" button) are names, not vague wording.
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|«[^»]*»|„[^“”]*[“”]")
# Input words that are something else: "enterprise", "format", "formula", "формировать".
_NOT_INPUT = re.compile(r"enterpris|entertain|формат|формир|формув|формуєт|формул|формальн", re.IGNORECASE)
# An adjective-like participle: "uploaded photos", "загруженные фото", "завантажені фото".
_PARTICIPLE = re.compile(
    r"\w+ed|\w+(?:енн|ённ|анн)(?:ый|ая|ое|ые|ого|ой|ую|ых|ым|ыми)|\w+(?:ен|ан)(?:ий|а|е|і|их|им|ими|у|ої|ого)",
    re.IGNORECASE,
)
_PASSIVE = {
    "be", "is", "are", "was", "were", "been", "being", "get", "gets", "got",
    "быть", "будет", "будут", "был", "была", "были", "бути", "буде", "будуть", "був", "була", "були", "є",
}
_BY_AGENT = {"by", "пользователем", "пользователями", "користувачем", "користувачами"}
# "After the user logs in, ..." states a precondition, not the input under test.
_PRECONDITION = {"after", "once", "після", "после"}
_VALIDATION = re.compile(
    r"(?<!\w)(?:validat|verif|check|required|mandatory|провер|валид|перевір|валід|обязательн|обов'язков)\w*",
    re.IGNORECASE
)
_LOADING = re.compile(r"(?:загруж|загруз|завантаж)\w*(?:ся|сь)", re.IGNORECASE)
# "login date", "login page": the word names a thing, not the user's action.
_LOGIN = re.compile(r"log in|login|sign in|вхід|вход", re.IGNORECASE)
_LOGIN_NOUNS = {"date", "time", "history", "page", "screen", "button", "link", "name", "count"}
# Input nouns: a form or field alone ("the login form must be convenient") is not an action that can fail.
_INPUT_NOUN = re.compile(r"form|fields?|поле|поля|полі|форм(?:а|и|у|і|ою|е|ы|ой)?", re.IGNORECASE)
# Input dimensions: a limit on these is a rule about what the user may submit.
_INPUT_DIMENSIONS = frozenset({"characters", "data", "items", "attempts"})
_TYPE_VERB_BEFORE = {"can", "must", "should", "may", "to", "will", "shall", "user", "users", "then", "and", "they", "you"}
# Boundary words that a non-numeric event can settle: "expires when the user logs out".
_EVENT_LIMITED = re.compile(r"expir\w*|срок\w*|термін\w*|истека\w*|спливає", re.IGNORECASE)
_EVENT_WORDS = {"on", "upon", "when", "after", "at", "при", "когда", "после", "по", "після", "коли", "once"}
_NOT_A_LIMIT_BEFORE = {"response", "load", "loading", "processing", "waiting", "font", "screen", "window"}


def _words_around(text: str, start: int, end: int, count: int = 3) -> tuple[list[str], list[str]]:
    before = re.findall(r"[\w']+", text[:start].lower())[-count:]
    after = re.findall(r"[\w']+", text[end:].lower())[:count]
    return before, after


def input_terms(text: str) -> list[str]:
    """Words that show the requirement is about user input that can fail.

    Leaves out words used for something else: an adjective-like participle
    ("uploaded photos should appear quickly", "загруженные фото") unless the
    requirement validates it or limits it ("uploaded files must not exceed
    2 GB"), a precondition ("after login"), a noun ("login date"),
    page loading ("страница загружается"), "type" as a noun ("account type"),
    "in the form of", and look-alikes ("enterprise", "формат").
    """
    text = _normalize(text)
    validates = bool(_VALIDATION.search(text)) or any(
        q.dimension in _INPUT_DIMENSIONS and q.comparator != "exact" for q in quantities.limits(text)
    )
    found: list[str] = []
    for match in _INPUT.finditer(text):
        word = match.group(0)
        lower = word.lower()
        before, after = _words_around(text, match.start(), match.end())
        if _NOT_INPUT.match(word) or _LOADING.fullmatch(word):
            continue
        if any(w in _PRECONDITION for w in before):
            continue
        if _PARTICIPLE.fullmatch(word) and not validates:
            if not (before and before[-1] in _PASSIVE) and not (after and after[0] in _BY_AGENT):
                continue
        if lower.startswith("type") and not (
            (after and after[0] in ("in", "into")) or (before and before[-1] in _TYPE_VERB_BEFORE)
        ):
            continue
        if lower == "form" and before[-2:] in (["in", "the"], ["in"]) and after[:1] == ["of"]:
            continue
        if _LOGIN.fullmatch(word) and after and after[0] in _LOGIN_NOUNS:
            continue
        if lower not in (f.lower() for f in found):
            found.append(word)
    if found and all(_INPUT_NOUN.fullmatch(word) for word in found) and not validates:
        return []  # only a form or field is named: nothing the user does can fail yet
    return found


def boundary_terms(text: str) -> list[str]:
    """Concepts that need a number, unless the text settles them otherwise.

    "Expires when the user logs out" is limited by an event, not a number,
    and "response times" or "font size" are not limits a tester can probe.
    """
    text = _normalize(text)
    found: list[str] = []
    for match in _BOUNDARY.finditer(text):
        word = match.group(0)
        before, after = _words_around(text, match.start(), match.end())
        if _EVENT_LIMITED.fullmatch(word) and any(w in _EVENT_WORDS for w in after):
            continue
        if word.lower() in ("times", "size") and before and before[-1] in _NOT_A_LIMIT_BEFORE:
            continue
        if word.lower() not in (f.lower() for f in found):
            found.append(word)
    return found


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
    """Map (unit, comparator) to (number, original phrase), for the test design.

    Example: {("characters", "min"): ("8", "at least 8 characters")}. Strict
    comparators ("more than 5 attempts") are reported as the exact number, as
    the test design has always treated them.
    """
    found: dict[tuple[str, str], tuple[str, str]] = {}
    for quantity in quantities.find_quantities(text, skip_ranges=False):
        number = quantities.format_quantity(quantity.value)
        if quantity.comparator in ("gt", "lt"):
            found.setdefault((quantity.unit, "exact"), (number, quantity.bare))
        else:
            found.setdefault((quantity.unit, quantity.comparator), (number, quantity.phrase))
    return found


def _stems(words: set[str]) -> set[str]:
    return {w[:5] for w in words}


def scope_qualifiers(text: str) -> set[str]:
    """Qualifiers that narrow a rule's scope ("admin", "международн", ...)."""
    words = re.findall(r"\w+", _normalize(text).lower())
    return {q for w in words for q in SCOPE_QUALIFIERS if w.startswith(q)}


def condition_words(text: str) -> set[str]:
    """Content words of the text's condition clauses ("if the address is abroad" -> {address, abroad})."""
    words: set[str] = set()
    for match in _CONDITION.finditer(_normalize(text)):
        words |= _content_words(match.group("clause")) - _CONDITION_FILLER
    return words


def different_context(text_a: str, text_b: str) -> bool:
    """True when two statements apply to different scopes or conditions.

    "Orders over 50 USD ship free" and "International orders over 100 USD ship
    free" differ by a qualifier; "... if the address is abroad" adds a
    condition the other statement does not mention. Such pairs are not
    contradictions: each may hold in its own context.
    """
    return _Context.of(text_a).differs(_Context.of(text_b))


class _Context(NamedTuple):
    qualifiers: set[str]
    condition_stems: set[str]
    stems: set[str]

    @classmethod
    def of(cls, text: str) -> "_Context":
        return cls(scope_qualifiers(text), _stems(condition_words(text)), _stems(_content_words(_normalize(text))))

    def differs(self, other: "_Context") -> bool:
        return self.qualifiers != other.qualifiers or bool(
            self.condition_stems - other.stems or other.condition_stems - self.stems
        )


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

    if ambiguous := _matches(_AMBIGUOUS, _QUOTED.sub(" ", text)):
        add(FindingType.AMBIGUOUS_WORDING, Severity.MEDIUM, ambiguous)

    states_behavior = _OBLIGATION.search(text) and not _CAPABILITY.search(text)
    # "Orders over 50 USD get free shipping", "Подписка стоит 10 USD в месяц": a
    # declarative rule with a concrete value states what to check, unless the
    # user does something whose result is still open ("enters a code of 6 digits").
    states_value = bool(quantities.limits(text)) and not input_terms(text)
    if not states_behavior and not states_value and not _OUTCOME.search(text):
        add(FindingType.MISSING_EXPECTED_RESULT, Severity.HIGH, [])

    if (boundary := boundary_terms(text)) and not _has_number(text):
        add(FindingType.MISSING_BOUNDARY, Severity.MEDIUM, boundary)

    if (inputs := input_terms(text)) and not _ERROR.search(text):
        add(FindingType.MISSING_ERROR_HANDLING, Severity.MEDIUM, inputs)

    return findings


# Minimum share of topic words two requirements need before they are compared.
NUMERIC_SIMILARITY = 0.4
NEGATION_SIMILARITY = 0.6


class _Features(NamedTuple):
    """Pre-computed facts about one requirement, reused for every pair."""

    words: set[str]
    limits: list[quantities.Quantity]
    modal: tuple[bool, str] | None
    context: _Context
    # Content words before the first stated limit: what the limit is about.
    subject: set[str]


def _features(req: Requirement) -> _Features:
    text = _normalize(req.text)
    limits = quantities.limits(text)
    subject = _content_words(text[: limits[0].start]) if limits else set()
    return _Features(_content_words(text), limits, _modal(text), _Context.of(text), subject)


def _similarity(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a & b else 0.0


def _contradiction_terms(a: _Features, b: _Features) -> list[str] | None:
    """Return the conflicting phrases if two requirements seem to conflict."""
    similarity = _similarity(a.words, b.words)
    # "The username must be between 3 and 20 characters" and "The username must
    # be at least 5 characters long" share their subject even if the rest differs.
    limit_similarity = max(similarity, _similarity(a.subject, b.subject))
    if max(similarity, limit_similarity) < min(NUMERIC_SIMILARITY, NEGATION_SIMILARITY):
        return None
    if a.context.differs(b.context):
        return None  # each statement may hold in its own scope or condition

    # Same topic and dimension, limits that cannot both hold: "password at least
    # 8 characters" vs "at least 10 characters", "at least 10" vs "at most 8",
    # "2 minutes" vs "3 minutes" (but not "2 minutes" vs "120 seconds").
    if limit_similarity >= NUMERIC_SIMILARITY:
        for limit_a in a.limits:
            for limit_b in b.limits:
                if quantities.disagree(limit_a, limit_b):
                    return [limit_a.phrase, limit_b.phrase]

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
