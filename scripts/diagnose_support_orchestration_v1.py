"""Explicit protocol transformation of frozen failures; not strict replay or an LLM score."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "agent/src")]

from resolveflow.support.guide import guide_source
from resolveflow.support.orchestration import Orchestration, TurnPlan
from resolveflow.support.protocol import SupportInput

FROZEN = {
    "reports/customer-agent-acceptance-gate-v1/primary/runtime-results.json":
        "94d76f7489266803f8d4b89c5e91eaddf1c5f165b4a5e8c3eeb4e8e4da795014",
    "reports/customer-answer-fact-fields-v1/live-v1/runtime-results.json":
        "dc386a70ea4af6942e7384d7205b70121d360dda832ca6388d88f41ec8fe0e3c",
    "reports/chat-refund-handoff-v1/live-v2/runtime-results.json":
        "0ad1e89dd5e49a541cf00e6eb97ac7b4e3969100a79479f397bfbfaae0007f99",
}


def diagnose():
    rows = []
    for name, digest in FROZEN.items():
        raw = (ROOT / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        run = json.loads(raw)["support_runs"][0]
        models = sorted((c for c in run["calls"] if c["kind"] == "model"), key=lambda c: c["position"])
        opening = deepcopy(models[0]["response_json"]["decision"])
        for focus in opening["focus"]:
            focus["goal"] = "PREPARE_REFUND" if focus["intent"] == "APPLICATION" else "EXPLAIN"
        req = SupportInput.model_validate({**run["input_json"],
            "deadline_at": dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)})
        plan = TurnPlan.model_validate(opening)
        flow = Orchestration(req)
        flow.accept(plan)
        # Program-owned current guide is an explicit new-protocol input, not an old saved model read.
        refs = {"O1": guide_source()}
        row = {"raw": name, "raw_status": run["status"], "source_ids_remapped": True,
               "added_goal": True, "current_program_guide_added": True, "snapshots": []}
        tool_calls = sorted((c for c in run["calls"] if c["kind"] == "tool"), key=lambda c: c["position"])
        for call in tool_calls:
            if call["request_json"]["name"] == "get_support_guide":
                continue
            for source in call["response_json"]:
                if "error" in source:
                    raise AssertionError("These three frozen trajectories contain successful saved reads")
                prefix = "P" if source["source_type"] == "POLICY" else "O"
                ref = prefix + str(1 + sum(key.startswith(prefix) for key in refs))
                refs[ref] = source
            state = flow.snapshot(plan.meaning(), refs, [], {})
            row["snapshots"].append({"after_saved_tool": call["request_json"]["name"], **state})
        state = flow.snapshot(plan.meaning(), refs, [], {})
        row["new_readiness"] = state["phase"]
        row["remaining_missing"] = {task["task_id"]: task["missing"] for task in state["tasks"]}
        if state["phase"] == "INVESTIGATE":
            flow.defer(state)
            row["premature_finish"] = "CONTINUE_WITH_GAPS_WITHOUT_FORMAT_REPAIR"
            assert any("ORDER" in task["missing"] for task in state["tasks"])
        else:
            row["premature_finish"] = "EVIDENCE_READY_FOR_NEW_COMPOSITION_NOT_OLD_TEXT_ACCEPTANCE"
        rows.append(row)
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    return {"diagnostic_only": True, "strict_replay": False, "new_provider_calls": 0,
            "business_writes": 0, "not_generation_or_quality_proof": True,
            "raw_sha256": FROZEN, "rows": rows}


if __name__ == "__main__":
    path = ROOT / "reports/customer-agent-orchestration-v1/offline-readiness.json"
    value = diagnose()
    if path.exists():
        assert json.loads(path.read_text(encoding="utf-8")) == value
    else:
        path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
    print({"frozen_failures": len(value["rows"]), "new_provider_calls": 0,
           "phases": [row["new_readiness"] for row in value["rows"]]})
