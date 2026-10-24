"""The new fulfilment-policy floor survives real PG journal recovery without new calls."""

import json

import pytest

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_orchestrated_engine import Sources, respond
from tests.unit.test_support_orchestration import plan


@pytest.mark.parametrize("policy_available", [True, False])
def test_fulfilment_policy_requirement_and_result_are_persistent(agent_db, policy_available):
    req = request()
    final = respond(parts=[{"task_id": "trace", "text": "按相关条款，争议需商家核验，草稿不等于批准。",
                            "citations": ["P1"]}]) if policy_available else respond(
                                parts=[{"task_id": "trace", "text": "政策来源不可用，暂不能完整解释处理条件。"}],
                                refund_reason=None)
    script = [plan(req, needs=["SHIPMENT"]).model_dump(), read("get_order_context"), read(),
              respond(), read("search_policy", query="签收争议如何核验处理"), final]

    class PolicySource(Sources):
        def search(self, query, top_k):
            if not policy_available:
                self.calls.append(("search_policy", {"query": query, "top_k": top_k}))
                return [{"error": "POLICY_INDEX_NOT_READY", "retryable": False}]
            return super().search(query, top_k)

    sources = PolicySource()
    models = [TokenizedScript(mode="live", script=script)]
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="live", provider="deepseek", model_id="deepseek-flash"),
                             architecture="orchestrated-v1", model_factory=lambda: models[0],
                             sources_factory=lambda *_: sources)
    result = runtime.run(req, "test-bound")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert models[0].calls == 6
    statuses = [t["status"] for t in result["answer"]["task_state"]["tasks"]]
    assert statuses == (["ANSWERED"] if policy_available else ["UNAVAILABLE"])
    assert bool(result["answer"].get("refund_summary")) == policy_available
    with agent_db.connection() as c:
        row = c.execute("SELECT request_json FROM support_agent_call WHERE run_id=%s AND kind='model' "
                        "AND position=5", (req.run_id,)).fetchone()
        packet = json.loads(row["request_json"]["messages"][-1]["content"])
        assert packet["orchestration"]["tasks"][0]["missing"] == ["POLICY"]
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    old_calls = list(sources.calls)
    models[0] = TokenizedScript(mode="live", script=script)
    assert runtime.run(req, "test-recovered") == result
    assert models[0].calls == 0 and sources.calls == old_calls
