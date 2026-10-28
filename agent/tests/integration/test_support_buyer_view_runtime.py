"""Real API/SDK/isolated PG persistence and recovery; scripted decisions, no provider network."""

import pytest
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.integration.test_support_staged_api import SECRET
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_orchestrated_engine import Sources, respond
from tests.unit.test_support_orchestration import plan


@pytest.mark.parametrize('operation', [True, False])
def test_api_and_fenced_saved_call_recovery_keep_buyer_projection_without_new_calls(
    agent_db, monkeypatch, tmp_path, operation,
):
    req = request()
    text, guide = '商家还需要核实具体情况。', '核对共享内容后再确认。'
    opening = plan(req) if operation else plan(req, intent='OTHER', goal='EXPLAIN', needs=['GUIDE'])
    final = respond(parts=[{'task_id': 'trace', 'text': text, 'guidance': guide, 'citations': ['O1']}],
                    **({} if operation else {'refund_reason': None}))
    script = [opening.model_dump(), *([read('get_order_context')] if operation else []), final]
    models, sources = [TokenizedScript(mode='live', script=script)], Sources()
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture='orchestrated-v1',
                             model_factory=lambda: models[0], sources_factory=lambda *_: sources)
    monkeypatch.setenv('RESOLVEFLOW_SUPPORT_ARCHITECTURE', 'orchestrated-v1')
    app = create_app(provider_db=tmp_path / 'provider.db', delivery_loop=False, worker_loop=False,
                     migrate=False, jwt_secret=SECRET, support_runtime=runtime)
    token = mint_service_token('case-service', SECRET, scope='support:run',
                               merchant_id=req.merchant_id, customer_id=req.customer_id)
    headers = {'Authorization': 'Bearer ' + token}
    body = {**req.model_dump(mode='json'), 'tool_token': 'test-bound'}
    with TestClient(app) as api:
        reply = api.post('/internal/v1/support-runs', json=body, headers=headers)
        assert reply.status_code == 200
        result = reply.json()
        assert result['status'] == 'SUCCEEDED', result['reason']
        part = result['answer']['buyer_view']['parts'][0]
        if operation:
            assert part == {'task_id': 'trace', 'text': text, 'action': 'REFUND_APPLICATION'}
            assert result['answer']['text'] == text
        else:
            assert part == {'task_id': 'trace', 'text': text, 'guidance': guide}
            assert result['answer']['text'] == text + '\n\n' + guide
        with agent_db.connection() as c:
            saved = c.execute('SELECT result_json,manifest_json,fence FROM support_agent_run WHERE run_id=%s',
                              (req.run_id,)).fetchone()
            assert saved['result_json'] == result
            assert saved['manifest_json']['buyer_presentation'] == 'buyer-view-v1'
            assert 'presentation.py' in saved['manifest_json']['code']
            calls = c.execute("SELECT response_json FROM support_agent_call WHERE run_id=%s AND kind='model' "
                              "ORDER BY position", (req.run_id,)).fetchall()
            assert calls[-1]['response_json']['decision']['parts'][0]['guidance'] == guide
        sources_before = list(sources.calls)
        models[0] = TokenizedScript(mode='live', script=script)
        assert api.post('/internal/v1/support-runs', json=body, headers=headers).json() == result
        assert models[0].calls == 0 and sources.calls == sources_before
        with agent_db.connection() as c:
            c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                      "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
        assert api.post('/internal/v1/support-runs', json=body, headers=headers).json() == result
        assert models[0].calls == 0 and sources.calls == sources_before
        with agent_db.connection() as c:
            assert c.execute('SELECT fence FROM support_agent_run WHERE run_id=%s', (req.run_id,)).fetchone()[
                'fence'] == saved['fence'] + 1
