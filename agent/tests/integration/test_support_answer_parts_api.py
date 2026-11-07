"""Raw parts are journaled, their rendered result is stable on fenced recovery."""

import httpx
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from resolveflow.support.sources import BoundSources
from tests.integration.test_support_dialogue_api import SECRET, TokenizedScript
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


def test_parts_persist_raw_and_recover_identical_rendered_answer_with_no_new_calls(agent_db, tmp_path):
    req = request()
    initial = {**read(), 'tasks': [task('a'), task('b', 'ELIGIBILITY')],
               'dialogue_events': [group('ADD', ['a', 'b'], req.context['current_request'])]}
    script = [initial, parts(part('a', '系统有签收记录。', ['O1']),
                             part('b', '退款条件需要商家核验。', status='NEEDS_MERCHANT'))]
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
                                       merchant_id=req.merchant_id, buyer_id=req.buyer_id)
            headers = {'Authorization': 'Bearer ' + token}
            body = {**req.model_dump(mode='json'), 'tool_token': 'synthetic-read-token'}
            response = api.post('/internal/v1/support-runs', json=body, headers=headers)
            assert response.status_code == 200
            result = response.json()
            assert result['status'] == 'SUCCEEDED', result['reason']
            assert result['answer']['text'] == '系统有签收记录。\n\n退款条件需要商家核验。'
            assert result['answer']['task_state']['tasks'][1]['status'] == 'NEEDS_MERCHANT'
            with agent_db.connection() as c:
                records = c.execute("SELECT * FROM support_agent_call "
                                    "WHERE run_id=%s AND kind='model' ORDER BY position",
                                    (req.run_id,)).fetchall()
                assert len(records) == 2
                assert records[1]['response_json']['decision'] == script[1]
                c.execute("UPDATE support_agent_run SET result_json=NULL,status='RUNNING',"
                          "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
            before = list(paths)
            active[0] = TokenizedScript(script=script, mode='live')
            assert api.post('/internal/v1/support-runs', json=body, headers=headers).json() == result
            assert active[0].calls == 0 and paths == before
