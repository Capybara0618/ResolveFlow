"""One actual UI wait-profile sample using the existing accounting and preparation path."""

import argparse
import json
from unittest.mock import patch

import accept_customer_latency_browser_v1 as base
from accept_chat_refund_live_v1 import ROOT, persist

VERSION = "customer-wait-profile-live-v1"
OUT = ROOT / "reports" / VERSION
PRIVATE = ROOT / "tmp" / VERSION
FILES = list(dict.fromkeys(base.FILES + [
    "scripts/accept_customer_wait_profile_v1.py",
    "docs/customer-wait-profile-live-v1.md",
    "agent/src/resolveflow/api/app.py",
    "agent/src/resolveflow/harness/token_counting.py",
    "agent/src/resolveflow/support/navigation.py",
    "agent/src/resolveflow/support/grounding.py",
    "agent/src/resolveflow/support/progress.py",
    "agent/src/resolveflow/support/sources.py",
    "agent/src/resolveflow/support/service.py",
    "infra/logging.agent.json",
    "scripts/reviewer_demo.py",
]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "watch"])
    args = parser.parse_args()
    with patch.multiple(base, OUT=OUT, PRIVATE=PRIVATE, FILES=FILES):
        if args.action == "prepare":
            base.prepare()
            plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
            plan.update(scope="one actual browser turn and production phase timings; no confirmation",
                        required_observations=[
                            "actual progressive visible text and final answer",
                            "UNDERSTAND/INVESTIGATE/COMPOSE timings from actual run logs",
                            "correct bound evidence; no duplicate same-source fact blocks",
                            "prepared refund draft uses card confirmation guidance",
                            "no Case, merchant handoff or refund; exact usage accounting",
                        ])
            persist(OUT / "plan.json", plan)
        else:
            base.watch()


if __name__ == "__main__":
    main()
