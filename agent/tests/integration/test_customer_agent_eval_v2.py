"""Fixed baseline crosses the actual ASGI/store boundary, not a provider-only probe."""

import httpx
from fastapi.testclient import TestClient
from scripts import customer_agent_eval_v2 as runner
from scripts.evaluation.support_fixed_v2 import FixedSupportRuntime

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from resolveflow.support.sources import BoundSources
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import answer
from tests.unit.test_support_dialogue import event
from tests.unit.test_support_tasks import task


def test_fixed_two_turns_share_current_annotations_and_saved_result_is_reused(agent_db, tmp_path):
    case = runner.load_cases()[12]
    active = [None]
    paths, completed, models = [], [], []
    app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False,
                     migrate=False, jwt_secret=runner.SECRET)
    with TestClient(app) as api:
        for i in range(2):
            req, archive = runner.prepare_turn(case, i, completed, "fixed")
            tasks = [task("trace")] if i == 0 else [task("trace", status="SUSPENDED"), task("entry", "APPLICATION")]
            events = [event("ADD", "trace", case["turns"][i]["text"])] if i == 0 else [
                event("PAUSE", "trace", case["turns"][i]["text"]), event("ADD", "entry", case["turns"][i]["text"])]
            text = "可请商家核查。" if i == 0 else "核查稍后继续。正式申请在我的售后。"
            final_tasks = [task("trace", status="NEEDS_MERCHANT", response_excerpt="可请商家核查")]
            if i == 1:
                final_tasks = [task("trace", status="SUSPENDED", response_excerpt="核查稍后继续"),
                               task("entry", "APPLICATION", "ANSWERED", response_excerpt="正式申请在我的售后")]
            model = TokenizedScript(script=[
                {"kind": "SEARCH_POLICY", "query": "签收核查", "top_k": 3, "tasks": tasks, "dialogue_events": events},
                answer(text=text, citations=[], tasks=final_tasks)])
            active[0] = model
            models.append(model)
            with httpx.Client(transport=httpx.MockTransport(
                runner.upstream_for(case["snapshot"], req, archive, paths)
            )) as upstream:
                runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), model_factory=lambda: active[0])

                def sources(bound, token, journal):
                    return BoundSources(bound, case_url="http://frozen-case.local", token=token,
                                        journal=journal, client=upstream)

                app.state.support_runtime = FixedSupportRuntime(agent_db, runtime, sources, "isolated-test-plan")
                token = mint_service_token("case-service", runner.SECRET, scope="support:run",
                                           merchant_id=req.merchant_id, customer_id=req.customer_id)
                headers = {"Authorization": "Bearer " + token}
                body = {**req.model_dump(mode="json"), "tool_token": "synthetic-read-token"}
                response = api.post("/internal/v1/support-runs", json=body, headers=headers)
                assert response.status_code == 200
                result = response.json()
                assert result["status"] == "SUCCEEDED", result["reason"]
                completed.append(result)
                calls_before = len(paths)
                assert api.post("/internal/v1/support-runs", json=body, headers=headers).json() == result
                assert len(paths) == calls_before
    assert [m.calls for m in models] == [2, 2]
    assert models[1].packets[0]["previous_tasks"]["tasks"][0]["id"] == "trace"
    assert completed[-1]["answer"]["task_state"]["tasks"][0]["status"] == "SUSPENDED"
    with agent_db.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM support_agent_run").fetchone()["n"] == 2
