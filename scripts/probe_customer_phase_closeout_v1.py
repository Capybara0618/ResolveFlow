"""Two fixed state-contract checks within the original forty-request repair allowance."""

from __future__ import annotations

import argparse
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import accept_customer_final_v1 as base
from scripts.customer_agent_eval_v2 import digest, read_json, write_new

ROOT, CURRENT = base.ROOT, base.current
VERSION = "customer-phase-closeout-live-v1"
PLAN = ROOT / "evals" / VERSION / "manifest.json"
OUT = ROOT / "reports" / VERSION
SAVED = ROOT / "reports/customer-boundary-confirm-live-v1/runtime-results.json"
ENVELOPE_START, ENVELOPE_LIMIT = 2410, 40


def cases():
    snapshots = {c["id"]: c["snapshot"] for c in base.cases()}
    rows = read_json(SAVED)["rows"]
    selected = []
    for index in (3, 9):
        row = rows[index]
        selected.append({"id": f"P-{row['id']}-{row['turn']}", "scenario": "原实际前缀的阶段合同定点确认",
            "snapshot": snapshots[row["id"]], "turns": [{"text": row["input"]["context"]["current_request"]}],
            "saved_input": row["input"], "original_id": row["id"], "original_turn": row["turn"]})
    return selected


def prepare_turn(case, turn_index, completed):
    if turn_index != 0 or completed:
        raise ValueError("each fixed point runs once from its actual saved prefix")
    raw = deepcopy(case["saved_input"])
    raw.update(run_id=str(uuid.uuid5(uuid.NAMESPACE_URL, VERSION + raw["run_id"])),
               deadline_at=datetime.now(UTC) + timedelta(seconds=120))
    from resolveflow.support.protocol import SupportInput

    request = SupportInput.model_validate(raw)
    return request, deepcopy(request.context["history"])


def freeze():
    inherited = read_json(ROOT / "evals/customer-boundary-confirm-live-v1/manifest.json")
    names = set(inherited["files"]) | {"scripts/probe_customer_phase_closeout_v1.py",
        "agent/tests/unit/test_customer_phase_probe.py", SAVED.relative_to(ROOT).as_posix(),
        "agent/tests/unit/test_support_goal_review.py"}
    write_new(PLAN, {"version": VERSION, "architecture": "orchestrated-v1", "conversations": 2, "turns": 2,
        "source_visible_regression": True, "independent_holdout": False,
        "usage_start": 2440, "original_envelope_start": ENVELOPE_START,
        "max_new_provider_attempts": 10, "original_envelope_limit": ENVELOPE_LIMIT,
        "files": {name: digest(ROOT / name) for name in sorted(names)},
        "embedding_files": {name: digest(Path(CURRENT.MODEL_PATH) / name) for name in inherited["embedding_files"]}})


def load_plan():
    plan = read_json(PLAN)
    if (plan["turns"], plan["usage_start"], plan["max_new_provider_attempts"]) != (2, 2440, 10):
        raise ValueError("fixed point allowance changed")
    for name, expected in plan["files"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("frozen source changed: " + name)
    for name, expected in plan["embedding_files"].items():
        if digest(Path(CURRENT.MODEL_PATH) / name) != expected:
            raise ValueError("frozen embedding changed: " + name)
    return plan, cases()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "check", "execute"])
    mode = parser.parse_args().mode
    if mode == "freeze":
        freeze()
    elif mode == "check":
        _, selected = load_plan()
        write_new(OUT / "preflight.json", {"new_provider_requests": 0, "plan_sha256": digest(PLAN),
            "database": CURRENT.previous.check_database(selected, CURRENT.DSN)})
    else:
        plan, _ = load_plan()
        if read_json(base.USAGE)["used"] != plan["usage_start"]:
            raise ValueError("usage changed after preparation")
        with patch.multiple(CURRENT, VERSION=VERSION, PLAN=PLAN, load_plan=load_plan, prepare_turn=prepare_turn,
                            RecordedStreamingModel=base.capped_model_class(ENVELOPE_START)):
            CURRENT.evaluate(OUT / "runtime-results.json", base.USAGE)


if __name__ == "__main__":
    main()
