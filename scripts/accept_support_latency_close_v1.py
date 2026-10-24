"""Reuse the tested three-turn live driver under a separate immutable latency manifest."""

from __future__ import annotations

import sys
from unittest.mock import patch

from scripts import accept_support_policy_batch_live_v1 as base
from scripts.customer_agent_eval_v2 import digest, read_json
from scripts.customer_rag_live_v2 import persist

VERSION = "customer-latency-close-live-v1"
PLAN = base.ROOT / "evals" / VERSION / "manifest.json"
SCENARIOS = PLAN.with_name("scenarios.json")
OUT = base.ROOT / "reports" / VERSION


def main():
    with patch.multiple(base, VERSION=VERSION, PLAN=PLAN, SCENARIOS=SCENARIOS, OUT=OUT):
        base.main()
        if sys.argv[1:] == ["freeze"]:
            plan = read_json(PLAN)
            for name in ["scripts/accept_support_latency_close_v1.py",
                         "docs/customer-agent-latency-close-v1.md",
                         "evals/customer-latency-close-live-v1/scenarios.json"]:
                plan["files"][name] = digest(base.ROOT / name)
            plan.update(source_commit="d1f7856ca0588670e1c3ca16ea69855ea871efe9",
                        comparison="Same three inputs/snapshots as policy-batch-live-v1, different time; not randomized paired SLA",
                        complex_first_body_target_ms=4000, browser_max_new_requests=12)
            persist(PLAN, plan)
            base.load_plan()


if __name__ == "__main__":
    main()
