"""Frozen multi-turn inputs and read-only readiness checks. Does not execute a model evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from resolveflow.support.protocol import SupportInput  # noqa: E402

PLAN = ROOT / "evals/customer-agent-readiness-v1/manifest.json"
NAMESPACE = uuid.UUID("a8ab8258-5bdd-44cc-990a-6cc68891bc6a")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plan(path=PLAN):
    plan = json.loads(path.read_text(encoding="utf-8"))
    for relative, expected in plan["files"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError("frozen source changed: " + relative)
    data = json.loads((ROOT / plan["scenarios_path"]).read_text(encoding="utf-8"))
    cases = data["cases"]
    snapshots = json.loads((ROOT / plan["snapshot_path"]).read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in snapshots}
    if len(cases) != 12 or len({c["id"] for c in cases}) != 12:
        raise ValueError("expected twelve distinct conversation families")
    for case in cases:
        if case["snapshot_id"] not in by_id or len(case["turns"]) != 3:
            raise ValueError("unknown snapshot or incomplete conversation")
        for turn in case["turns"]:
            if not turn["text"].strip() or not turn["criteria"] or any(not x.strip() for x in turn["criteria"]):
                raise ValueError("turn requires semantic scoring conditions")
        case["snapshot"] = deepcopy(by_id[case["snapshot_id"]])
        # Validate binding/schema only. Gold never enters the prepared request.
        prepare_turn(case, 0, [])
    return plan, cases


def prepare_turn(case, turn_index, completed):
    """Use actual earlier results, preserving failed turns and complete originals for history pagination.

    Returned archive is for the synthetic scoped history adapter, never a second prompt containing gold.
    Agent-side last-20 history matches Java's snapshot shape. No assistant answers are fabricated here.
    """
    if not 0 <= turn_index < len(case["turns"]) or len(completed) != turn_index:
        raise ValueError("completed turns must be exactly the preceding prefix")
    history = deepcopy(case.get("seed_history", []))
    conversation = str(uuid.uuid5(NAMESPACE, case["id"]))
    previous = None
    base = deepcopy(case["snapshot"]["input_without_deadline"])
    for index in range(turn_index + 1):
        version = 1 + max((m["sequence"] for m in history), default=0)
        run = str(uuid.uuid5(NAMESPACE, f"{case['id']}:{index}"))
        turn = case["turns"][index]
        history.append({"message_id": str(uuid.uuid5(NAMESPACE, f"{case['id']}:{version}:customer")),
                        "sequence": version, "author": "CUSTOMER", "recipient": "ASSISTANT", "text": turn["text"]})
        if index == turn_index:
            context = {"product": base["context"]["product"],
                       "policy_manifest": base["context"]["policy_manifest"],
                       "current_request": turn["text"], "history": deepcopy(history[-20:]),
                       "history_before": history[-20]["sequence"] if len(history) >= 20 else None,
                       "conversation_state": turn.get("conversation_state", {
                           "has_ticket": False, "ticket_status": "NONE",
                           "current_recipient": "ASSISTANT", "default_recipient": "ASSISTANT"}),
                       "previous_tasks": previous}
            request = SupportInput.model_validate({**base, "run_id": run, "conversation_id": conversation,
                                                   "input_version": version, "context": context,
                                                   "deadline_at": datetime.now(UTC) + timedelta(seconds=120)})
            return request, history
        result = completed[index]
        if (result.get("run_id"), result.get("conversation_id"), result.get("input_version")) != (
            run, conversation, version
        ):
            raise ValueError("completed turn identity does not match this conversation prefix")
        if result["status"] == "SUCCEEDED":
            answer = result["answer"]
            if not isinstance(answer, dict) or not isinstance(answer.get("text"), str) or not answer["text"].strip():
                raise ValueError("successful completed turn requires its actual answer")
            history.append({"message_id": str(uuid.uuid5(NAMESPACE, f"{case['id']}:{version+1}:assistant")),
                            "sequence": version + 1, "author": "ASSISTANT", "recipient": "CUSTOMER",
                            "text": answer["text"]})
            state = answer.get("task_state")
            previous = {"origin": "MODEL_PREVIOUS_TURN", "input_version": version, "tasks": state["tasks"]} if (
                isinstance(state, dict) and state.get("origin") == "MODEL" and isinstance(state.get("tasks"), list)
            ) else None
        elif result["status"] != "FAILED":
            raise ValueError("unknown completed turn status")
    raise AssertionError("unreachable")


def check_database(cases, dsn):
    from resolveflow.policies.index import PolicyIndex
    from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot

    database = ReadOnlyDatabase(dsn)
    try:
        before = snapshot(database)
        index = PolicyIndex(database)
        pins = {}
        for case in cases:
            req, _ = prepare_turn(case, 0, [])
            manifest = req.context["policy_manifest"]
            if manifest["merchant_id"] != req.merchant_id:
                raise ValueError("manifest merchant mismatch")
            ready = index.require_ready(manifest["bundle_ids"], manifest["manifest_hash"])
            actual = {g.bundle_id: g.generation_id for g in ready}
            if any(g.merchant_id != req.merchant_id for g in ready) or actual != case["snapshot"]["pinned_generations"]:
                raise ValueError("policy generation or merchant mismatch")
            pins.update(actual)
        after = snapshot(database)
        if before != after:
            raise ValueError("retained public data changed")
        return {"pinned_generations": pins, "public_before": before, "public_after": after, "equal": True}
    finally:
        database.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--dsn", default="postgresql://agent:agent@127.0.0.1:55433/agent_db")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plan, cases = load_plan()
    result = {"version": plan["version"], "preflight": "PASSED", "conversations": len(cases),
              "turns": sum(len(c["turns"]) for c in cases), "new_model_calls": 0,
              "formal_evaluation_executed": False, "database_checked": args.database}
    if args.database:
        result["database"] = check_database(cases, args.dsn)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
            file.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "database"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
