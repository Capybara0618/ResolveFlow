"""New cohort identity, actual persisted program-rendered steps and no-call reconstruction."""

import uuid

from scripts import customer_agent_navigation_v1 as runner

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import GuideReads, read
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_staged import understand


def test_navigation_cohort_renders_and_persists_both_steps_with_zero_call_restore(agent_db):
    req, _ = runner.prepare_turn(runner.load_cases()[2], 0, [])
    req.run_id = str(uuid.uuid4())
    piece = part('review', '两个操作有不同的用途。')
    piece['next_steps'] = [{'action': action, 'source': 'O1'}
                          for action in ['MERCHANT_REVIEW', 'REFUND_APPLICATION']]
    script = [understand(req, key='review', intent='HANDOFF', needs=['GUIDE']),
              read('get_support_guide'), parts(piece)]
    active = [TokenizedScript(mode='live', script=script)]
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture='staged-v1',
        model_factory=lambda: active[0], sources_factory=lambda *args: GuideReads())
    result = runtime.run(req, 'local-read-token')
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert '人工核查：打开“售后咨询”' in result['answer']['text']
    assert '正式退款：打开“我的售后”' in result['answer']['text']
    assert len(result['answer']['citations']) == 1
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    active[0] = TokenizedScript(mode='live', script=script)
    assert runtime.run(req, 'local-read-token') == result and active[0].calls == 0
