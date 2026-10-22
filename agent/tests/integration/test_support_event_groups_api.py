"""Grouped model annotations cross ASGI/AgentScope/PG and replay without new calls."""

import httpx
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from resolveflow.support.sources import BoundSources
from tests.integration.test_support_dialogue_api import SECRET, TokenizedScript
from tests.unit.test_support_agent import answer, read, request
from tests.unit.test_support_dialogue import event
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


def test_group_correction_is_persisted_and_rebuilt_without_model_or_network(agent_db, tmp_path):
    req = request()
    quote = req.context['current_request']
    pending = [task('a'), task('b', 'ELIGIBILITY'), task('c', 'APPLICATION')]
    final = [task('a', status='ANSWERED', evidence_refs=['O1'], response_excerpt='系统有签收记录'),
             task('b', 'ELIGIBILITY', 'NEEDS_MERCHANT', response_excerpt='需要商家核验'),
             task('c', 'APPLICATION', 'ANSWERED', evidence_refs=['O2'], response_excerpt='正式申请入口为我的售后')]
    script = [{**read(), 'tasks': pending, 'dialogue_events': [event('ADD', 'a', quote)]},
              {**read(), 'tasks': pending, 'dialogue_events': [group('ADD', ['a', 'b', 'c'], quote)]},
              read('get_support_guide'),
              answer(text='系统有签收记录，需要商家核验。正式申请入口为我的售后。',
                     citations=['O1', 'O2'], tasks=final)]
    active = [TokenizedScript(script=script, mode='live')]
    paths = []

    def transport(call):
        paths.append(call.url.path)
        assert req.run_id in call.url.path
        if call.url.path.endswith('/current'):
            return httpx.Response(200, json={'conversation_id': req.conversation_id,
                                            'input_version': req.input_version})
        assert call.url.path.endswith('/facts/shipment')
        return httpx.Response(200, json={'version': 3, 'status': 'DELIVERED', 'synthetic': True})

    with httpx.Client(transport=httpx.MockTransport(transport)) as upstream:
        runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), model_factory=lambda: active[0],
            sources_factory=lambda bound, token, journal: BoundSources(
                bound, case_url='http://case.local', token=token, journal=journal, client=upstream))
        app = create_app(provider_db=tmp_path / 'provider.db', delivery_loop=False, worker_loop=False,
                         migrate=False, jwt_secret=SECRET, support_runtime=runtime)
        with TestClient(app) as api:
            token = mint_service_token('case-service', SECRET, scope='support:run',
                                       merchant_id=req.merchant_id, customer_id=req.customer_id)
            headers = {'Authorization': 'Bearer ' + token}
            body = {**req.model_dump(mode='json'), 'tool_token': 'synthetic-read-token'}
            response = api.post('/internal/v1/support-runs', json=body, headers=headers)
            assert response.status_code == 200
            result = response.json()
            assert result['status'] == 'SUCCEEDED', result['reason']
            assert [e['task_id'] for e in result['answer']['dialogue_state']['events']] == ['a', 'b', 'c']
            assert active[0].calls == 4
            with agent_db.connection() as c:
                calls = c.execute('SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY kind,position',
                                  (req.run_id,)).fetchall()
                model_calls = [row for row in calls if row['kind'] == 'model']
                assert len(model_calls) == 4 and len(calls) == 6
                assert model_calls[1]['response_json']['decision']['dialogue_events'][0]['task_ids'] == ['a', 'b', 'c']
                c.execute("UPDATE support_agent_run SET result_json=NULL,status='RUNNING',"
                          "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
            before = list(paths)
            active[0] = TokenizedScript(script=script, mode='live')
            assert api.post('/internal/v1/support-runs', json=body, headers=headers).json() == result
            assert active[0].calls == 0 and paths == before
