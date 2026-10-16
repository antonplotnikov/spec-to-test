"""Numbers with units in requirement text (English, Russian, Ukrainian).

One parser for every place that reads limits: the rule engine (numeric
contradictions), the test design (boundary values) and Grill Mode (answers
that disagree with a requirement). Nothing is guessed: a number counts only
when a known unit or currency is written next to it.

- Units belong to a dimension and convert to its base unit, so "2 minutes"
  and "120 seconds" are the same limit, "1 GB" is 1024 MB, and "5 MB" vs
  "10 MB" differ. Months and years are calendar units and are never
  converted to days.
- Every currency is its own dimension: "100 USD" and "3000 RUB" are never
  compared (no exchange rates are assumed).
- Comparators: min ("at least", "не менее", "щонайменше"), max ("up to",
  "не более", "не більше", "must not exceed", "не повинен перевищувати"), strict gt ("more than", "свыше", "понад") and lt
  ("less than", "менее", "менше"), or exact. "N or more" ("8 и более", "8 або
  більше") is a min only after an obligation ("must contain 8 or more
  characters"); otherwise it may name the rejected side and stays exact.
- Ranges: "between 8 and 64 characters", "8-64 characters", "от 8 до 64
  символов", "від 8 до 64 символів", "from $10 to $50".
- Number formats: "1 000", "1,000", "1 000,50", "2.5", "2,5".
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# name -> (dimension, factor to the dimension's base unit, suffix pattern, prefix symbol pattern)
_UNIT_TABLE: dict[str, tuple[str, Decimal, str, str]] = {
    "characters": ("characters", Decimal(1), r"characters?|chars?|символ\w*|знак\w*", ""),
    "milliseconds": ("time", Decimal("0.001"), r"ms|milliseconds?|мс|миллисекунд\w*|мілісекунд\w*", ""),
    "seconds": ("time", Decimal(1), r"seconds?|secs?|сек\.?|секунд\w*", ""),
    "minutes": ("time", Decimal(60), r"minutes?|mins?|хв\.?|хвилин\w*|мин\.?|минут\w*", ""),
    "hours": ("time", Decimal(3600), r"hours?|hrs?|годин\w*|час(?:а|ов)?", ""),
    "days": ("time", Decimal(86400), r"days?|дн(?:і|ів|я|ей)|день|доб(?:а|и|у)|сут(?:ки|ок)", ""),
    "weeks": ("time", Decimal(604800), r"weeks?|тижн(?:і|ів|я)|тиждень|недел(?:и|ь|ю)|неделя", ""),
    "months": ("calendar", Decimal(1), r"months?|місяц\w*|месяц\w*", ""),
    "years": ("calendar", Decimal(12), r"years?|рок(?:и|ів)|рік|лет|года?", ""),
    "attempts": ("attempts", Decimal(1), r"attempts?|tries|спроб\w*|попыт\w*", ""),
    "kilobytes": ("data", Decimal(1024), r"kb|kilobytes?|кб|кілобайт\w*|килобайт\w*", ""),
    "megabytes": ("data", Decimal(1024**2), r"mb|megabytes?|мб|мегабайт\w*", ""),
    "gigabytes": ("data", Decimal(1024**3), r"gb|gigabytes?|гб|гігабайт\w*|гигабайт\w*", ""),
    "percent": ("percent", Decimal(1), r"%|percent|per cent|відсот\w*|процент\w*", ""),
    "usd": ("usd", Decimal(1), r"usd|us dollars?|dollars?|долар\w*|доллар\w*|\$", r"US\$|\$"),
    "eur": ("eur", Decimal(1), r"eur|euros?|євро|евро|€", r"€"),
    "gbp": ("gbp", Decimal(1), r"gbp|£", r"£"),
    "rub": ("rub", Decimal(1), r"rub|rubles?|roubles?|руб(?:\.|л\w*)?|₽", r"₽"),
    "uah": ("uah", Decimal(1), r"uah|hryvni?as?|грн\.?|гривн\w*|гривен\w*|гривень|₴", r"₴"),
    "items": ("items", Decimal(1), r"items?|products?|товар(?:ов|а|ы|ів|и)?|позиц\w*", ""),
}

# Suffix patterns by unit (the rule engine's historical name for this table).
UNITS: dict[str, str] = {name: suffix for name, (_, _, suffix, _) in _UNIT_TABLE.items()}
CURRENCIES = frozenset({"usd", "eur", "gbp", "rub", "uah"})

MIN_WORDS = (
    r"at least|minimum(?: of)?|min\.?|no less than|not less than|no fewer than|no shorter than|no smaller than|"
    r"не менше(?: ніж| за)?|щонайменше|мінімум|не менее(?: чем)?|не меньше(?: чем)?|минимум|как минимум"
)
MAX_WORDS = (
    r"at most|maximum(?: of)?|max\.?|up to|no more than|not more than|not exceed\w*|no longer than|no larger than|"
    r"не більше(?: ніж| за)?|максимум|до|не более(?: чем)?|не больше(?: чем)?|не превыша\w*|не перевищу\w*|"
    r"no later than|не дольше(?: чем)?(?: за)?|не довше(?: ніж)?(?: за)?|не позднее|не позже|не пізніше(?: ніж)?(?: за)?|"
    # "cannot exceed", "не повинен перевищувати", "не должен превышать": a negated "more than" is an upper limit.
    r"(?:cannot|can't|won't|doesn't|don't|mustn't|shouldn't|shan't) exceed\w*|"
    r"не (?:повин\w*|ма[єю]\w*|мож\w*|буде|будуть|долж\w*|мог\w*|будет|будут) (?:перевищ\w*|превы[шс]\w*)"
)
GT_WORDS = (
    r"more than|greater than|over|above|exceeds?|exceeding|longer than|larger than|bigger than|"
    r"понад|більше ніж|більше за|більш ніж|свыше|более чем|больше чем|превыша\w*|перевищу\w*"
)
LT_WORDS = (
    r"less than|fewer than|under|below|shorter than|smaller than|"
    r"менше ніж|менше за|менш ніж|нижче|менее чем|меньше чем|меньше|менее"
)

NUMBER = r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?"
_SUFFIX_ANY = "|".join(f"(?:{suffix})" for suffix in UNITS.values())
_PREFIX_ANY = "|".join(f"(?:{prefix})" for _, _, _, prefix in _UNIT_TABLE.values() if prefix)
_END = r"(?![\w$€£₽₴%])"

# "8 or more characters", "8 символов и более", "8 або більше символів".
OR_MORE_WORDS = r"or more|(?:и|или) (?:более|больше)|(?:або|і|й|та|чи) більше"
# An obligation right before the number: "must be / must contain / должен содержать / має містити".
# Only then is "N or more" the valid side; "passwords of 65 or more characters are rejected" is not.
_OBLIGATION_BEFORE = re.compile(
    r"(?<!\w)(?:must|shall|should|has to|have to|needs? to)\s+(?:be|have|contain|consist of|include)\s*$|"
    r"(?<!\w)(?:долж(?:ен|на|но|ны)|обязан\w*)\s+(?:быть|содержать|состоять из|иметь|включать)\s*$|"
    r"(?<!\w)(?:ма(?:є|ють)|повин(?:ен|на|но|ні)|мус(?:ить|ять))\s+(?:бути|містити|складатися з|мати|включати)\s*$",
    re.IGNORECASE,
)

_QUANTITY = re.compile(
    rf"(?:(?<!\w)(?P<min>{MIN_WORDS})|(?<!\w)(?P<max>{MAX_WORDS})|(?<!\w)(?P<gt>{GT_WORDS})|(?<!\w)(?P<lt>{LT_WORDS}))?"
    rf"\s*(?:(?P<prefix>{_PREFIX_ANY})\s?(?P<pnum>{NUMBER})|"
    rf"(?<![\w.,])(?P<num>{NUMBER})(?:\s+(?P<more_inner>{OR_MORE_WORDS}))?\s*(?P<suffix>{_SUFFIX_ANY}))"
    rf"(?:\s+(?P<more>{OR_MORE_WORDS}))?{_END}",
    re.IGNORECASE,
)
_RANGE = re.compile(
    rf"(?:(?<!\w)(?:between|from|від|от|между|з)\s+)?"
    rf"(?:(?P<prefix>{_PREFIX_ANY})\s?)?(?<![\w.,])(?P<low>{NUMBER})\s*(?P<lsuffix>{_SUFFIX_ANY})?\s*"
    rf"(?:and|to|до|і|и|[-–—…]|\.\.)\s*(?:(?P<prefix2>{_PREFIX_ANY})\s?)?(?P<high>{NUMBER})\s*(?P<suffix>{_SUFFIX_ANY})?{_END}",
    re.IGNORECASE,
)
_COMPILED_SUFFIX = {name: re.compile(rf"(?:{suffix})\Z", re.IGNORECASE) for name, suffix in UNITS.items()}
_COMPILED_PREFIX = {
    name: re.compile(rf"(?:{prefix})\Z", re.IGNORECASE) for name, (_, _, _, prefix) in _UNIT_TABLE.items() if prefix
}


@dataclass(frozen=True)
class Quantity:
    """One stated limit: "at least 8 characters" -> (characters, min, 8)."""

    unit: str
    comparator: str  # "min", "max", "gt", "lt" or "exact"
    value: Decimal
    phrase: str  # the original wording, comparator included
    bare: str  # the number and unit only ("8 characters")
    start: int
    end: int

    @property
    def dimension(self) -> str:
        return dimension(self.unit)

    @property
    def base(self) -> Decimal:
        return to_base(self.value, self.unit)


@dataclass(frozen=True)
class Range:
    unit: str
    low: Decimal
    high: Decimal
    phrase: str
    start: int
    end: int

    @property
    def dimension(self) -> str:
        return dimension(self.unit)


def dimension(unit: str) -> str:
    return _UNIT_TABLE[unit][0] if unit in _UNIT_TABLE else unit


def to_base(value: Decimal, unit: str) -> Decimal:
    """`value` in its dimension's base unit (seconds, bytes, months, ...)."""
    factor = _UNIT_TABLE[unit][1] if unit in _UNIT_TABLE else Decimal(1)
    return (value * factor).normalize()


def parse_number(text: str) -> Decimal | None:
    """ "1 000" -> 1000, "1,000" -> 1000, "2,5" -> 2.5, "1 000,50" -> 1000.50."""
    raw = re.sub(r"[   ]", "", text)
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
        raw = raw.replace(",", "")
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


def _unit_of(suffix: str | None, prefix: str | None) -> str | None:
    if suffix:
        return next((name for name, pattern in _COMPILED_SUFFIX.items() if pattern.fullmatch(suffix.strip())), None)
    if prefix:
        return next((name for name, pattern in _COMPILED_PREFIX.items() if pattern.fullmatch(prefix.strip())), None)
    return None


def _normalize(text: str) -> str:
    return text.replace("’", "'").replace("ʼ", "'").replace("`", "'")


def find_ranges(text: str) -> list[Range]:
    """Ranges with a unit, low < high, in order of appearance."""
    text = _normalize(text)
    found = []
    for match in _RANGE.finditer(text):
        unit = _unit_of(match.group("suffix"), match.group("prefix") or match.group("prefix2"))
        if match.group("lsuffix") and _unit_of(match.group("lsuffix"), None) != unit:
            continue  # "5 MB - 1 GB": two units, not one range
        low, high = parse_number(match.group("low")), parse_number(match.group("high"))
        if unit is None or low is None or high is None or not low < high:
            continue
        found.append(Range(unit, low, high, match.group(0).strip(), match.start(), match.end()))
    return found


def find_quantities(text: str, *, skip_ranges: bool = True) -> list[Quantity]:
    """Single limits in order of appearance (numbers inside a range are left to `find_ranges`)."""
    text = _normalize(text)
    taken = [(r.start, r.end) for r in find_ranges(text)] if skip_ranges else []
    found = []
    for match in _QUANTITY.finditer(text):
        number_start = match.start("pnum") if match.group("pnum") else match.start("num")
        if any(start <= number_start < end for start, end in taken):
            continue
        unit = _unit_of(match.group("suffix"), match.group("prefix"))
        value = parse_number(match.group("pnum") or match.group("num"))
        if unit is None or value is None:
            continue
        comparator = next((c for c in ("min", "max", "gt", "lt") if match.group(c)), "exact")
        # "Must be 8 or more characters" is a lower limit. Without the obligation the sentence may
        # describe the rejected side, so the value stays exact.
        or_more = match.group("more_inner") or match.group("more")
        if or_more and comparator == "exact" and _OBLIGATION_BEFORE.search(text[:match.start()]):
            comparator = "min"
        bare_start = match.start("prefix") if match.group("prefix") else match.start("num")
        found.append(Quantity(
            unit=unit, comparator=comparator, value=value, phrase=match.group(0).strip(),
            bare=text[bare_start:match.end()].strip(), start=match.start(), end=match.end(),
        ))
    return found


def limits(text: str) -> list[Quantity]:
    """Every limit as single quantities: a range counts as its min and its max."""
    result = []
    for r in find_ranges(text):
        result.append(Quantity(r.unit, "min", r.low, r.phrase, r.phrase, r.start, r.end))
        result.append(Quantity(r.unit, "max", r.high, r.phrase, r.phrase, r.start, r.end))
    result += find_quantities(text)
    return sorted(result, key=lambda q: q.start)


def _bounds(quantity: Quantity) -> tuple[Decimal | None, bool, Decimal | None, bool]:
    """(lower, lower inclusive, upper, upper inclusive) in base units."""
    base = quantity.base
    if quantity.comparator == "min":
        return base, True, None, True
    if quantity.comparator == "gt":
        return base, False, None, True
    if quantity.comparator == "max":
        return None, True, base, True
    if quantity.comparator == "lt":
        return None, True, base, False
    return base, True, base, True


def disagree(a: Quantity, b: Quantity) -> bool:
    """True when two limits of the same dimension cannot both hold.

    The same comparator with a different value ("at least 8" vs "at least
    10 characters"), or a lower limit above an upper one ("at least 10" vs
    "at most 8"). Different units of one dimension are converted first, so
    "2 minutes" and "120 seconds" agree. Different currencies never disagree.
    """
    if a.dimension != b.dimension:
        return False
    if a.comparator == b.comparator:
        return a.base != b.base
    if "exact" in (a.comparator, b.comparator):
        return False  # "expires after 30 minutes" vs "at most 60 minutes" can both hold
    for low_q, high_q in ((a, b), (b, a)):
        low, low_inclusive, _, _ = _bounds(low_q)
        _, _, high, high_inclusive = _bounds(high_q)
        if low is not None and high is not None:
            if low > high or (low == high and not (low_inclusive and high_inclusive)):
                return True
    return False


def format_quantity(value: Decimal) -> str:
    return format(value.normalize(), "f") if value == value.to_integral() else str(value.normalize())
