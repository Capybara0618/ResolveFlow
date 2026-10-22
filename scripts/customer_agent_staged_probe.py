"""Offline saved-response probes; no model generation, network or database access."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from resolveflow.support.dialogue import DialogueState, event_outcomes
from resolveflow.support.protocol import DECISION, SupportInput
from resolveflow.support.tasks import TaskTracker, render_answer


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe():
    raw = ROOT / "reports/customer-agent-experience-v3/runtime-results.json"
    before = fingerprint(raw)
    old = json.loads(raw.read_text(encoding="utf-8"))
    interruption = next(r for r in old["rows"] if r["id"] == "U05" and r["turn"] == 2)
    payload = deepcopy(interruption["models"][-1]["decision"])
    rendered = render_answer(DECISION.validate_python(payload), [])
    state = DialogueState(SupportInput.model_validate(interruption["input"]))
    state.apply(rendered.dialogue_events, rendered.tasks, [], require=True)
    retained = state.task_snapshot(rendered.tasks)
    assert retained["focus_ids"] == ["t2"]
    assert [(t["id"], t["lifecycle"]) for t in retained["tasks"]] == [("t1", "OPEN"), ("t2", "OPEN")]

    closure = next(r for r in old["rows"] if r["id"] == "U05" and r["turn"] == 4)
    response = render_answer(DECISION.validate_python(closure["models"][0]["decision"]), [])
    tasks = event_outcomes(response.tasks, response.dialogue_events)
    tracker = TaskTracker()
    tracker.accept(tasks, set(), answer=response, require=True)
    closed = DialogueState(SupportInput.model_validate(closure["input"]))
    closed.apply(response.dialogue_events, tracker.tasks, [], require=True)
    resolved = closed.task_snapshot(tracker.tasks)
    assert resolved["tasks"][0]["lifecycle"] == "RESOLVED"
    assert resolved["tasks"][0]["status"] == "ANSWERED"

    mixed = next(r for r in old["rows"] if r["id"] == "U02")
    read = DECISION.validate_python(mixed["models"][1]["decision"])
    assert read.kind == "READ_TOOL" and read.tool_name == "get_shipment_trace" and read.arguments == {}
    assert fingerprint(raw) == before
    return {
        "version": "customer-agent-staged-v1-offline-probes", "generation": "NONE",
        "runtime_sha256": before, "old_raw_unchanged": True,
        "interpretation": "Local parsing/state probes only; not new model outputs or business writes.",
        "retained_after_saved_interruption": retained,
        "interruption_limit": "Original output did not propose PAUSE, so old issue remains OPEN, not PAUSED.",
        "derived_after_saved_closure": resolved,
        "read_executable_fields": {"tool_name": read.tool_name, "arguments": read.arguments},
        "purpose_is_execution_parameter": False,
        "source_sha256": {p: fingerprint(ROOT / p) for p in [
            "agent/src/resolveflow/support/engine.py", "agent/src/resolveflow/support/dialogue.py",
            "agent/src/resolveflow/support/protocol.py", "agent/src/resolveflow/support/stages.py",
            "agent/src/resolveflow/support/service.py", "scripts/customer_agent_staged_probe.py"]},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = probe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print({"old_raw_unchanged": True, "new_model_calls": 0, "probes_passed": 3})


if __name__ == "__main__":
    main()
