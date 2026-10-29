"""The AI limits hold before a request is sent: parallel requests, unknown usage, failures, prices."""

import json
import threading
import time

import pytest
from pydantic import BaseModel, SecretStr

from spec_to_test.llm import usage as usage_module
from spec_to_test.llm.config import AIConfig
from spec_to_test.llm.providers import AIError, request_structured
from spec_to_test.llm.usage import (
    Budget,
    ModelPrice,
    Usage,
    UsageLedger,
    estimate_input_tokens,
    reset_shared_ledger,
    shared_ledger,
)


class Answer(BaseModel):
    text: str


PRICE = ModelPrice(input_per_mtok=3.0, output_per_mtok=15.0)
SCHEMA_JSON = json.dumps(Answer.model_json_schema())


def worst_case(max_tokens: int) -> int:
    """The reservation of one request with these texts and this output limit."""
    return estimate_input_tokens("sys", "user", SCHEMA_JSON) + max_tokens


def test_reservations_never_add_up_past_the_limit_under_parallel_calls():
    book = UsageLedger(Budget(token_limit=1000))
    granted: list[int] = []
    mutex = threading.Lock()

    def reserve():
        ticket = book.reserve("ollama", "m", 100, 200)  # 300 tokens each
        if ticket is not None:
            with mutex:
                granted.append(ticket)

    threads = [threading.Thread(target=reserve) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert len(granted) == 3  # 3 x 300 = 900 fits; a 4th would cross 1000


def test_parallel_requests_are_refused_before_they_are_sent():
    max_tokens = 500
    book = UsageLedger(Budget(token_limit=int(worst_case(max_tokens) * 2.5)))  # exactly two fit
    config = AIConfig(provider="ollama", model="m", api_key=SecretStr(""), base_url="http://localhost:11434",
                      ledger=book)
    gate = threading.Event()
    entered: list[int] = []
    refused: list[str] = []
    answered: list[str] = []
    mutex = threading.Lock()

    class Client:
        def chat(self, **kwargs):
            with mutex:
                entered.append(1)
            gate.wait(10)  # the request stays in flight until the test lets it finish
            return {"message": {"content": '{"text": "ok"}'}, "done_reason": "stop",
                    "prompt_eval_count": 10, "eval_count": 5}

    def call():
        try:
            request_structured(config, "sys", "user", Answer, lambda c: Client(), max_tokens=max_tokens)
            with mutex:
                answered.append("ok")
        except AIError as error:
            with mutex:
                refused.append(error.code)

    threads = [threading.Thread(target=call) for _ in range(5)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 10
    while (len(entered) < 2 or len(refused) < 3) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (len(entered), refused) == (2, ["budget_exceeded"] * 3)  # refused without reaching the client
    gate.set()
    for thread in threads:
        thread.join(10)
    assert answered == ["ok", "ok"]
    assert book.totals().requests == 2


def test_unknown_usage_stays_counted_at_its_worst_case():
    book = UsageLedger(Budget(token_limit=1000))
    ticket = book.reserve("ollama", "m", 300, 200)  # 500
    book.settle(ticket, Usage())  # the provider reported nothing
    assert book.enforced() == (500, 0.0)
    assert book.reserve("ollama", "m", 300, 300) is None  # 500 + 600 would cross 1000


def test_reported_usage_replaces_the_reservation():
    book = UsageLedger(Budget(token_limit=1000))
    ticket = book.reserve("ollama", "m", 300, 200)
    book.settle(ticket, Usage(input_tokens=40, output_tokens=10))
    assert book.enforced()[0] == 50
    assert book.reserve("ollama", "m", 300, 600) is not None  # 50 + 900 fits


def test_a_failed_request_releases_its_reservation():
    book = UsageLedger(Budget(token_limit=worst_case(500) + 10))

    class Broken:
        def chat(self, **kwargs):
            raise ConnectionError("no route")

    config = AIConfig(provider="ollama", model="m", base_url="http://localhost:11434", ledger=book)
    with pytest.raises(AIError):
        request_structured(config, "sys", "user", Answer, lambda c: Broken(), max_tokens=500)
    assert book.enforced() == (0, 0.0)  # nothing was spent, so nothing stays reserved


def test_an_answer_that_cannot_be_used_keeps_its_worst_case():
    book = UsageLedger(Budget(token_limit=10_000))

    class Garbage:
        def chat(self, **kwargs):
            return {"message": {"content": "not json at all"}, "done_reason": "stop"}

    config = AIConfig(provider="ollama", model="m", base_url="http://localhost:11434", ledger=book)
    with pytest.raises(AIError) as error:
        request_structured(config, "sys", "user", Answer, lambda c: Garbage(), max_tokens=500)
    assert error.value.code == "invalid_response"
    assert book.enforced()[0] == worst_case(500)  # the tokens were spent: counted at the worst case


def test_an_unpriced_model_is_not_covered_by_the_cost_limit_but_the_token_limit_applies():
    book = UsageLedger(Budget(cost_limit=0.000001, token_limit=5000))
    assert book.reserve("ollama", "unpriced", 100, 100) is not None  # no price: the cost limit does not apply
    assert book.reserve("ollama", "unpriced", 4000, 4000) is None  # the token limit still does


def test_a_priced_request_is_refused_when_its_worst_case_cost_would_cross_the_cost_limit():
    book = UsageLedger(Budget(cost_limit=0.01, prices={"anthropic:m": PRICE}))
    assert book.reserve("anthropic", "m", 100, 100) is not None  # about 0.0018 USD
    assert book.reserve("anthropic", "m", 1_000_000, 1000) is None  # about 3 USD worst case


def test_a_priced_request_with_unknown_tokens_counts_its_worst_case_cost():
    book = UsageLedger(Budget(cost_limit=1.0, prices={"anthropic:m": PRICE}))
    ticket = book.reserve("anthropic", "m", 100_000, 100_000)  # 1.8 USD worst case, not affordable
    assert ticket is None
    ticket = book.reserve("anthropic", "m", 1000, 1000)  # 0.018 USD worst case
    book.settle(ticket, Usage())
    assert book.enforced()[1] == pytest.approx((1000 * 3 + 1000 * 15) / 1_000_000)


def test_the_app_has_one_shared_ledger_per_budget():
    reset_shared_ledger()
    budget = Budget(token_limit=100)
    first = shared_ledger(budget)
    assert shared_ledger(Budget(token_limit=100)) is first  # a second tab or reload gets the same counts
    assert shared_ledger(Budget(token_limit=200)) is not first  # a changed budget starts a new count
    reset_shared_ledger()


def test_worst_case_estimate_is_an_upper_bound_for_non_latin_text():
    assert estimate_input_tokens("Перевірка" * 20) >= len("Перевірка" * 20) // 4
    assert usage_module.WRAPPER_TOKENS > 0
