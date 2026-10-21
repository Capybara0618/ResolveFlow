"""Four scoped ASGI/SDK/PG turns with correction, interruption, resume and cancellation; scripted model."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.harness.model import MockModelClient
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from resolveflow.support.sources import BoundSources
from tests.unit.test_support_agent import answer, read, request
from tests.unit.test_support_context import message
from tests.unit.test_support_dialogue import event
from tests.unit.test_support_memory import memory
from tests.unit.test_support_tasks import task

SECRET = "support-dialogue-test-only-secret"


class TokenizedScript(MockModelClient):
    provider = "deepseek"
    model_id = "deepseek-flash"


def test_four_real_runtime_turns_and_saved_decisions_reconstruct_identical_memory(agent_db, tmp_path):
    texts = ["签收没收到，家人可能代收了", "先问退款入口，签收核查稍后继续",
             "继续签收核查，纠正：家人没代收", "找到包裹了，不用核查"]
    scripts = [
        [{**read(), "tasks": [task("trace")], "dialogue_events": [event("ADD", "trace", texts[0])],
          "memory_updates": [memory("initial", texts[0])]},
         answer(citations=["O1"], tasks=[task("trace", status="NEEDS_MERCHANT", evidence_refs=["O1"],
                                                response_excerpt="可以请商家核验")])],
        [{**read("get_support_guide"), "tasks": [task("trace", status="SUSPENDED"), task("entry", "APPLICATION")],
          "dialogue_events": [event("PAUSE", "trace", texts[1]), event("ADD", "entry", texts[1])]},
         answer(text="签收核查稍后继续。正式申请请到我的售后。", citations=["O1"], tasks=[
             task("trace", status="SUSPENDED", response_excerpt="签收核查稍后继续"),
             task("entry", "APPLICATION", "ANSWERED", evidence_refs=["O1"], response_excerpt="正式申请请到我的售后")])],
        [{**read(), "tasks": [task("trace")], "dialogue_events": [event("RESUME", "trace", texts[2])],
          "memory_updates": [memory("corrected", texts[2], supersedes=["initial"])]},
         answer(text="已记录家人未代收，仍须商家核验签收。", citations=["O1"], tasks=[
             task("trace", status="NEEDS_MERCHANT", evidence_refs=["O1"], response_excerpt="仍须商家核验签收")])],
        [answer(text="已记录找到包裹，不再核查。", citations=[], tasks=[task("trace", status="CANCELLED")],
                dialogue_events=[event("CANCEL", "trace", texts[3])],
                memory_updates=[memory("found", texts[3], supersedes=["corrected"])])],
    ]
    active, bound, paths = [None], [None], []

    def transport(call):
        paths.append(call.url.path)
        req = bound[0]
        assert req.run_id in call.url.path
        if call.url.path.endswith("/current"):
            return httpx.Response(200, json={
                "conversation_id": req.conversation_id, "input_version": req.input_version,
            })
        assert call.url.path.endswith("/facts/shipment")
        return httpx.Response(200, json={"version": 3, "status": "DELIVERED", "synthetic": True})

    history, results, models, previous = [], [], [], None
    with httpx.Client(transport=httpx.MockTransport(transport)) as upstream:
        runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), model_factory=lambda: active[0],
                                 sources_factory=lambda req, token, journal: BoundSources(
                                     req, case_url="http://case.local", token=token, journal=journal, client=upstream))
        app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False,
                         migrate=False, jwt_secret=SECRET, support_runtime=runtime)
        with TestClient(app) as api:
            for index, script in enumerate(scripts):
                version = 1 + max((m["sequence"] for m in history), default=0)
                req = request(run_id=str(uuid.uuid4()), input_version=version)
                history.append(message(version, texts[index]))
                req.context.update(current_request=texts[index], history=list(history))
                if previous:
                    req.context.update(previous_tasks={"origin": "MODEL_PREVIOUS_TURN",
                                       "input_version": previous["input_version"],
                                       "tasks": previous["answer"]["task_state"]["tasks"]},
                                       previous_customer_memory=previous["answer"]["customer_memory"])
                active[0] = TokenizedScript(script=script)
                bound[0] = req
                models.append(active[0])
                token = mint_service_token("case-service", SECRET, scope="support:run",
                                           merchant_id=req.merchant_id, customer_id=req.customer_id)
                headers = {"Authorization": "Bearer " + token}
                body = {**req.model_dump(mode="json"), "tool_token": "bound-synthetic-read-token"}
                result = api.post("/internal/v1/support-runs", json=body, headers=headers)
                assert result.status_code == 200
                previous = result.json()
                assert previous["status"] == "SUCCEEDED", previous["reason"]
                results.append(previous)
                history.append(message(version + 1, previous["answer"]["text"], "ASSISTANT"))
                assert api.post("/internal/v1/support-runs", json=body, headers=headers).json() == previous
            # Simulate process loss after saved calls, before finish: exact same manifest/input must replay.
            with agent_db.connection() as c:
                c.execute("UPDATE support_agent_run SET result_json=NULL,status='RUNNING',"
                          "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
            before_paths = list(paths)
            active[0] = TokenizedScript(script=scripts[-1])  # exact frozen mock manifest, not a different script
            replayed = api.post("/internal/v1/support-runs", json=body, headers=headers)
            assert replayed.json() == previous and active[0].calls == 0 and paths == before_paths
    assert [m.calls for m in models] == [2, 2, 2, 1]
    assert models[1].packets[0]["customer_memory"]["active"][0]["id"] == "initial"
    assert results[1]["answer"]["task_state"]["tasks"][0]["status"] == "SUSPENDED"
    assert results[2]["answer"]["customer_memory"]["entries"][0]["status"] == "SUPERSEDED"
    assert results[-1]["answer"]["task_state"]["tasks"][0]["status"] == "CANCELLED"
    active_ids = [e["id"] for e in results[-1]["answer"]["customer_memory"]["entries"] if e["status"] == "ACTIVE"]
    assert active_ids == ["found"]


def test_previous_frozen_readiness_manifest_is_not_silently_rewritten():
    from scripts.customer_agent_readiness import load_plan

    with pytest.raises(ValueError, match="frozen source changed"):
        load_plan()
