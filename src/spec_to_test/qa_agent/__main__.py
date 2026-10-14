"""Run a QA plan from the command line.

    AUTOMATION_ALLOWED_HOSTS=127.0.0.1:8765 AUTOMATION_ALLOW_PRIVATE_NETWORK=true \\
    AUTOMATION_SECRET_DEMO_PASSWORD=demo-pass-123 \\
    python -m spec_to_test.qa_agent --plan ../examples/qa_demo/plan.json \\
        --url http://127.0.0.1:8765/ --approve-all --authorized --out ../qa-demo-output

Approval is explicit: --approve QA-001,QA-002 or --approve-all, and
--authorized confirms you may test the target. Exit code: 0 when every
executed case passed, 1 when a case failed or was blocked, 2 on a usage error.
"""

import argparse
import sys
from pathlib import Path

from spec_to_test.input_parser import extract_requirements
from spec_to_test.qa_agent.planner import PlanError, approve, import_plan
from spec_to_test.qa_agent.report import bundle, markdown_report
from spec_to_test.qa_agent.safety import load_qa_settings
from spec_to_test.qa_agent.service import QAError, run_cases
from spec_to_test.qa_agent.store import RunStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m spec_to_test.qa_agent", description="Run an approved QA plan.")
    parser.add_argument("--plan", required=True, type=Path, help="plan JSON (exported from the QA Agent page)")
    parser.add_argument("--url", help="target URL (default: the plan's target_url)")
    parser.add_argument("--requirements", type=Path, help="requirements document, for the coverage table")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--approve", help="comma-separated case IDs to approve")
    group.add_argument("--approve-all", action="store_true", help="approve every case that can be approved")
    parser.add_argument("--authorized", action="store_true", help="confirm you are authorized to test the target")
    parser.add_argument("--allow-destructive", action="store_true", help="allow delete/pay/... actions")
    parser.add_argument("--out", type=Path, default=Path("qa-output"), help="folder for runs and the report")
    args = parser.parse_args(argv)

    if not args.authorized:
        print("Refusing to run: pass --authorized to confirm you may test this application.", file=sys.stderr)
        return 2
    try:
        plan = import_plan(args.plan.read_bytes(), "")
    except (OSError, PlanError) as error:
        print(f"Cannot read the plan: {error}", file=sys.stderr)
        return 2
    wanted = None if args.approve_all else {x.strip() for x in args.approve.split(",") if x.strip()}
    for case in plan.cases:
        if wanted is None or case.id in wanted:
            try:
                approve(case)
            except PlanError as error:
                print(f"{case.id}: not approved ({error.code})", file=sys.stderr)
    requirements = extract_requirements(args.requirements.read_text(encoding="utf-8")) if args.requirements else None

    store = RunStore(args.out)
    try:
        run = run_cases(
            plan.cases, args.url or plan.target_url, load_qa_settings(), store, authorized=True,
            allow_destructive=args.allow_destructive, document_title=args.plan.name,
            on_progress=lambda done, total, r: print(f"[{done}/{total}] {r.case_id} {r.status.value.upper()}"
                                                     + (f" ({r.reason})" if r.reason else "")),
        )
    except QAError as error:
        print(f"Run refused: {error.code} {error.params or ''}".rstrip(), file=sys.stderr)
        return 2
    run_dir = store.run_dir(run.id)
    (run_dir / "report.md").write_text(markdown_report(run, requirements), encoding="utf-8")
    (run_dir / "qa-report.zip").write_bytes(bundle(run, run_dir, requirements))
    counts = run.counts()
    print(f"Run {run.id}: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + f"; bugs {len(run.bugs)}")
    print(f"Report: {run_dir / 'report.md'}")
    return 1 if counts["failed"] or counts["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
