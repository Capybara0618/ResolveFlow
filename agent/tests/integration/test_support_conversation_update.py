"""Accepted conversation meaning survives a failed answer and fenced zero-call recovery."""

import uuid

import pytest

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import Reads, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_staged import understand


def test_failed_reply_exports_accepted_pause_and_next_turn_can_resume(agent_db):
    req = request(input_version=3, run_id=str(uuid.uuid4()))
    text = "先暂停签收调查，我想问申请入口。"
    req.context.update(current_request=text, previous_tasks={"origin": "MODEL_PREVIOUS_TURN",
        "input_version": 1, "tasks": [{"id": "trace", "intent": "LOGISTICS", "request": "查签收",
        "status": "ANSWERED", "lifecycle": "OPEN"}]})
    opening = understand(req, key="entry", intent="APPLICATION", needs=["GUIDE"], events=[
        group("PAUSE", ["trace"], text), group("ADD", ["entry"], text)])
    bad = parts(part("entry", "未经来源的入口回答。"))
    model = TokenizedScript(mode="live", script=[opening, bad, bad])
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), architecture="staged-v1",
        model_factory=lambda: model, sources_factory=lambda *a: Reads())
    failed = runtime.run(req, "local-read-token")
    assert failed["status"] == "FAILED" and failed["answer"] is None
    update = failed["conversation_update"]
    assert update["input_version"] == 3
    assert update["task_state"]["tasks"][0]["lifecycle"] == "PAUSED"
    assert all(t["evidence_refs"] == [] and t["response_excerpt"] is None
               for t in update["task_state"]["tasks"])
    # Rebuild accepted state from durable recorded model results, with no new generation/reads.
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    model = TokenizedScript(mode="live", script=[opening, bad, bad])
    assert runtime.run(req, "local-read-token") == failed and model.calls == 0
    next_req = request(input_version=4, run_id=str(uuid.uuid4()))
    next_req.context.update(current_request="继续签收调查。",
        previous_tasks={"origin": "MODEL_PREVIOUS_TURN", "input_version": 3,
                        "tasks": update["task_state"]["tasks"]},
        previous_customer_memory=update["customer_memory"])
    resumed = understand(next_req, needs=[], events=[group("RESUME", ["trace"], "继续签收调查。")])
    model = TokenizedScript(mode="live", script=[resumed, parts(part("trace", "已继续原调查。"))])
    result = runtime.run(next_req, "local-read-token")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["conversation_update"]["task_state"]["tasks"][0]["lifecycle"] == "OPEN"


def test_rejected_understanding_never_exports_candidate_as_accepted_state(agent_db):
    req = request(run_id=str(uuid.uuid4()))
    bad = understand(req, needs=[])
    bad["dialogue_events"][0]["quote"] = "不存在的客户原文"
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), architecture="staged-v1",
        model_factory=lambda: TokenizedScript(mode="live", script=[bad, bad]),
        sources_factory=lambda *a: Reads())
    result = runtime.run(req, "local-read-token")
    assert result["status"] == "FAILED" and result.get("conversation_update") is None
    # Changing an unfinished run's architecture must still reject, rather than reset the state/budget.
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    runtime.architecture = "single"
    with pytest.raises(SupportFailure, match="MANIFEST_MISMATCH"):
        runtime.run(req, "local-read-token")


def test_atomic_claim_correction_survives_failed_answer_and_zero_call_recovery(agent_db):
    from resolveflow.support.memory import CustomerMemory
    from tests.unit.test_support_customer_claims import claim

    initial = request(input_version=1)
    initial.context['current_request'] = '门卫没有代收。代收柜已查没有包裹。'
    memory = CustomerMemory(initial)
    memory.propose([claim('门卫没有代收。'), claim('代收柜已查没有包裹。')], [])
    old_id, separate_id = [e['id'] for e in memory.entries]
    req = request(input_version=3, run_id=str(uuid.uuid4()))
    req.context.update(current_request='更正：门卫是否代收还没确认。', previous_customer_memory=memory.snapshot())
    opening = understand(req, needs=['GUIDE'])
    opening['customer_claims'] = [claim('门卫是否代收还没确认。', change='REPLACE', target=old_id)]
    bad = parts(part('trace', '无指南却给入口。'))
    active = [TokenizedScript(mode='live', script=[opening, bad, bad])]
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture='staged-v1',
        model_factory=lambda: active[0], sources_factory=lambda *a: Reads())
    failed = runtime.run(req, 'local-read-token')
    assert failed['status'] == 'FAILED' and failed['answer'] is None
    saved = failed['conversation_update']['customer_memory']
    assert [e['status'] for e in saved['entries']] == ['SUPERSEDED', 'ACTIVE', 'ACTIVE']
    assert saved['entries'][-1]['supersedes'] == [old_id]
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    active[0] = TokenizedScript(mode='live', script=[opening, bad, bad])
    assert runtime.run(req, 'local-read-token') == failed and active[0].calls == 0
    later = request(input_version=4)
    later.context.update(previous_customer_memory=saved)
    retained = CustomerMemory(later).packet()
    assert {e['id'] for e in retained['active']} == {separate_id, saved['entries'][-1]['id']}
    assert [e['quote'] for e in retained['correction_targets']] == [
        '代收柜已查没有包裹。', '门卫是否代收还没确认。']


def test_refinement_and_source_rendered_amount_rebuild_from_saved_calls(agent_db):
    from tests.unit.test_support_grounding import FactReads
    from tests.unit.test_support_refine_needs import refine

    req = request(run_id=str(uuid.uuid4()))
    piece = part("trace", "当前实付{{PAID_AMOUNT}}。")
    piece["facts"] = [{"field": "PAID_AMOUNT", "source": "O1"}]
    script = [understand(req, needs=[]), refine(needs=["ORDER"]),
              {"kind": "READ_TOOL", "tool_name": "get_order_context", "arguments": {}}, parts(piece)]
    active = [TokenizedScript(mode="live", script=script)]
    sources = []

    def source_factory(*args):
        source = FactReads()
        sources.append(source)
        return source

    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), architecture="staged-v1",
        model_factory=lambda: active[0], sources_factory=source_factory)
    result = runtime.run(req, "local-read-token")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["answer"]["text"] == "当前实付123.45 CNY。" and active[0].calls == 4
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    active[0] = TokenizedScript(mode="live", script=script)
    assert runtime.run(req, "local-read-token") == result
    assert active[0].calls == 0 and sources[-1].calls == []
