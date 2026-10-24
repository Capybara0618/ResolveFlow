"""Saved primary actions stay failed; compare complete rejection metadata without new network calls."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src"), str(ROOT / "agent")]

from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportInput
from tests.integration.test_support_dialogue_api import TokenizedScript

RAW = ROOT / "reports/customer-agent-acceptance-gate-v1/primary/runtime-results.json"
OUT = ROOT / "reports/customer-agent-acceptance-gate-v1/diagnostic.json"


def diagnose():
    digest = hashlib.sha256(RAW.read_bytes()).hexdigest()
    run = json.loads(RAW.read_text(encoding="utf-8"))["support_runs"][0]
    req = SupportInput.model_validate({**run["input_json"],
        "deadline_at": dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)})
    models = [c for c in run["calls"] if c["kind"] == "model"]
    tools = [c for c in run["calls"] if c["kind"] == "tool"]

    class Saved:
        position = 0

        def read(self, name, arguments):
            call = tools[self.position]
            self.position += 1
            assert call["request_json"] == {"name": name, "arguments": arguments}
            return call["response_json"][0]

    saved = Saved()
    model = TokenizedScript(mode="live", script=[c["response_json"]["decision"] for c in models])
    agent = SupportAgent(req, model, saved, architecture="staged-v1")
    result = agent.run()
    assert result["reason"] == "INVALID_DECISION" and result["answer"] is None
    assert model.calls == len(models) == 4 and saved.position == len(tools) == 1 and agent.repairs == 1
    old = json.loads(json.loads(models[3]["request_json"]["messages"][-1]["content"])["feedback"])
    new = json.loads(model.packets[3]["feedback"])
    assert old["field"] == "citations" and new["field"] == "refund_summary"
    assert {g["need"] for g in new["source_gaps"]} == {"ORDER", "GUIDE"}
    assert new["action_gaps"] == [{"task_id": "t2", "action": "REFUND_APPLICATION"}]
    assert hashlib.sha256(RAW.read_bytes()).hexdigest() == digest
    return {"diagnostic_only": True, "strict_replay": False, "deadline_refreshed_for_offline_execution": True,
        "raw_sha256": digest, "new_provider_calls": 0, "business_writes": 0,
        "old_feedback": old, "new_feedback": new, "saved_model_actions": model.calls,
        "saved_tool_results": saved.position, "repairs": agent.repairs,
        "original_actions_still_failed": True, "published_answer": None,
        "real_model_acceptance_of_new_feedback": "NOT_TESTED"}


if __name__ == "__main__":
    value = diagnose()
    assert not OUT.exists(), "Never overwrite a diagnosis"
    OUT.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print({"old_actions_still_failed": True, "complete_gaps": ["ORDER", "GUIDE", "REFUND_APPLICATION"],
           "new_provider_calls": 0})
