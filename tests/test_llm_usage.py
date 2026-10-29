"""AI usage and cost: tokens from the answers, prices from the operator, limits per session."""

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, SecretStr

from spec_to_test.llm.config import AIConfig, load_settings
from spec_to_test.llm.providers import AIError, request_structured
from spec_to_test.llm.usage import Budget, ModelPrice, Usage, UsageLedger, parse_budget


class Answer(BaseModel):
    text: str


PRICE = ModelPrice(input_per_mtok=3.0, output_per_mtok=15.0)


def ledger(token_limit=None, cost_limit=None, prices=None) -> UsageLedger:
    return UsageLedger(Budget(token_limit=token_limit, cost_limit=cost_limit, prices=prices or {}))


# --- Cost and totals ----------------------------------------------------------------------------

def test_a_priced_request_costs_its_tokens_times_the_configured_price():
    book = ledger(prices={"anthropic:m": PRICE})
    entry = book.record("anthropic", "m", Usage(input_tokens=1_000_000, output_tokens=100_000))
    assert entry.cost_usd == pytest.approx(3.0 + 1.5)
    assert book.totals().cost_usd == pytest.approx(4.5)


def test_an_unpriced_model_has_an_unknown_cost_never_zero():
    book = ledger()
    entry = book.record("ollama", "llama3", Usage(input_tokens=10, output_tokens=5))
    totals = book.totals()
    assert entry.cost_usd is None
    assert (totals.requests, totals.unpriced_requests, totals.tokens) == (1, 1, 15)


def test_a_request_without_reported_tokens_is_unknown_and_not_priced():
    book = ledger(prices={"anthropic:m": PRICE})
    entry = book.record("anthropic", "m", Usage())
    totals = book.totals()
    assert entry.cost_usd is None
    assert (totals.unknown_token_requests, totals.tokens) == (1, 0)


# --- Limits ---------------------------------------------------------------------------------------

def test_the_token_limit_warns_from_80_percent_and_refuses_at_100():
    book = ledger(token_limit=100)
    book.record("ollama", "m", Usage(input_tokens=50, output_tokens=20))
    assert (book.warning(), book.exceeded()) == ("", "")
    book.record("ollama", "m", Usage(input_tokens=10, output_tokens=5))
    assert (book.warning(), book.exceeded()) == ("tokens", "")
    book.record("ollama", "m", Usage(input_tokens=10, output_tokens=5))
    assert book.exceeded() == "tokens"


def test_the_cost_limit_counts_priced_requests_only():
    book = ledger(cost_limit=1.0, prices={"anthropic:m": PRICE})
    book.record("ollama", "unpriced", Usage(input_tokens=10_000_000, output_tokens=10_000_000))
    assert book.exceeded() == ""  # the unpriced request does not count toward the cost limit
    book.record("anthropic", "m", Usage(input_tokens=1_000_000, output_tokens=0))  # 3.0 USD
    assert book.exceeded() == "cost"


# --- Settings -------------------------------------------------------------------------------------

def test_empty_settings_mean_no_limits_and_no_problem():
    assert parse_budget({}) == Budget()


def test_valid_settings_are_read():
    budget = parse_budget({"AI_TOKEN_LIMIT": "500", "AI_COST_LIMIT_USD": "2.5",
                           "AI_PRICES": '{"anthropic:claude-x": {"input": 3, "output": 15}}'})
    assert (budget.token_limit, budget.cost_limit, budget.problem) == (500, 2.5, "")
    assert budget.prices["anthropic:claude-x"] == PRICE


@pytest.mark.parametrize(("values", "field"), [
    ({"AI_TOKEN_LIMIT": "lots"}, "token_limit"),
    ({"AI_TOKEN_LIMIT": "0"}, "token_limit"),
    ({"AI_COST_LIMIT_USD": "nan"}, "cost_limit"),
    ({"AI_COST_LIMIT_USD": "-1"}, "cost_limit"),
    ({"AI_PRICES": "not json"}, "prices"),
    ({"AI_PRICES": '{"noprovider": {"input": 1, "output": 1}}'}, "prices"),
    ({"AI_PRICES": '{"a:b": {"input": -1, "output": 1}}'}, "prices"),
])
def test_an_unreadable_setting_is_left_off_and_flagged(values, field):
    budget = parse_budget(values)
    assert budget.problem == "invalid"
    assert getattr(budget, field) in (None, {})


def test_limits_are_read_from_the_environment(tmp_path):
    settings = load_settings({"AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "key", "AI_TOKEN_LIMIT": "500"},
                             env_file=tmp_path / "none.env")
    assert settings.budget.token_limit == 500


# --- Tokens from each provider's answer -------------------------------------------------------------

def _factory(client):
    return lambda config: client


def test_anthropic_answers_record_their_usage():
    message = MagicMock(parsed_output=Answer(text="ok"), stop_reason="end_turn")
    message.usage.input_tokens, message.usage.output_tokens = 12, 7
    client = MagicMock()
    client.messages.parse.return_value = message
    book = ledger(prices={"anthropic:m": PRICE})
    config = AIConfig(provider="anthropic", model="m", api_key=SecretStr("k"), ledger=book)
    assert request_structured(config, "sys", "user", Answer, _factory(client)).text == "ok"
    assert [(e.input_tokens, e.output_tokens) for e in book.entries] == [(12, 7)]


def test_openai_answers_record_their_usage():
    choice = MagicMock(finish_reason="stop")
    choice.message.parsed = Answer(text="ok")
    choice.message.refusal = None
    completion = MagicMock(choices=[choice])
    completion.usage.prompt_tokens, completion.usage.completion_tokens = 20, 3
    client = MagicMock()
    client.chat.completions.parse.return_value = completion
    book = ledger()
    config = AIConfig(provider="openai", model="gpt", api_key=SecretStr("k"), ledger=book)
    request_structured(config, "sys", "user", Answer, _factory(client))
    assert [(e.input_tokens, e.output_tokens) for e in book.entries] == [(20, 3)]


def test_compatible_server_answers_record_their_usage():
    client = MagicMock()
    client.chat.return_value = {
        "choices": [{"finish_reason": "stop", "message": {"content": '{"text": "ok"}'}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 4},
    }
    book = ledger()
    config = AIConfig(provider="openai_compatible", model="local", base_url="http://localhost:8000/v1", ledger=book)
    request_structured(config, "sys", "user", Answer, _factory(client))
    assert [(e.input_tokens, e.output_tokens) for e in book.entries] == [(30, 4)]


def test_ollama_answers_record_their_usage():
    client = MagicMock()
    client.chat.return_value = {"message": {"content": '{"text": "ok"}'}, "done_reason": "stop",
                                "prompt_eval_count": 40, "eval_count": 5}
    book = ledger()
    config = AIConfig(provider="ollama", model="llama", base_url="http://localhost:11434", ledger=book)
    request_structured(config, "sys", "user", Answer, _factory(client))
    assert [(e.input_tokens, e.output_tokens) for e in book.entries] == [(40, 5)]


def test_a_provider_that_reports_no_usage_is_recorded_as_unknown():
    client = MagicMock()
    client.chat.return_value = {"message": {"content": '{"text": "ok"}'}, "done_reason": "stop"}
    book = ledger()
    config = AIConfig(provider="ollama", model="llama", base_url="http://localhost:11434", ledger=book)
    request_structured(config, "sys", "user", Answer, _factory(client))
    assert [(e.input_tokens, e.output_tokens) for e in book.entries] == [(None, None)]


# --- Refusing a request over the limit ----------------------------------------------------------------

def test_a_request_over_the_limit_is_refused_before_it_is_sent():
    book = ledger(token_limit=10)
    book.record("ollama", "m", Usage(input_tokens=10, output_tokens=0))
    client_factory = MagicMock()
    config = AIConfig(provider="ollama", model="m", base_url="http://localhost:11434", ledger=book)
    with pytest.raises(AIError) as error:
        request_structured(config, "sys", "user", Answer, client_factory)
    assert error.value.code == "budget_exceeded"
    client_factory.assert_not_called()


def test_without_a_ledger_nothing_is_counted_or_refused():
    client = MagicMock()
    client.chat.return_value = {"message": {"content": '{"text": "ok"}'}, "done_reason": "stop",
                                "prompt_eval_count": 1, "eval_count": 1}
    config = AIConfig(provider="ollama", model="llama", base_url="http://localhost:11434")
    assert request_structured(config, "sys", "user", Answer, _factory(client)).text == "ok"
    assert config.ledger is None


def test_the_ledger_is_not_written_out_with_the_configuration():
    config = AIConfig(provider="ollama", model="llama", base_url="http://localhost:11434", ledger=ledger())
    assert "ledger" not in config.model_dump()
    assert "ledger" not in repr(config)


def test_cost_and_tokens_are_kept_per_provider_and_model():
    book = ledger(prices={"anthropic:m": PRICE})
    book.record("anthropic", "m", Usage(input_tokens=1_000_000, output_tokens=0))
    book.record("ollama", "llama", Usage(input_tokens=5, output_tokens=5))
    book.record("anthropic", "m", Usage(input_tokens=0, output_tokens=1_000_000))
    parts = book.by_model()
    assert list(parts) == ["anthropic · m", "ollama · llama"]
    assert (parts["anthropic · m"].requests, parts["anthropic · m"].cost_usd) == (2, pytest.approx(18.0))
    assert (parts["ollama · llama"].unpriced_requests, parts["ollama · llama"].tokens) == (1, 10)
