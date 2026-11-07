"""Unannotated investigation and delayed declaration persist across actual API/store recovery."""

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


def test_three_reads_then_three_task_publication_and_zero_call_recovery(agent_db, tmp_path):
    req = request()
    req.context['current_request'] = '查物流、退款资格以及申请入口'
    script = [read('get_order_context'), read(), read('get_support_guide'),
              parts(part('shipping', '系统记录已签收。', ['O2']),
                    part('qualify', '签收争议需商家核验，暂不能确定退款资格。', ['O2'], 'NEEDS_MERCHANT'),
                    part('entry', '正式退款申请入口为我的售后。', ['O3']),
                    tasks=[task('shipping'), task('qualify', 'ELIGIBILITY'), task('entry', 'APPLICATION')],
                    dialogue_events=[group('ADD', ['shipping', 'qualify', 'entry'], req.context['current_request'])])]
    active = [TokenizedScript(script=script, mode='live')]
    paths = []

    def transport(call):
        paths.append(call.url.path)
        assert req.run_id in call.url.path
        if call.url.path.endswith('/current'):
            return httpx.Response(200, json={'conversation_id': req.conversation_id,
                                            'input_version': req.input_version})
        if call.url.path.endswith('/facts/order'):
            return httpx.Response(200, json={'version': 1, 'status': 'PAID', 'synthetic': True})
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
            assert active[0].calls == 4
            assert [a['tool_name'] for a in active[0].packets[-1]['recent_actions']] == [
                'get_order_context', 'get_shipment_trace', 'get_support_guide']
            assert all(p['feedback'] is None and p['task_state']['tasks'] == [] for p in active[0].packets)
            assert len(result['answer']['task_state']['tasks']) == 3
            assert [e['task_id'] for e in result['answer']['dialogue_state']['events']] == [
                'shipping', 'qualify', 'entry']
            assert {c['source_id'] for c in result['answer']['citations']} == {'O2', 'O3'}
            with agent_db.connection() as c:
                records = c.execute('SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY kind,position',
                                    (req.run_id,)).fetchall()
                assert len(records) == 7
                assert [row['response_json']['decision'] for row in records if row['kind'] == 'model'] == script
                c.execute("UPDATE support_agent_run SET result_json=NULL,status='RUNNING',"
                          "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
            before = list(paths)
            active[0] = TokenizedScript(script=script, mode='live')
            assert api.post('/internal/v1/support-runs', json=body, headers=headers).json() == result
            assert active[0].calls == 0 and paths == before
