"""Explicit offline contract adaptations of saved failures, never new model scores."""

from __future__ import annotations

import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportInput

from scripts.accept_customer_final_v1 import ROOT
from scripts.customer_agent_eval_v2 import digest, read_json, write_new
from scripts.diagnose_support_boundary_v1 import SavedModel, SavedSources


def main():
    original = ROOT / "reports/customer-final-acceptance-v1/runtime-results.json"
    before = digest(original)
    rows = read_json(original)["rows"]
    output = []
    connect = socket.socket.connect

    def local_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            raise AssertionError("offline external network forbidden")
        return connect(sock, address)

    for index in (3, 4, 10):
        row = rows[index]
        req = SupportInput.model_validate({**row["input"], "deadline_at": datetime.now(UTC) + timedelta(seconds=120)})
        decisions = [deepcopy(m["decision"]) for m in row["models"]]
        if index == 3:
            # Explicit diagnostic proposal: reuse the original paused issue, retain the actual chosen reads.
            decisions = [d for d in decisions if d["kind"] != "REVIEW_GOAL"]
            decisions[0]["focus"][0]["id"] = "t1"
            decisions[0]["dialogue_events"][0].update(change="RESUME", task_ids=["t1"])
            decisions[-1]["parts"][0]["task_id"] = "t1"
        elif index == 4:
            change = decisions[0]["customer_claims"][0]
            change.pop("target")
            entries = req.context["previous_customer_memory"]["entries"]
            change["targets"] = [entries[i]["id"] for i in (0, 3, 4)]
        else:
            decisions = [decisions[0], decisions[-1]]
            decisions[-1]["handoff_reason"] = {"customer_refs": [
                req.context["previous_customer_memory"]["entries"][0]["id"], "CURRENT"]}
        model, sources = SavedModel(script=decisions, mode="live"), SavedSources(row["calls"])
        with (patch.object(socket.socket, "connect", local_only),
              patch.object(httpx.Client, "send", side_effect=AssertionError("offline HTTP forbidden"))):
            result = SupportAgent(req, model, sources, architecture="orchestrated-v1").run()
        assert result["status"] == "SUCCEEDED", result["reason"]
        if index == 3:
            assert [(t["id"], t["lifecycle"]) for t in result["answer"]["task_state"]["tasks"]
                    if t["id"] == "t1"] == [("t1", "OPEN")]
        elif index == 4:
            assert [e["quote"] for e in result["answer"]["customer_memory"]["entries"] if e["status"] == "ACTIVE"] == [
                "家里人其实还没回复我，刚才说他们没代收不准确", change["quote"]]
        else:
            assert "历史有效陈述原话" in result["answer"]["handoff_summary"]
        output.append({"id": row["id"], "turn": row["turn"], "adapted_decisions": decisions,
                       "result": result, "mock_model_calls": model.calls, "sources": sources.calls})
    assert digest(original) == before
    write_new(ROOT / "reports/customer-boundary-closeout-v1/offline-adaptations.json", {
        "mode": "OFFLINE_EXPLICIT_CONTRACT_ADAPTATIONS", "new_provider_requests": 0,
        "original_sha256": before, "original_unchanged": True, "passed": len(output),
        "limits": "程序合同和原输出装配验证；适配内容由开发者明确指定，不是真实模型新输出或通过率。", "rows": output})
    print("Three offline contract adaptations passed; zero external requests.")


if __name__ == "__main__":
    main()
