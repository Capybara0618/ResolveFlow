"""Offline source/state probes of saved real decisions; no generation, HTTP or database access."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from pydantic import ValidationError
from resolveflow.support.completion import CompletionError, check_completion
from resolveflow.support.dialogue import (
    DialogueState,
    DialogueStateError,
    event_outcomes,
)
from resolveflow.support.grounding import ground_answer
from resolveflow.support.memory import CustomerMemory
from resolveflow.support.protocol import DECISION, AnswerParts, SupportInput
from resolveflow.support.stages import RefineNeeds, Understanding
from resolveflow.support.tasks import TaskTracker, render_answer

from scripts import customer_agent_state_live_v1 as runner


def citations_for(row):
    counters = {"O": 0, "P": 0}
    result = {}
    for tool in row["tools"]:
        sources = tool["result"] if isinstance(tool["result"], list) else [tool["result"]]
        for source in sources:
            if "error" in source:
                continue
            prefix = "P" if source["source_type"] == "POLICY" else "O"
            counters[prefix] += 1
            result[prefix + str(counters[prefix])] = deepcopy(source)
    return result


def diagnose():
    runner.load_plan()
    path = ROOT / "reports/customer-agent-state-live-v1/runtime-results.json"
    fingerprint = runner.prior.digest(path)
    raw = runner.prior.read_json(path)
    assert raw["state"] == "FINISHED" and len(raw["rows"]) == 14
    rows = {(r["id"], r["turn"]): r for r in raw["rows"]}
    invalid = []
    total = 0
    for row in raw["rows"]:
        for index, model in enumerate(row["models"], 1):
            total += 1
            payload = model["decision"]
            try:
                if payload.get("kind") == "TURN_UNDERSTANDING":
                    Understanding.model_validate(payload)
                elif payload.get("kind") == "REFINE_NEEDS":
                    RefineNeeds.model_validate(payload)
                else:
                    DECISION.validate_python(payload)
            except ValidationError as error:
                invalid.append({"id": row["id"], "turn": row["turn"], "model": index,
                    "errors": [{"path": list(e["loc"]), "type": e["type"]} for e in error.errors()]})
    assert total == 48 and len(invalid) == 1

    closure = rows[("U05:single", 4)]
    req = SupportInput.model_validate(closure["input"])
    decision = render_answer(DECISION.validate_python(closure["models"][0]["decision"]), [])
    state = DialogueState(req)
    try:
        state.apply(decision.dialogue_events, decision.tasks, [], require=True)
    except DialogueStateError as error:
        missing = error.missing_task_ids
    else:
        raise AssertionError("Missing old FAQ event unexpectedly accepted")
    assert missing == ["t2"]
    # Local hypothetical copy only, not a new actual model result or repaired live success.
    local = deepcopy(closure["models"][0]["decision"])
    local["tasks"] = [t for t in local["tasks"] if t["id"] == "t1"]
    local["parts"] = [p for p in local["parts"] if p["task_id"] == "t1"]
    parsed = render_answer(DECISION.validate_python(local), [])
    hypothetical = DialogueState(req)
    hypothetical.apply(parsed.dialogue_events, parsed.tasks, [], require=True)
    assert hypothetical.lifecycles["t1"] == "RESOLVED" and "t2" in hypothetical.issues

    mixed = rows[("U02:single", 1)]
    req = SupportInput.model_validate(mixed["input"])
    answer = render_answer(DECISION.validate_python(mixed["models"][-1]["decision"]), [])
    refs = citations_for(mixed)
    tracker = TaskTracker()
    tracker.accept(event_outcomes(answer.tasks, answer.dialogue_events), set(refs), answer=answer, require=True)
    state = DialogueState(req)
    state.apply(answer.dialogue_events, tracker.tasks, [], require=True)
    try:
        check_completion(answer, tracker.tasks, refs, [], state.lifecycles)
    except CompletionError as error:
        gaps = error.gaps
    else:
        raise AssertionError("Missing policy unexpectedly accepted")
    assert gaps == [{"task_id": "t2", "code": "SOURCE_REQUIRED", "tool_name": "search_policy"}]

    resume = rows[("U05:single", 3)]
    req = SupportInput.model_validate(resume["input"])
    memory = CustomerMemory(req)
    for record in resume["models"][1:]:
        memory.propose(record["decision"].get("customer_claims", []), [])
    assert memory.snapshot() == resume["result"]["answer"]["customer_memory"]
    active = [e for e in memory.entries if e["status"] == "ACTIVE"]
    assert len(active) == 2 and active[0]["quote"] == active[1]["quote"]

    money = rows[("U06:staged-v1", 1)]
    parsed = AnswerParts.model_validate(money["models"][-1]["decision"])
    rendered = ground_answer(parsed, SupportInput.model_validate(money["input"]), citations_for(money))
    assert "\n\n".join(p.text for p in rendered.parts) == money["result"]["answer"]["text"]
    four = [rows[("U05:staged-v1", i)]["result"]["answer"] for i in range(1, 5)]
    assert [a["task_state"]["tasks"][0]["lifecycle"] for a in four] == ["OPEN", "PAUSED", "OPEN", "RESOLVED"]
    assert four[2]["customer_memory"]["entries"][0]["source"]["offset"] == 15
    assert runner.prior.digest(path) == fingerprint
    return {"version": "customer-agent-state-live-v1-diagnosis", "new_model_calls": 0,
        "runtime_sha256": fingerprint, "raw_unchanged": True, "schema_valid": total - len(invalid),
        "schema_total": total, "schema_invalid": invalid, "single_closure_missing_event": missing,
        "hypothetical_copy_only_focus_t1": {"lifecycles": hypothetical.lifecycles,
            "not_actual_success": True}, "single_mixed_actual_missing_policy": gaps,
        "single_resume_duplicate_active_claims": [{"id": e["id"], "quote": e["quote"],
            "supersedes": e["supersedes"]} for e in active],
        "staged_actual_four_turn_lifecycle": [a["task_state"]["tasks"][0]["lifecycle"] for a in four],
        "staged_actual_correction_offset": 15, "staged_actual_paid_amount_render_reproduced": True,
        "live_failed_accepted_state_inheritance_exercised": False,
        "reason": "The two failed single turns had no accepted update and no following in-scope turn; staged had no failures."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = diagnose()
    runner.prior.write_new(args.output, result)
    print({"schema_valid": result["schema_valid"], "schema_total": result["schema_total"],
           "new_model_calls": 0, "raw_unchanged": True})


if __name__ == "__main__":
    main()
