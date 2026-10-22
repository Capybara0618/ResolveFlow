"""Reproduce the saved six-turn failures offline; never runs models or business adapters."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from pydantic import ValidationError
from resolveflow.support.dialogue import DialogueState, DialogueStateError
from resolveflow.support.memory import customer_source
from resolveflow.support.protocol import DECISION, MemoryUpdate, SupportInput
from resolveflow.support.tasks import render_answer

from scripts import customer_agent_experience_v3 as runner


def diagnose():
    runner.load_plan()  # Same source/weights as the live cohort, never rewrite an old manifest.
    raw = ROOT / "reports/customer-agent-experience-v3/runtime-results.json"
    before = runner.prior.digest(raw)
    report = runner.prior.read_json(raw)
    assert report["state"] == "FINISHED" and len(report["rows"]) == 6
    rows = {(r["id"], r["turn"]): r for r in report["rows"]}
    invalid = []
    for row in report["rows"]:
        for position, record in enumerate(row["models"], 1):
            try:
                DECISION.validate_python(record["decision"])
            except ValidationError as error:
                invalid.append({"id": row["id"], "turn": row["turn"], "model": position,
                                "errors": [{"path": list(e["loc"]), "type": e["type"]} for e in error.errors()]})
    assert len(invalid) == 3

    pause = rows[("U05", 2)]
    state = DialogueState(SupportInput.model_validate(pause["input"]))
    carried_before = state.packet()
    decision = render_answer(DECISION.validate_python(pause["models"][-1]["decision"]), [])
    state.apply(decision.dialogue_events, decision.tasks, [], require=True)
    carried_after = state.packet()
    assert carried_before["lifecycles"] == {"t1": "OPEN"}
    assert "t1" not in carried_after["lifecycles"] and carried_after["lifecycles"] == {"t2": "OPEN"}

    resume = rows[("U05", 3)]
    req = SupportInput.model_validate(resume["input"])
    update = MemoryUpdate.model_validate(resume["models"][0]["decision"]["memory_updates"][0])
    located = customer_source(update, req, [])
    assert located["offset"] == 15
    assert resume["tools"] == [] and resume["result"]["answer"]["citations"] == []

    closure = rows[("U05", 4)]

    def closure_probe(payload):
        parsed = render_answer(DECISION.validate_python(payload), [])
        state = DialogueState(SupportInput.model_validate(closure["input"]))
        try:
            state.apply(parsed.dialogue_events, parsed.tasks, [], require=True)
        except DialogueStateError as error:
            return {"accepted": False, "error": str(error)}
        return {"accepted": True, "lifecycles": state.lifecycles}

    original = deepcopy(closure["models"][0]["decision"])
    rejected = closure_probe(original)
    cancel = deepcopy(original)
    cancel["dialogue_events"][0]["change"] = "CANCEL"
    matched_cancel = closure_probe(cancel)
    resolved = deepcopy(original)
    resolved["tasks"][0]["status"] = resolved["parts"][0]["status"] = "ANSWERED"
    matched_resolve = closure_probe(resolved)
    assert not rejected["accepted"] and matched_cancel["accepted"] and matched_resolve["accepted"]
    assert runner.prior.digest(raw) == before
    return {
        "version": "customer-agent-experience-v3-diagnosis",
        "runtime_sha256": before, "diagnoser_sha256": runner.prior.digest(Path(__file__)),
        "new_model_calls": 0, "raw_unchanged": True,
        "schema_invalid": invalid,
        "open_issue_omission": {"before": carried_before, "after": carried_after,
                                "reason": "ANSWERED is exempt from required carry-over; omission removes OPEN topic"},
        "unique_quote_location": located,
        "resume_without_fresh_sources": {"tools": [], "citations": [], "previous_task_ids": [
            t["id"] for t in resume["input"]["context"]["previous_tasks"]["tasks"]],
            "new_task_ids": [t["id"] for t in resume["result"]["answer"]["task_state"]["tasks"]],
            "wrong_route_excerpt": "可在「我的售后」页面选择该订单商品后点「请商家核查」"},
        "closure": {"original_resolve_cancelled": rejected,
                    "hypothetical_event_cancel": matched_cancel, "hypothetical_outcome_answered": matched_resolve,
                    "probe_limit": "local DialogueState only; copies are not live results or accepted business writes"},
        "rag_searches": sum(t.get("name") == "search_policy" for r in report["rows"] for t in r["tools"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = diagnose()
    runner.prior.write_new(args.output, result)
    print({"schema_invalid": len(result["schema_invalid"]), "new_model_calls": 0, "raw_unchanged": True})


if __name__ == "__main__":
    main()
