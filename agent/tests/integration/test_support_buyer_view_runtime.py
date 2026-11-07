"""Real API/SDK/isolated PG persistence and recovery; scripted decisions, no provider network."""

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.integration.test_support_staged_api import SECRET
from tests.support_request_checks import checked_script
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_orchestrated_engine import Sources, respond
from tests.unit.test_support_orchestration import plan


@pytest.mark.parametrize('operation,approved', [(True, True), (False, False), (True, False)])
def test_api_and_fenced_saved_call_recovery_keep_buyer_projection_without_new_calls(
    agent_db, monkeypatch, tmp_path, operation, approved,
):
    req = request()
    text, guide = '商家还需要核实具体情况。', '核对共享内容后再确认。'
    if operation and not approved:
        req.context['current_request'] = '耳机没收到，现在应该找谁帮我？我只问一下。'
        text, guide = '你可以先请商家协助核实。', None
    opening = plan(req) if operation else plan(req, intent='OTHER', goal='EXPLAIN', needs=['GUIDE'])
    final = respond(parts=[{'task_id': 'trace', 'text': text, 'guidance': guide, 'citations': ['O1']}],
                    **({} if approved else {'refund_reason': None}))
    script = checked_script([opening.model_dump(), *([read('get_order_context')] if operation else []), final])
    if operation and not approved:
        script[1] = {'kind': 'CHECK_REQUEST', 'assessments': [{'task_id': 'trace', 'purpose': 'INFORMATION',
                     'quote': '现在应该找谁帮我', 'reason': '买家只问协助对象，没有请求准备。'}]}
    models, sources = [TokenizedScript(mode='live', script=script)], Sources()
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture='orchestrated-v1',
                             model_factory=lambda: models[0], sources_factory=lambda *_: sources)
    monkeypatch.setenv('RESOLVEFLOW_SUPPORT_ARCHITECTURE', 'orchestrated-v1')
    app = create_app(provider_db=tmp_path / 'provider.db', delivery_loop=False, worker_loop=False,
                     migrate=False, jwt_secret=SECRET, support_runtime=runtime)
    token = mint_service_token('case-service', SECRET, scope='support:run',
                               merchant_id=req.merchant_id, buyer_id=req.buyer_id)
    headers = {'Authorization': 'Bearer ' + token}
    body = {**req.model_dump(mode='json'), 'tool_token': 'test-bound'}
    with TestClient(app) as api:
        reply = api.post('/internal/v1/support-runs', json=body, headers=headers)
        assert reply.status_code == 200
        result = reply.json()
        assert result['status'] == 'SUCCEEDED', result['reason']
        part = result['answer']['buyer_view']['parts'][0]
        if approved:
            assert part == {'task_id': 'trace', 'text': text, 'action': 'REFUND_APPLICATION'}
            assert result['answer']['text'] == text
        elif guide is not None:
            assert part == {'task_id': 'trace', 'text': text, 'guidance': guide}
            assert result['answer']['text'] == text + '\n\n' + guide
        else:
            assert part == {'task_id': 'trace', 'text': text}
            assert result['answer']['text'] == text and not result['answer'].get('refund_summary')
        with agent_db.connection() as c:
            saved = c.execute('SELECT result_json,manifest_json,fence FROM support_agent_run WHERE run_id=%s',
                              (req.run_id,)).fetchone()
            assert saved['result_json'] == result
            assert saved['manifest_json']['buyer_presentation'] == 'buyer-view-v1'
            assert 'presentation.py' in saved['manifest_json']['code']
            assert saved['manifest_json']['operation_request_check'] == 'request-check-v1'
            assert 'request_check.py' in saved['manifest_json']['code']
            path = Path(__file__).parents[2] / 'src/resolveflow/support/request_check.py'
            assert saved['manifest_json']['code']['request_check.py'] == hashlib.sha256(path.read_bytes()).hexdigest()
            calls = c.execute("SELECT response_json FROM support_agent_call WHERE run_id=%s AND kind='model' "
                              "ORDER BY position", (req.run_id,)).fetchall()
            assert calls[-1]['response_json']['decision']['parts'][0]['guidance'] == guide
            assert [row['response_json']['decision']['kind'] for row in calls].count('CHECK_REQUEST') == int(operation)
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
        runtime.architecture = 'staged-v1'
        assert runtime.run(req, 'test-bound') == result  # Published historical results remain reusable.
        with agent_db.connection() as c:
            c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                      "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
        with pytest.raises(SupportFailure, match='MANIFEST_MISMATCH'):
            runtime.run(req, 'test-bound')
        assert models[0].calls == 0 and sources.calls == sources_before
