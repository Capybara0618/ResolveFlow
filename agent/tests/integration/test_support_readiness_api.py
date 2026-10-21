"""Three actual API/runtime/SDK/PG turns; scripted outputs, no model provider or business database writes."""

import httpx
from fastapi.testclient import TestClient
from scripts.customer_agent_readiness import load_plan, prepare_turn

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.harness.model import MockModelClient
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from resolveflow.support.sources import BoundSources
from tests.unit.test_support_agent import read
from tests.unit.test_support_tasks import task

SECRET = "support-readiness-test-only-secret"


class TokenizedScript(MockModelClient):
    # Exercise the actual pinned production tokenizer; generation is still explicitly mock.
    provider = "deepseek"
    model_id = "deepseek-flash"


def test_three_turn_correction_preserves_exact_archive_and_new_run_citations(agent_db, tmp_path):
    _, cases = load_plan()
    case = next(c for c in cases if c["id"] == "D09")
    originals = {m["sequence"]: m for m in case["seed_history"]}
    raw = originals[6]["text"]
    scripts = [
        [{**read("read_history", before_sequence=10, limit=5), "tasks": [task("trace")]},
         read("read_context", reference="H6", offset=len(raw)-30, limit=30),
         {"kind": "ANSWER", "text": "摘要：客户未收到且家人未代收，需商家核查。", "citations": ["O2"],
          "tasks": [task("trace", status="NEEDS_MERCHANT", evidence_refs=["O2"], response_excerpt="需商家核查")]}],
        [{"kind": "ANSWER", "text": "已记录你找到包裹的纠正，不再推进退款或签收核查。", "citations": [],
          "tasks": [task("close", "OTHER", "ANSWERED", response_excerpt="不再推进退款或签收核查")]}],
        [read("get_support_guide"),
         {"kind": "ANSWER", "text": "每个订单行独立保存咨询，切换商品后原记录保留。", "citations": ["O1"],
          "tasks": [task("history", "APPLICATION", "ANSWERED", evidence_refs=["O1"],
                         response_excerpt="切换商品后原记录保留")]}],
    ]
    requests, archives, models = {}, {}, []
    active = [None]

    def transport(call):
        run_id = call.url.path.split("/")[5]
        req = requests[run_id]
        if call.url.path.endswith("/current"):
            return httpx.Response(200, json={
                "conversation_id": req.conversation_id, "input_version": req.input_version,
            })
        assert call.url.path.endswith("/facts/history")
        before = int(call.url.params.get("before_sequence", str(req.input_version + 1)))
        limit = int(call.url.params.get("limit", "5"))
        messages = [m for m in archives[run_id] if m["sequence"] < before][-limit:]
        return httpx.Response(200, json={"version": req.input_version, "messages": messages})

    with httpx.Client(transport=httpx.MockTransport(transport)) as upstream:
        runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), model_factory=lambda: active[0],
                                 sources_factory=lambda bound, token, journal: BoundSources(
                                     bound, case_url="http://case.local", token=token,
                                     journal=journal, client=upstream))
        app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False,
                         migrate=False, jwt_secret=SECRET, support_runtime=runtime)
        completed = []
        with TestClient(app) as api:
            for index, script in enumerate(scripts):
                req, archive = prepare_turn(case, index, completed)
                requests[req.run_id], archives[req.run_id] = req, archive
                model = TokenizedScript(script=script)
                active[0] = model
                models.append(model)
                token = mint_service_token("case-service", SECRET, scope="support:run",
                                           merchant_id=req.merchant_id, customer_id=req.customer_id)
                headers = {"Authorization": "Bearer " + token}
                body = {**req.model_dump(mode="json"), "tool_token": "bound-synthetic-test-token"}
                response = api.post("/internal/v1/support-runs", json=body, headers=headers)
                assert response.status_code == 200
                result = response.json()
                assert result["status"] == "SUCCEEDED", result["reason"]
                completed.append(result)
                assert api.post("/internal/v1/support-runs", json=body, headers=headers).json() == result
    assert [m.calls for m in models] == [3, 1, 2]
    assert models[1].packets[0]["previous_tasks"]["needs_recheck"] is True
    assert "家人并没有代收" in completed[0]["answer"]["citations"][0]["data"]["text"]
    assert completed[1]["answer"]["citations"] == []
    assert completed[2]["answer"]["citations"][0]["source_type"] == "KNOWLEDGE"
    with agent_db.connection() as c:
        rows = c.execute("SELECT manifest_json,status FROM support_agent_run").fetchall()
    assert len(rows) == 3 and all(r["status"] == "SUCCEEDED" for r in rows)
    assert all({"context.py", "tasks.py"} <= set(r["manifest_json"]["code"]) for r in rows)
