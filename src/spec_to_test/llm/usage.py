"""AI usage, estimated cost and limits of the running app.

- The budget belongs to the operator: the API key and what it costs are the operator's, not a browser
  tab's. So one ledger serves the whole running app (see shared_ledger). Its counters are kept in
  memory: restarting the app starts them at zero, which is stated in the sidebar and the docs.
- Tokens come from the provider's own answer. A count the provider does not report stays unknown
  (None) in the totals, and it is never counted as zero.
- Limits are checked BEFORE a request is sent (reserve). A request reserves its worst case: the
  estimated input tokens plus the output limit it asks for. Reservations are made under one lock, so
  parallel requests cannot all pass the check and overshoot together. When the answer arrives, the
  reservation is replaced by the reported usage (settle). A request that fails releases its
  reservation (release): its tokens are then not counted (see the docs).
- A request whose usage is unknown keeps its worst-case reservation in the limit check. So an answer
  the provider did not measure still counts against the limit.
- Cost = tokens x the price configured for that provider and model (AI_PRICES, USD per million
  tokens). No price is built in, because prices change. A model without a configured price has an
  unknown cost (shown as unknown, never 0) and is not covered by the cost limit: the token limit still
  applies to it.
- The app warns from WARN_AT of a limit on, and refuses new requests once a reservation would cross it.
"""

import json
import math
import threading
from collections.abc import Mapping

from pydantic import BaseModel, Field

WARN_AT = 0.8
# Characters per token are about 4 in English and fewer in other languages. Two characters per token,
# plus a fixed allowance for the message wrapper, is an estimate that errs on the high side.
CHARS_PER_TOKEN_UPPER_BOUND = 2
WRAPPER_TOKENS = 64


class ModelPrice(BaseModel):
    input_per_mtok: float = Field(ge=0)  # USD per million input tokens
    output_per_mtok: float = Field(ge=0)  # USD per million output tokens


class Budget(BaseModel):
    token_limit: int | None = None  # input + output tokens for the whole app
    cost_limit: float | None = None  # USD for the whole app, priced requests only
    prices: dict[str, ModelPrice] = Field(default_factory=dict)  # "provider:model" -> price
    # "invalid" when a limit or the prices could not be read; that setting is then left off.
    problem: str = ""


class Usage(BaseModel):
    """What one answer reported. None = not reported."""

    input_tokens: int | None = None
    output_tokens: int | None = None


class Entry(BaseModel):
    provider: str
    model: str
    input_tokens: int | None  # as reported; None when not reported
    output_tokens: int | None
    cost_usd: float | None  # None when the tokens or the price are unknown
    # What the limit check counts for this request: its worst case, used when the usage is unknown.
    bound_tokens: int = 0
    bound_cost: float | None = None  # None when the model has no price


class Totals(BaseModel):
    requests: int = 0
    input_tokens: int = 0  # known counts only
    output_tokens: int = 0
    unknown_token_requests: int = 0
    cost_usd: float = 0.0  # priced requests with known tokens only
    unpriced_requests: int = 0  # requests that are not in cost_usd

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class _Pending(BaseModel):
    provider: str
    model: str
    bound_tokens: int
    bound_cost: float | None


def estimate_input_tokens(*texts: str) -> int:
    """An upper estimate of the input tokens of the given texts (see CHARS_PER_TOKEN_UPPER_BOUND)."""
    return sum(len(text) for text in texts) // CHARS_PER_TOKEN_UPPER_BOUND + WRAPPER_TOKENS


def _known_tokens(usage: Usage) -> int | None:
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    return usage.input_tokens + usage.output_tokens


def _totals(entries: list[Entry]) -> Totals:
    totals = Totals(requests=len(entries))
    for entry in entries:
        if entry.input_tokens is None or entry.output_tokens is None:
            totals.unknown_token_requests += 1
        else:
            totals.input_tokens += entry.input_tokens
            totals.output_tokens += entry.output_tokens
        if entry.cost_usd is None:
            totals.unpriced_requests += 1
        else:
            totals.cost_usd += entry.cost_usd
    return totals


class UsageLedger:
    """The usage and the reservations of the running app. Every method is safe to call from any thread."""

    def __init__(self, budget: Budget) -> None:
        self.budget = budget
        self.entries: list[Entry] = []
        self._pending: dict[int, _Pending] = {}
        self._next_ticket = 1
        self._lock = threading.Lock()

    # --- prices and bounds -------------------------------------------------------------------

    def price_of(self, provider: str, model: str) -> ModelPrice | None:
        return self.budget.prices.get(f"{provider}:{model}")

    def _bound_cost(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> float | None:
        price = self.price_of(provider, model)
        if price is None:
            return None
        return (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1_000_000

    # --- the limit check (enforced amounts include unknown requests at their worst case) -----

    def _enforced_tokens_locked(self) -> int:
        total = 0
        for e in self.entries:
            known = _entry_tokens(e)
            total += e.bound_tokens if known is None else known
        return total + sum(p.bound_tokens for p in self._pending.values())

    def _enforced_cost_locked(self) -> float:
        total = 0.0
        for e in self.entries:
            if e.bound_cost is None:
                continue  # unpriced: not covered by the cost limit
            total += e.cost_usd if e.cost_usd is not None else e.bound_cost
        total += sum(p.bound_cost for p in self._pending.values() if p.bound_cost is not None)
        return total

    def reserve(self, provider: str, model: str, input_estimate: int, output_limit: int) -> int | None:
        """Reserve the worst case of a request before it is sent. Returns a ticket, or None when the
        request would cross a limit (it must then not be sent)."""
        bound_tokens = input_estimate + output_limit
        bound_cost = self._bound_cost(provider, model, input_estimate, output_limit)
        with self._lock:
            if self.budget.token_limit is not None and self._enforced_tokens_locked() + bound_tokens > self.budget.token_limit:
                return None
            if (self.budget.cost_limit is not None and bound_cost is not None
                    and self._enforced_cost_locked() + bound_cost > self.budget.cost_limit):
                return None
            ticket = self._next_ticket
            self._next_ticket += 1
            self._pending[ticket] = _Pending(provider=provider, model=model, bound_tokens=bound_tokens,
                                             bound_cost=bound_cost)
            return ticket

    def settle(self, ticket: int, usage: Usage) -> Entry:
        """Replace a reservation with the usage the answer reported."""
        with self._lock:
            pending = self._pending.pop(ticket, None)
            if pending is None:
                raise KeyError(f"no reservation {ticket}")
            cost = None
            tokens = _known_tokens(usage)
            if pending.bound_cost is not None and tokens is not None:
                cost = self._actual_cost(pending.provider, pending.model, usage)
            entry = Entry(provider=pending.provider, model=pending.model, input_tokens=usage.input_tokens,
                          output_tokens=usage.output_tokens, cost_usd=cost, bound_tokens=pending.bound_tokens,
                          bound_cost=pending.bound_cost)
            self.entries.append(entry)
            return entry

    def release(self, ticket: int) -> None:
        """Drop a reservation whose request failed before an answer arrived."""
        with self._lock:
            self._pending.pop(ticket, None)

    def _actual_cost(self, provider: str, model: str, usage: Usage) -> float | None:
        price = self.price_of(provider, model)
        if price is None or usage.input_tokens is None or usage.output_tokens is None:
            return None
        return (usage.input_tokens * price.input_per_mtok + usage.output_tokens * price.output_per_mtok) / 1_000_000

    def record(self, provider: str, model: str, usage: Usage) -> Entry:
        """Record a request without a reservation (no check is made)."""
        tokens = _known_tokens(usage)
        bound_cost = self._bound_cost(provider, model, usage.input_tokens or 0, usage.output_tokens or 0)
        with self._lock:
            entry = Entry(provider=provider, model=model, input_tokens=usage.input_tokens,
                          output_tokens=usage.output_tokens, cost_usd=self._actual_cost(provider, model, usage),
                          bound_tokens=tokens or 0, bound_cost=bound_cost)
            self.entries.append(entry)
            return entry

    # --- figures for the sidebar and the tests ---------------------------------------------------

    def totals(self) -> Totals:
        with self._lock:
            return _totals(list(self.entries))

    def by_model(self) -> dict[str, Totals]:
        """Totals per "provider · model", in order of first use."""
        with self._lock:
            entries = list(self.entries)
        groups: dict[str, list[Entry]] = {}
        for entry in entries:
            groups.setdefault(f"{entry.provider} · {entry.model}", []).append(entry)
        return {key: _totals(items) for key, items in groups.items()}

    def enforced(self) -> tuple[int, float]:
        """(tokens, cost) the limits are checked against: unknown requests at their worst case, and
        requests in flight included."""
        with self._lock:
            return self._enforced_tokens_locked(), self._enforced_cost_locked()

    def exceeded(self) -> str:
        """"tokens" or "cost" when a limit is reached, else ""."""
        tokens, cost = self.enforced()
        if self.budget.token_limit is not None and tokens >= self.budget.token_limit:
            return "tokens"
        if self.budget.cost_limit is not None and cost >= self.budget.cost_limit:
            return "cost"
        return ""

    def warning(self) -> str:
        """"tokens" or "cost" once a limit is WARN_AT of the way there (and not yet reached), else ""."""
        tokens, cost = self.enforced()
        if self.budget.token_limit is not None and tokens >= WARN_AT * self.budget.token_limit:
            return "tokens"
        if self.budget.cost_limit is not None and cost >= WARN_AT * self.budget.cost_limit:
            return "cost"
        return ""


def _entry_tokens(entry: Entry) -> int | None:
    return _known_tokens(Usage(input_tokens=entry.input_tokens, output_tokens=entry.output_tokens))


_SHARED: UsageLedger | None = None
_SHARED_LOCK = threading.Lock()


def shared_ledger(budget: Budget) -> UsageLedger:
    """The one ledger of this running app. Every browser session uses it, so a second tab or a page
    reload cannot start a new budget. A changed budget (only possible in tests) starts a new ledger."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None or _SHARED.budget != budget:
            _SHARED = UsageLedger(budget)
        return _SHARED


def reset_shared_ledger() -> None:
    """Forget the app's usage (tests only)."""
    global _SHARED
    with _SHARED_LOCK:
        _SHARED = None


def valid_number(value: object, *, minimum: float = 0.0, strict_minimum: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return False
    return value > minimum if strict_minimum else value >= minimum


TOKEN_LIMIT = "AI_TOKEN_LIMIT"
COST_LIMIT = "AI_COST_LIMIT_USD"
PRICES = "AI_PRICES"
BUDGET_KEYS = (TOKEN_LIMIT, COST_LIMIT, PRICES)


def _positive_int(raw: str) -> int | None:
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _positive_float(raw: str) -> float | None:
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if valid_number(value, strict_minimum=True) else None


def _prices(raw: str) -> dict[str, ModelPrice] | None:
    """{"provider:model": {"input": USD per million, "output": USD per million}}, or None if malformed."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    prices = {}
    for key, value in data.items():
        if not isinstance(key, str) or ":" not in key or not isinstance(value, dict):
            return None
        try:
            prices[key.strip()] = ModelPrice(input_per_mtok=value["input"], output_per_mtok=value["output"])
        except (KeyError, TypeError, ValueError):
            return None
    return prices


def parse_budget(values: Mapping[str, str]) -> Budget:
    """Limits and prices from the settings values. A setting that cannot be read is left off and flagged."""
    budget = Budget()
    invalid = False
    if raw := values.get(TOKEN_LIMIT, "").strip():
        budget.token_limit = _positive_int(raw)
        invalid = invalid or budget.token_limit is None
    if raw := values.get(COST_LIMIT, "").strip():
        budget.cost_limit = _positive_float(raw)
        invalid = invalid or budget.cost_limit is None
    if raw := values.get(PRICES, "").strip():
        prices = _prices(raw)
        invalid = invalid or prices is None
        budget.prices = prices or {}
    budget.problem = "invalid" if invalid else ""
    return budget

