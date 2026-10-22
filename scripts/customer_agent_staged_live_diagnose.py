"""Inspect frozen comparison responses locally; no generation or database access."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from pydantic import ValidationError
from resolveflow.support.dialogue import DialogueState, DialogueStateError
from resolveflow.support.memory import CustomerMemory, MemoryStateError
from resolveflow.support.protocol import DECISION, SupportInput
from resolveflow.support.stages import Understanding
from resolveflow.support.tasks import render_answer

from scripts import customer_agent_staged_live_v1 as runner


def diagnose():
    runner.load_plan()
    path = ROOT / "reports/customer-agent-staged-live-v1/runtime-results.json"
    fingerprint = runner.prior.digest(path)
    raw = runner.prior.read_json(path)
    assert raw["state"] == "FINISHED" and len(raw["rows"]) == 12
    rows = {(r["id"], r["turn"]): r for r in raw["rows"]}
    invalid = []
    count = 0
    for row in raw["rows"]:
        for index, model in enumerate(row["models"], 1):
            count += 1
            payload = model["decision"]
            try:
                if payload.get("kind") == "TURN_UNDERSTANDING":
                    Understanding.model_validate(payload)
                else:
                    DECISION.validate_python(payload)
            except ValidationError as error:
                invalid.append({"id": row["id"], "turn": row["turn"], "model": index,
                                "errors": [{"path": list(e["loc"]), "type": e["type"]}
                                           for e in error.errors()]})
    assert count == 38 and len(invalid) == 3

    pause = rows[("U05:single", 2)]
    request = SupportInput.model_validate(pause["input"])
    parsed = render_answer(DECISION.validate_python(pause["models"][1]["decision"]), [])
    state = DialogueState(request)
    try:
        state.apply(parsed.dialogue_events, parsed.tasks, [], require=True)
    except DialogueStateError as error:
        pause_error = {"detail": str(error), "missing_task_ids": error.missing_task_ids}
    else:
        raise AssertionError("Saved interruption unexpectedly accepted")
    assert pause_error["missing_task_ids"] == ["t1"]

    resume = rows[("U05:single", 3)]
    request = SupportInput.model_validate(resume["input"])
    state = DialogueState(request)
    assert state.lifecycles == {"t1": "OPEN"}
    parsed = render_answer(DECISION.validate_python(resume["models"][0]["decision"]), [])
    try:
        state.apply(parsed.dialogue_events, parsed.tasks, [], require=True)
    except DialogueStateError as error:
        resume_error = str(error)
    else:
        raise AssertionError("RESUME from OPEN unexpectedly accepted")

    staged = rows[("U05:staged-v1", 3)]
    request = SupportInput.model_validate(staged["input"])
    understanding = Understanding.model_validate(staged["models"][1]["decision"])
    state = DialogueState(request)
    state.apply(understanding.dialogue_events, understanding.tasks(), [], require=True)
    assert state.lifecycles["t1"] == "OPEN"  # Correct RESUME independent of failed memory transaction.
    memory = CustomerMemory(request)
    assert memory.entries == []
    try:
        memory.apply(understanding.memory_updates, [])
    except MemoryStateError as error:
        memory_error = str(error)
    else:
        raise AssertionError("Unknown prior claim unexpectedly accepted")
    assert memory.entries == []

    # Hypothetical local copy only: no actual model response, API result or raw is modified.
    local = deepcopy(staged["models"][1]["decision"])
    local["memory_updates"][0]["supersedes"] = []
    hypothetical = Understanding.model_validate(local)
    memory.apply(hypothetical.memory_updates, [])
    assert len(memory.entries) == 1 and memory.entries[0]["source"]["offset"] == 15

    closure = rows[("U05:staged-v1", 4)]
    stale = deepcopy(closure["models"][0]["decision"])
    # Remove the earlier type error in a local copy to expose the stale CURRENT quotation.
    stale["memory_updates"][0]["supersedes"] = []
    stale = Understanding.model_validate(stale)
    state = DialogueState(SupportInput.model_validate(closure["input"]))
    try:
        state.apply(stale.dialogue_events, stale.tasks(), [], require=True)
    except DialogueStateError as error:
        stale_error = str(error)
    else:
        raise AssertionError("Prior-turn quotation unexpectedly accepted as CURRENT")
    assert "quote" in stale_error
    assert closure["result"]["status"] == "SUCCEEDED"
    assert runner.prior.digest(path) == fingerprint
    return {"version": "customer-agent-staged-live-v1-diagnosis", "new_model_calls": 0,
            "runtime_sha256": fingerprint, "raw_unchanged": True,
            "schema_valid": count - len(invalid), "schema_total": count, "schema_invalid": invalid,
            "single_pause": pause_error, "single_resume_from_open": resume_error,
            "staged_resume_event_independently_valid": True,
            "staged_actual_previous_claims": [], "staged_memory": memory_error,
            "hypothetical_copy_only_append_claim": memory.snapshot(),
            "hypothetical_copy_is_not_real_success": True,
            "stale_initial_understanding_rejected_locally": stale_error,
            "stale_initial_understanding_repaired_in_actual_run": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = diagnose()
    runner.prior.write_new(args.output, result)
    print({"schema_valid": result["schema_valid"], "schema_total": result["schema_total"],
           "new_model_calls": 0, "raw_unchanged": True, "local_root_cause_checks": 5})


if __name__ == "__main__":
    main()
