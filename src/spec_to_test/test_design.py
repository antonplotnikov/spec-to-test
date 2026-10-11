"""Black-box test design: Boundary Value Analysis, Equivalence Partitioning
and Decision Tables.

Only facts written in the requirement are used. A technique is applied only
where the requirement gives what it needs (a number with a unit, or an
explicit if/when condition). Outcomes the requirement does not state are
marked "unspecified" instead of being guessed.
"""

import re
from decimal import Decimal
from itertools import product
from typing import Literal

from pydantic import BaseModel

from spec_to_test.models import Requirement
from spec_to_test.rule_engine import UNITS, _normalize, _quantities

Expectation = Literal["valid", "invalid", "stated", "unspecified"]
ConstraintKind = Literal["min", "max", "exact", "range"]

MAX_DECISION_CONDITIONS = 3


class Constraint(BaseModel):
    unit: str
    kind: ConstraintKind
    low: Decimal | None = None
    high: Decimal | None = None
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

_RANGE = {
    unit: re.compile(
        r"(?:(?<!\w)(?:between|from|від|от|между)\s+)?"
        r"(?P<low>\d+(?:[.,]\d+)?)\s*(?:and|to|до|і|и|[-–])\s*(?P<high>\d+(?:[.,]\d+)?)\s*"
        rf"(?:{pattern})(?!\w)",
        re.IGNORECASE,
    )
    for unit, pattern in UNITS.items()
}


def _number(text: str) -> Decimal:
    return Decimal(text.replace(",", "."))


def extract_constraints(text: str) -> list[Constraint]:
    """Return numeric limits stated in the text, merging min+max into a range."""
    text = _normalize(text)
    constraints: list[Constraint] = []
    ranged_units: set[str] = set()

    for unit, pattern in _RANGE.items():
        for match in pattern.finditer(text):
            low, high = _number(match.group("low")), _number(match.group("high"))
            if low < high:
                constraints.append(
                    Constraint(unit=unit, kind="range", low=low, high=high, phrase=match.group(0).strip())
                )
                ranged_units.add(unit)
                break

    by_unit: dict[str, dict[str, tuple[str, str]]] = {}
    for (unit, comparator), quantity in _quantities(text).items():
        if unit not in ranged_units:
            by_unit.setdefault(unit, {})[comparator] = quantity

    for unit, found in by_unit.items():
        if "min" in found and "max" in found:
            low, high = _number(found["min"][0]), _number(found["max"][0])
            if low < high:
                phrase = f"{found['min'][1]} … {found['max'][1]}"
                constraints.append(Constraint(unit=unit, kind="range", low=low, high=high, phrase=phrase))
                continue
        for comparator, (number, phrase) in found.items():
            value = _number(number)
            if comparator == "min":
                constraints.append(Constraint(unit=unit, kind="min", low=value, phrase=phrase))
            elif comparator == "max":
                constraints.append(Constraint(unit=unit, kind="max", high=value, phrase=phrase))
            else:
                constraints.append(Constraint(unit=unit, kind="exact", low=value, high=value, phrase=phrase))
    return constraints


def _step(*values: Decimal | None) -> Decimal:
    """Smallest meaningful change: 1 for integers, 0.1 for one decimal place, ..."""
    places = max((-int(v.as_tuple().exponent) for v in values if v is not None), default=0)
    return Decimal(1).scaleb(-max(places, 0))


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
        # "Expires after 30 minutes" says what happens at 30, not around it.
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
    elif constraint.kind == "exact" and low is not None:
        parts.append(Partition(name="equal", interval=f"= {_fmt(low)}", representative=low, expectation="stated"))
        parts.append(Partition(name="not_equal", interval=f"≠ {_fmt(low)}", representative=low * 2 or _step(low), expectation="unspecified"))
    return PartitionAnalysis(constraint=constraint, partitions=parts)


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
    constraints = extract_constraints(requirement.text)
    return TestDesign(
        requirement_id=requirement.id,
        boundaries=[boundary_values(c) for c in constraints],
        partitions=[equivalence_partitions(c) for c in constraints],
        decision_table=decision_table(requirement.text),
    )


def format_value(value: Decimal) -> str:
    return _fmt(value)
