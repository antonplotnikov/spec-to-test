"""Optional: the evaluation suite against the real configured provider.

Skipped unless SPEC_TO_TEST_LIVE_AI=1 and a provider is configured (AI_PROVIDER and
its key in the environment). It costs API credits and is never run in CI:

    SPEC_TO_TEST_LIVE_AI=1 AI_PROVIDER=anthropic ANTHROPIC_API_KEY=... pytest -m live_ai
"""

import os

import pytest

from spec_to_test.evaluation import check_thresholds, load_thresholds, run_suite
from spec_to_test.llm.config import choose, load_settings
from spec_to_test.llm.providers import default_client_factory

pytestmark = pytest.mark.live_ai

# Captured before the autouse fixture in conftest.py switches AI off for every test.
LIVE_ENV = {k: v for k, v in os.environ.items() if k.startswith(("AI_", "ANTHROPIC_", "OPENAI_", "OLLAMA_"))}


@pytest.mark.skipif(os.environ.get("SPEC_TO_TEST_LIVE_AI") != "1", reason="set SPEC_TO_TEST_LIVE_AI=1 to call a real model")
def test_live_model_meets_the_live_thresholds():
    config = choose(load_settings(LIVE_ENV, env_file=None))
    if config is None:
        pytest.skip("no AI provider configured")
    result = run_suite(config=config, client_factory=default_client_factory, mode="live")
    print(result.to_markdown())
    totals = result.totals()
    # Whatever the model says, nothing untraceable may reach the user.
    assert totals["hallucination_accepted"] in (0, None) and totals["invented_requirements"] == 0
    assert check_thresholds(result, load_thresholds()["live"]) == []
