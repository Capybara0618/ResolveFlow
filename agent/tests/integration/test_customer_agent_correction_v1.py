"""Scripted integration tests exercise new subjects with the production staged runtime."""

import uuid

from scripts import customer_agent_correction_v1 as runner

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import GuideReads, read
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_customer_claims import claim
from tests.unit.test_support_staged import understand


def test_frozen_new_first_turn_records_independent_claims_and_restores_without_calls(agent_db):
    case = runner.load_cases()[0]
    req, _ = runner.prepare_turn(case, 0, [])
    req.run_id = str(uuid.uuid4())
    opening = understand(req)
    opening['customer_claims'] = [claim('家人没代收'), claim('门卫已经问过也没有')]
    script = [opening, read(), parts(part('trace', '记录显示签收，客户反馈未收到。', ['O1']))]
    active = [TokenizedScript(mode='live', script=script)]
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture='staged-v1',
        model_factory=lambda: active[0], sources_factory=lambda *args: GuideReads())
    result = runtime.run(req, 'local-read-token')
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert len(result['conversation_update']['customer_memory']['entries']) == 2
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    active[0] = TokenizedScript(mode='live', script=script)
    assert runtime.run(req, 'local-read-token') == result and active[0].calls == 0
