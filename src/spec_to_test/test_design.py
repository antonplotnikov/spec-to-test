"""Black-box test design: Boundary Value Analysis, Equivalence Partitioning
and Decision Tables.

Only facts written in the requirement are used. A technique is applied only
where the requirement gives what it needs (a number with a unit, or an
explicit if/when condition). Outcomes the requirement does not state are
marked "unspecified" instead of being guessed.

"At least" / "at most" / "не повинен перевищувати" include their limit. A
single time or attempt count is read by its preposition: "within 60 seconds"
is a deadline (60 s is still in time), "expires after 30 minutes" / "через
15 хвилин" a delay (the change has not happened at 29 and has at 31; "after
5 attempts" happens on the 5th, "after more than 5 attempts" on the 6th),
"locked for 15 minutes" a duration (still locked at 14, over at 16). Without
such a word the value stays exact, and so do "more than" / "less than": which
side of them is valid depends on the sentence ("passwords longer than 64
characters are rejected").
"""

import re
from decimal import Decimal
from itertools import product
from typing import Literal

from pydantic import BaseModel

from spec_to_test.models import Requirement
from spec_to_test.quantities import Quantity, dimension, find_quantities, find_ranges, to_base
from spec_to_test.rule_engine import _normalize

Expectation = Literal[
    "valid", "invalid", "stated", "unspecified",
    # Deadline ("within 60 seconds"): in time up to the limit, too late after it.
    "in_time", "too_late",
    # Delay ("expires after 30 minutes"): the stated change has not happened yet / has happened.
    "not_yet", "happened",
    # Duration ("locked for 15 minutes"): the stated state still holds / is over.
    "in_effect", "ended",
]
ConstraintKind = Literal["min", "max", "exact", "range"]
Timing = Literal["deadline", "delay", "duration"]

MAX_DECISION_CONDITIONS = 3


class Constraint(BaseModel):
    unit: str
    kind: ConstraintKind
    low: Decimal | None = None
    high: Decimal | None = None
    # How an exact time or attempt count is meant ("within", "after", "for"); None = plain equality.
    timing: Timing | None = None
    # "After more than 5 attempts": the limit itself is not reached yet.
    strict: bool = False
    # Original wording, used as the source reference.
    phrase: str


class TestValue(BaseModel):
    __test__ = False

    value: Decimal
    expectation: Expectation


class BoundaryAnalysis(BaseModel):
    constraint: Constraint
    values: list[TestValue]


class Partition(BaseModel):
    # "below", "inside", "above", "equal", "not_equal"
    name: str
    # Human-readable interval such as "< 8" or "8 – 64".
    interval: str
    representative: Decimal
    expectation: Expectation


class PartitionAnalysis(BaseModel):
    constraint: Constraint
    partitions: list[Partition]


class DecisionRule(BaseModel):
    values: list[bool]
    # None means the requirement does not say what happens.
    outcome: str | None


class DecisionTable(BaseModel):
    conditions: list[str]
    connector: Literal["and", "or"]
    action: str
    otherwise: str | None
    rules: list[DecisionRule]


class TestDesign(BaseModel):
    __test__ = False

    requirement_id: str
    boundaries: list[BoundaryAnalysis] = []
    partitions: list[PartitionAnalysis] = []
    decision_table: DecisionTable | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.boundaries or self.partitions or self.decision_table)


# ---------------------------------------------------------------------------
# Numeric constraints
# ---------------------------------------------------------------------------

# Words right before an exact time ("within 60 seconds", "через 15 хвилин", "locked for 15 minutes")
# or right after it ("30 minutes after it is generated").
_DEADLINE_BEFORE = re.compile(
    r"(?<!\w)(?:within|протягом|впродовж|упродовж|в течение|в течении|в пределах|за)\s*$", re.IGNORECASE
)
_DELAY_BEFORE = re.compile(
    r"(?<!\w)(?:after|через|після|после|спустя|по истечении|(?:expires?|expiring|times? out|ends?)\s+in)\s*$",
    re.IGNORECASE,
)
_DURATION_BEFORE = re.compile(r"(?<!\w)(?:for|на)\s*$", re.IGNORECASE)
_DELAY_AFTER = re.compile(r"^\s*(?:after|later|після|после|спустя)(?!\w)", re.IGNORECASE)
# Units a timing word applies to: "after 5 attempts" is a delay too.
_TIMED_UNITS = frozenset({"attempts"})


def _timing(text: str, quantity: Quantity) -> Timing | None:
    if quantity.dimension != "time" and quantity.unit not in _TIMED_UNITS:
        return None
    before = text[:quantity.start]
    if _DEADLINE_BEFORE.search(before):
        return "deadline"
    if _DELAY_BEFORE.search(before) or _DELAY_AFTER.match(text[quantity.end:]):
        return "delay"
    if _DURATION_BEFORE.search(before):
        return "duration"
    return None


def extract_constraints(text: str) -> list[Constraint]:
    """Return numeric limits stated in the text, merging a lower and an upper limit into a range."""
    text = _normalize(text)
    constraints: list[Constraint] = []
    ranged_units: set[str] = set()

    for found_range in find_ranges(text):
        if found_range.unit not in ranged_units:  # the first range per unit
            constraints.append(Constraint(
                unit=found_range.unit, kind="range", low=found_range.low, high=found_range.high,
                phrase=found_range.phrase,
            ))
            ranged_units.add(found_range.unit)

    # The first lower limit, upper limit and exact value per unit. Strict comparators count as the
    # exact number ("more than 5 attempts" → 5 attempts), as in the rule engine.
    by_unit: dict[str, dict[str, Quantity]] = {}
    for quantity in find_quantities(text, skip_ranges=False):
        if quantity.unit not in ranged_units:
            side = "exact" if quantity.comparator in ("gt", "lt") else quantity.comparator
            by_unit.setdefault(quantity.unit, {}).setdefault(side, quantity)

    for unit, found in by_unit.items():
        if "min" in found and "max" in found:
            low, high = found["min"].value, found["max"].value
            if low < high:
                phrase = f"{found['min'].phrase} … {found['max'].phrase}"
                constraints.append(Constraint(unit=unit, kind="range", low=low, high=high, phrase=phrase))
                continue
        for side, quantity in found.items():
            if side == "min":
                constraints.append(Constraint(unit=unit, kind="min", low=quantity.value, phrase=quantity.phrase))
            elif side == "max":
                constraints.append(Constraint(unit=unit, kind="max", high=quantity.value, phrase=quantity.phrase))
            else:
                timing = _timing(text, quantity)
                strict = quantity.comparator == "gt" and timing == "delay"
                if quantity.comparator in ("gt", "lt") and not strict:
                    timing = None  # "less than 2 seconds", "longer than 64 characters are rejected"
                phrase = quantity.bare if quantity.comparator in ("gt", "lt") and not strict else quantity.phrase
                constraints.append(Constraint(unit=unit, kind="exact", low=quantity.value, high=quantity.value,
                                              timing=timing, strict=strict, phrase=phrase))
    return constraints


def _step(*values: Decimal | None) -> Decimal:
    """Smallest meaningful change: 1 for integers, 0.1 for one decimal place, ..."""
    places = max((-int(v.as_tuple().exponent) for v in values if v is not None), default=0)
    return Decimal(1).scaleb(-max(places, 0))


# Outcome below / at / above an exact timed value.
_TIMED_OUTCOMES: dict[str, tuple[Expectation, Expectation, Expectation]] = {
    "deadline": ("in_time", "in_time", "too_late"),  # "within 60 seconds" includes 60 s
    "delay": ("not_yet", "stated", "happened"),
    "duration": ("in_effect", "stated", "ended"),
}


def _at_limit(constraint: Constraint) -> Expectation:
    below, at, above = _TIMED_OUTCOMES[constraint.timing or "delay"]
    if constraint.strict:  # "after more than 5 attempts": not at the 5th
        return below
    # "Locked after 5 attempts" happens on the 5th; the exact moment of a time limit is left as stated.
    if constraint.timing == "delay" and dimension(constraint.unit) != "time":
        return above
    return at


def boundary_values(constraint: Constraint) -> BoundaryAnalysis:
    step = _step(constraint.low, constraint.high)
    values: list[TestValue] = []

    def add(value: Decimal, expectation: Expectation) -> None:
        if value >= 0 and all(v.value != value for v in values):
            values.append(TestValue(value=value, expectation=expectation))

    low, high = constraint.low, constraint.high
    if constraint.kind in ("min", "range") and low is not None:
        add(low - step, "invalid")
        add(low, "valid")
        add(low + step, "valid")
    if constraint.kind in ("max", "range") and high is not None:
        add(high - step, "valid")
        add(high, "valid")
        add(high + step, "invalid")
    if constraint.kind == "exact" and low is not None:
        if constraint.timing:
            below, _, above = _TIMED_OUTCOMES[constraint.timing]
            add(low - step, below)
            add(low, _at_limit(constraint))
            add(low + step, above)
        else:
            # "The code has 6 digits" says what happens at 6, not around it.
            add(low - step, "unspecified")
            add(low, "stated")
            add(low + step, "unspecified")
    values.sort(key=lambda v: v.value)
    return BoundaryAnalysis(constraint=constraint, values=values)


def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f") if value == value.to_integral() else str(value)


def _half(value: Decimal) -> Decimal:
    half = value / 2
    return half.to_integral_value() if value == value.to_integral() else half


def equivalence_partitions(constraint: Constraint) -> PartitionAnalysis:
    low, high = constraint.low, constraint.high
    parts: list[Partition] = []
    if constraint.kind == "min" and low is not None:
        if low > 0:
            parts.append(Partition(name="below", interval=f"< {_fmt(low)}", representative=_half(low), expectation="invalid"))
        parts.append(Partition(name="inside", interval=f"≥ {_fmt(low)}", representative=low * 2 or _step(low), expectation="valid"))
    elif constraint.kind == "max" and high is not None:
        parts.append(Partition(name="inside", interval=f"≤ {_fmt(high)}", representative=_half(high), expectation="valid"))
        parts.append(Partition(name="above", interval=f"> {_fmt(high)}", representative=high * 2 or _step(high), expectation="invalid"))
    elif constraint.kind == "range" and low is not None and high is not None:
        if low > 0:
            parts.append(Partition(name="below", interval=f"< {_fmt(low)}", representative=_half(low), expectation="invalid"))
        middle = (low + high) / 2
        if low == low.to_integral() and high == high.to_integral():
            middle = middle.to_integral_value()
        parts.append(Partition(name="inside", interval=f"{_fmt(low)} – {_fmt(high)}", representative=middle, expectation="valid"))
        parts.append(Partition(name="above", interval=f"> {_fmt(high)}", representative=high * 2, expectation="invalid"))
    elif constraint.kind == "exact" and low is not None and constraint.timing:
        below, _, above = _TIMED_OUTCOMES[constraint.timing]
        at = _at_limit(constraint)
        before = f"≤ {_fmt(low)}" if at == below else f"< {_fmt(low)}"
        after = f"≥ {_fmt(low)}" if at == above else f"> {_fmt(low)}"
        parts.append(Partition(name="below", interval=before, representative=_half(low) or low / 2, expectation=below))
        parts.append(Partition(name="above", interval=after, representative=low * 2 or _step(low), expectation=above))
    elif constraint.kind == "exact" and low is not None:
        parts.append(Partition(name="equal", interval=f"= {_fmt(low)}", representative=low, expectation="stated"))
        parts.append(Partition(name="not_equal", interval=f"≠ {_fmt(low)}", representative=low * 2 or _step(low), expectation="unspecified"))
    return PartitionAnalysis(constraint=constraint, partitions=parts)


# Data limits probed in a smaller unit when one step of their own is too coarse: the neighbours of
# "at most 1 MB" are 1023 and 1025 KB, not 0 and 2 MB.
_FINER_UNIT = {"gigabytes": "megabytes", "megabytes": "kilobytes"}
_MAX_RELATIVE_STEP = Decimal("0.01")


def _probe_constraint(constraint: Constraint) -> Constraint:
    """The constraint in the unit its test values are written in."""
    finer = _FINER_UNIT.get(constraint.unit)
    limits = [v for v in (constraint.low, constraint.high) if v]
    if finer is None or not limits or _step(*limits) / min(limits) <= _MAX_RELATIVE_STEP:
        return constraint
    factor = to_base(Decimal(1), constraint.unit) / to_base(Decimal(1), finer)

    def convert(value: Decimal | None) -> Decimal | None:
        return None if value is None else (value * factor).normalize() + 0

    return constraint.model_copy(update={"unit": finer, "low": convert(constraint.low), "high": convert(constraint.high)})


# ---------------------------------------------------------------------------
# Decision tables
# ---------------------------------------------------------------------------

_IF = r"if|when|whenever|якщо|коли|если|когда"
_THEN = r"then|тоді|то|тогда"
_LEADING_CONDITION = re.compile(
    rf"^(?:{_IF})\s+(?P<cond>.+?),\s*(?:(?:{_THEN})\s+)?(?P<action>.+)$", re.IGNORECASE | re.DOTALL
)
_TRAILING_CONDITION = re.compile(
    rf"^(?P<action>.+?)\s+(?:{_IF})\s+(?P<cond>[^,]+?)[.!]?$", re.IGNORECASE | re.DOTALL
)
_OTHERWISE = re.compile(
    r"[.;,]?\s*(?:otherwise|else|інакше|в іншому випадку|иначе|в противном случае)\s*,?\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_AND = re.compile(r"\s+(?:and|і|та|й|и)\s+", re.IGNORECASE)
_OR = re.compile(r"\s+(?:or|або|чи|или)\s+", re.IGNORECASE)


def _split_conditions(text: str) -> tuple[list[str], Literal["and", "or"]] | None:
    has_and, has_or = bool(_AND.search(text)), bool(_OR.search(text))
    if has_and and has_or:
        return None  # mixed logic is too easy to misread; leave it to a person
    connector: Literal["and", "or"] = "or" if has_or else "and"
    parts = (_OR if has_or else _AND).split(text) if (has_and or has_or) else [text]
    parts = [p.strip(" ,.") for p in parts]
    # "email and password are valid" is one condition, not two.
    if len(parts) > 1 and any(len(p.split()) < 2 for p in parts):
        parts = [text.strip(" ,.")]
    return parts, connector


def decision_table(text: str) -> DecisionTable | None:
    """Build a table from an explicit if/when condition, or return None."""
    text = _normalize(text).strip()
    match = _LEADING_CONDITION.match(text) or _TRAILING_CONDITION.match(text)
    if not match:
        return None
    action = match.group("action").strip()
    otherwise = None
    if other := _OTHERWISE.search(action):
        otherwise = other.group("rest").strip(" .")
        action = action[: other.start()].strip()
    action = action.strip(" .")
    split = _split_conditions(match.group("cond"))
    if split is None or not action:
        return None
    conditions, connector = split
    if not conditions or len(conditions) > MAX_DECISION_CONDITIONS:
        return None

    rules = []
    for values in product([True, False], repeat=len(conditions)):
        triggered = all(values) if connector == "and" else any(values)
        rules.append(DecisionRule(values=list(values), outcome=action if triggered else otherwise))
    return DecisionTable(
        conditions=conditions, connector=connector, action=action, otherwise=otherwise, rules=rules
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def design_tests(requirement: Requirement) -> TestDesign:
    constraints = [_probe_constraint(c) for c in extract_constraints(requirement.text)]
    return TestDesign(
        requirement_id=requirement.id,
        boundaries=[boundary_values(c) for c in constraints],
        partitions=[equivalence_partitions(c) for c in constraints],
        decision_table=decision_table(requirement.text),
    )


def format_value(value: Decimal) -> str:
    return _fmt(value)
