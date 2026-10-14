"""Repeatable quality evaluation of the Grill AI (question relevance, duplication,
requirement coverage, hallucinations, test case quality).

    python -m spec_to_test.evaluation              # scripted model, deterministic (CI)
    python -m spec_to_test.evaluation --rules-only # built-in questions only, for comparison
    python -m spec_to_test.evaluation --live       # the configured real provider (optional, costs money)

See runner.py for the metrics and cases.py for the fixture format.
"""

from .cases import EvalCase, load_cases
from .runner import CaseResult, SuiteResult, check_thresholds, load_thresholds, run_case, run_suite

__all__ = [
    "CaseResult", "EvalCase", "SuiteResult", "check_thresholds", "load_cases", "load_thresholds", "run_case", "run_suite",
]
