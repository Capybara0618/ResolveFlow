"""Preparation and source-review CLI. No implicit model execution or quality claims."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.customer_agent_eval_v2 import digest, read_json, write_new
from scripts.customer_quantification_agent import runs
from scripts.evaluation.customer_quantification_data import ROOT, audit
from scripts.evaluation.customer_quantification_metrics import (
    review_template,
    summarize,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["audit", "review-template", "summarize"])
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "audit":
        report = audit()
        report.update(production_code_changed=False, live_executed=False, measured_effect=None,
            conversation_run_limit=128, customer_turn_run_limit=200,
            suggested_new_request_ceiling=800, provider_allowance_authorized=False,
            estimate="100 fixed customer turns about 3 calls each; 100 dynamic turns about 2-4; actual may vary",
            theoretical_per_run_call_ceiling=2400,
            original_failure_regression="reports/customer-final-acceptance-v1/README.md")
    else:
        if not args.runtime:
            parser.error("--runtime required")
        runtime = read_json(args.runtime)
        if args.mode == "review-template":
            report = review_template(runtime, runs())
            report["runtime_sha256"] = digest(args.runtime)
        else:
            if not args.review:
                parser.error("--review required")
            review = read_json(args.review)
            if review.get("runtime_sha256") != digest(args.runtime):
                raise ValueError("review does not bind this exact immutable runtime file")
            report = summarize(runtime, runs(), review)
            report.update(runtime_sha256=digest(args.runtime), review_sha256=digest(args.review))
    write_new(args.output, report)
    print({"mode": args.mode, "output": str(args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT)
                                           else args.output), "new_provider_requests": 0})
