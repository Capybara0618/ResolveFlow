"""Goal review is reconstructed from the original fenced call journal with no new transmissions."""

import json

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_goal_review import review
from tests.unit.test_support_orchestrated_engine import Sources
from tests.unit.test_support_orchestration import plan


def test_goal_review_and_task_intent_survive_real_pg_recovery_without_resetting_spend(agent_db):
    req = request()
    req.context["current_request"] = "请准备给商家的核查摘要，先不发送。"
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "核查摘要待本人确认。",
                                          "citations": ["O1"]}], "handoff_reason": "客户请求核查，尚未转交。"}
    script = [plan(req).model_dump(), read("get_order_context"), final,
              review(quote=req.context["current_request"]), final]
    models, sources = [TokenizedScript(script=script, mode="live")], Sources()
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), architecture="orchestrated-v1",
                             model_factory=lambda: models[0], sources_factory=lambda *_: sources)
    result = runtime.run(req, "test-bound")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["answer"]["task_state"]["tasks"][0]["intent"] == "HANDOFF"
    assert len(result["answer"]["dialogue_state"]["events"]) == 1
    assert result["spend"]["model_calls"] == 5 and result["spend"]["tool_attempts"] == 1
    assert "refund_summary" not in result["answer"]
    with agent_db.connection() as c:
        calls = c.execute("SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY kind,position",
                          (req.run_id,)).fetchall()
        fourth = next(r for r in calls if r["kind"] == "model" and r["position"] == 4)
        packet = json.loads(fourth["request_json"]["messages"][-1]["content"])
        assert packet["orchestration"]["phase"] == "INVESTIGATE"
        assert packet["orchestration"]["goal_review"]["accepted_goals"] == {"trace": "PREPARE_REFUND"}
        assert len(calls) == 7
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    models[0] = TokenizedScript(script=script, mode="live")
    before = list(sources.calls)
    assert runtime.run(req, "new-test-bound") == result
    assert models[0].calls == 0 and sources.calls == before
