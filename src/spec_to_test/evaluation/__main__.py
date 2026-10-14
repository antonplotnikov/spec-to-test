"""Command line: python -m spec_to_test.evaluation [--live | --rules-only] [--json FILE] [--markdown FILE]

Exits with 1 when a threshold in thresholds.json is not met, 2 when --live has
no usable provider configured.
"""

import argparse
import json
import sys
from pathlib import Path

from spec_to_test.llm.config import choose, load_settings
from spec_to_test.llm.providers import default_client_factory

from .cases import FIXTURES_DIR, load_cases
from .runner import check_thresholds, load_thresholds, run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m spec_to_test.evaluation", description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--live", action="store_true", help="call the configured provider (AI_PROVIDER, keys from env/.env)")
    group.add_argument("--rules-only", action="store_true", help="no AI at all: the built-in questions only")
    parser.add_argument("--cases", type=Path, default=FIXTURES_DIR, help="folder of case files")
    parser.add_argument("--json", type=Path, help="write the full result as JSON")
    parser.add_argument("--markdown", type=Path, help="write the summary as Markdown")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    if args.live:
        config = choose(load_settings())
        if config is None:
            print("No AI provider configured (set AI_PROVIDER and its key).", file=sys.stderr)
            return 2
        result = run_suite(cases, config=config, client_factory=default_client_factory, mode="live")
        mode = "live"
    else:
        result = run_suite(cases, use_ai=not args.rules_only)
        mode = "rules" if args.rules_only else "scripted"
    failures = check_thresholds(result, load_thresholds().get(mode, {}))
    summary = result.to_markdown(failures)
    print(summary)
    if args.json:
        args.json.write_text(json.dumps({**result.to_data(), "failures": failures}, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(summary, encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
