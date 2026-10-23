"""Correct page explanations publish and reconstruct without new model or source calls in real PG."""

import uuid

import pytest

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import GuideReads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_staged import understand


@pytest.mark.parametrize('intent,action,text', [
    ('APPLICATION', 'REFUND_APPLICATION', '正式退款在我的售后选择商品后自行申请。'),
    ('HANDOFF', 'MERCHANT_REVIEW', '请在售后咨询中选择商品，确认后请商家核查。')])
def test_correct_page_and_selected_step_publish_with_zero_call_pg_restore(agent_db, intent, action, text):
    req = request(run_id=str(uuid.uuid4()))
    piece = {**part('entry', text), 'next_steps': [{'action': action, 'source': 'O1'}]}
    script = [understand(req, key='entry', intent=intent, needs=['GUIDE']), read('get_support_guide'), parts(piece)]
    active = [TokenizedScript(mode='live', script=script)]
    source = GuideReads()
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture='staged-v1',
        model_factory=lambda: active[0], sources_factory=lambda *args: source)
    result = runtime.run(req, 'local-test-token')
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['text'].startswith(text)
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    active[0] = TokenizedScript(mode='live', script=script)
    before = list(source.calls)
    assert runtime.run(req, 'local-test-token') == result
    assert active[0].calls == 0 and source.calls == before
