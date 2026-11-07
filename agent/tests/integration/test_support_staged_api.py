"""Same four-turn business path in both architectures, actual ASGI/PG and zero-call recovery."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from resolveflow.support.sources import BoundSources
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_context import message
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_staged import understand
from tests.unit.test_support_tasks import task

SECRET = 'staged-test-local-secret-only'  # noqa: S105 - scoped test identity, no real credential


def test_refund_summary_survives_persisted_recovery_without_model_or_tool_resend(agent_db):
    from tests.unit.test_support_agent import GuideReads

    req = request(run_id=str(uuid.uuid4()))
    summary = '客户反馈未收到商品，请核实签收后处理退款申请。'
    final = parts({**part('trace', '请核对申请摘要后自行确认。', ['O1']),
                   'next_steps': [{'action': 'REFUND_APPLICATION', 'source': 'O1'}]})
    final['refund_summary'] = summary
    script = [understand(req, intent='APPLICATION', needs=['GUIDE']), read('get_support_guide'), final]
    models, source = [TokenizedScript(mode='live', script=script)], GuideReads()
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture='staged-v1',
                             model_factory=lambda: models[0], sources_factory=lambda *_: source)
    result = runtime.run(req, 'bound-test-token')
    assert result['status'] == 'SUCCEEDED' and result['answer']['refund_summary'] == summary
    assert models[0].calls == 3
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    models[0] = TokenizedScript(mode='live', script=script)
    assert runtime.run(req, 'replacement-bound-test-token') == result
    assert models[0].calls == 0 and source.calls == [('get_support_guide', {})]


def test_branched_query_journal_rebuilds_without_resending_models_or_search(agent_db):
    from tests.unit.test_support_agent import Reads

    class Branches(Reads):
        def search(self, query, top_k, *, sub_queries=None):
            self.calls.append((query, top_k, sub_queries))
            return [{'source_type': 'POLICY', 'version': 'v1', 'data': {'text': text}}
                    for text in ['在途不足以确认丢失。', '假设确认丢失后须人工核验。']]

    req = request(run_id=str(uuid.uuid4()))
    query, branches = '当前与假设条件', ['当前在途', '假设确认丢失']
    script = [understand(req, intent='OTHER', needs=['POLICY']),
              read('search_policy', query=query, sub_queries=branches, top_k=3),
              parts(part('trace', '仅解释条件，不认定当前丢失或退款资格。', ['P1', 'P2']))]
    model, source = [TokenizedScript(mode='live', script=script)], Branches()
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture='staged-v1',
                             model_factory=lambda: model[0], sources_factory=lambda *_: source)
    result = runtime.run(req, 'bound-test-token')
    assert result['status'] == 'SUCCEEDED' and model[0].calls == 3
    with agent_db.connection() as c:
        call = c.execute("SELECT request_json FROM support_agent_call WHERE run_id=%s AND kind='tool'",
                         (req.run_id,)).fetchone()
        assert call['request_json']['arguments'] == {'query': query, 'sub_queries': branches, 'top_k': 3}
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    model[0] = TokenizedScript(mode='live', script=script)
    assert runtime.run(req, 'replacement-bound-test-token') == result
    assert model[0].calls == 0 and source.calls == [(query, 3, branches)]


@pytest.mark.parametrize('architecture', ['single', 'staged-v1'])
def test_focus_ledger_and_phase_rebuild_after_each_turn_with_no_new_calls(agent_db, tmp_path, architecture):
    texts = ['签收没找到，可能家人代收了。', '这件事先暂停，问一下正式申请入口。',
             '继续核查。纠正：家人和代收点都没有代收。', '包裹找到了，不用再查了。']
    active, bound, paths, models, results, history = [None], [None], [], [], [], []

    def transport(call):
        req = bound[0]
        paths.append(call.url.path)
        assert req.run_id in call.url.path
        if call.url.path.endswith('/current'):
            return httpx.Response(200, json={'conversation_id': req.conversation_id,
                                              'input_version': req.input_version})
        assert call.url.path.endswith('/facts/shipment')
        return httpx.Response(200, json={'version': 3, 'line_id': req.line_id,
                                          'status': 'DELIVERED', 'synthetic': True})

    with httpx.Client(transport=httpx.MockTransport(transport)) as upstream:
        runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture=architecture,
                                 model_factory=lambda: active[0],
                                 sources_factory=lambda req, token, journal: BoundSources(
                                     req, case_url='http://case.local', token=token, journal=journal, client=upstream))
        app = create_app(provider_db=tmp_path / 'provider.db', delivery_loop=False, worker_loop=False,
                         migrate=False, jwt_secret=SECRET, support_runtime=runtime)
        with TestClient(app) as api:
            for index, text in enumerate(texts):
                req = request(run_id=str(uuid.uuid4()), input_version=1 + len(history))
                history.append(message(req.input_version, text))
                req.context.update(current_request=text, history=list(history))
                if results:
                    prior = results[-1]
                    req.context.update(previous_tasks={'origin': 'MODEL_PREVIOUS_TURN',
                        'input_version': prior['input_version'], 'tasks': prior['answer']['task_state']['tasks']},
                        previous_customer_memory=prior['answer']['customer_memory'])
                if index == 0:
                    focus, intent, needs = 'trace', 'LOGISTICS', ['SHIPMENT']
                    events, memory = [group('ADD', [focus], text)], []
                    reads, final = [read()], parts(part(focus, '承运方记录签收，是否亲收尚待核实。', ['O1']))
                elif index == 1:
                    focus, intent, needs = 'entry', 'APPLICATION', ['GUIDE']
                    events = [group('PAUSE', ['trace'], text), group('ADD', [focus], text)]
                    memory, reads = [], [read('get_support_guide')]
                    final = parts(part(focus, '正式申请入口为我的售后。', ['O1']))
                elif index == 2:
                    focus, intent, needs = 'trace', 'LOGISTICS', ['SHIPMENT', 'GUIDE']
                    events = [group('RESUME', [focus], text)]
                    memory = [{'id': 'checked', 'topic': 'CHECKS', 'reference': 'CURRENT',
                               'quote': '家人和代收点都没有代收。'}]
                    reads = [read(), read('get_support_guide')]
                    final = parts(part(focus, '已记录排查；请从售后咨询预览摘要后确认请商家核查。', ['O1', 'O2']))
                else:
                    focus, intent, needs = 'trace', 'LOGISTICS', []
                    events, memory, reads = [group('RESOLVE', [focus], text)], [], []
                    final = parts(part(focus, '已记录找到包裹，结束核查。', status='CANCELLED'))
                if architecture == 'staged-v1':
                    if index in {1, 2}:
                        final['parts'][0]['text'] = '请核对后自行确认下一步操作。'
                        final['parts'][0]['next_steps'] = [{
                            'action': 'REFUND_APPLICATION' if index == 1 else 'MERCHANT_REVIEW',
                            'source': 'O1' if index == 1 else 'O2'}]
                    script = [understand(req, key=focus, intent=intent, needs=needs, events=events, memory=memory),
                              *reads, final]
                else:
                    declaration = {'tasks': [task(focus, intent)], 'dialogue_events': events,
                                   'memory_updates': memory}
                    script = [*reads, final]
                    script[0] = {**script[0], **declaration}
                active[0] = TokenizedScript(mode='live', script=script)
                models.append(active[0])
                bound[0] = req
                token = mint_service_token('case-service', SECRET, scope='support:run',
                                           merchant_id=req.merchant_id, buyer_id=req.buyer_id)
                headers = {'Authorization': 'Bearer ' + token}
                body = {**req.model_dump(mode='json'), 'tool_token': 'bound-test-token'}
                response = api.post('/internal/v1/support-runs', json=body, headers=headers)
                assert response.status_code == 200
                result = response.json()
                assert result['status'] == 'SUCCEEDED', result['reason']
                results.append(result)
                history.append(message(req.input_version + 1, result['answer']['text'], 'ASSISTANT'))
                with agent_db.connection() as c:
                    c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                              "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
                before_paths = list(paths)
                active[0] = TokenizedScript(mode='live', script=script)
                replayed = api.post('/internal/v1/support-runs', json=body, headers=headers)
                assert replayed.json() == result and active[0].calls == 0 and paths == before_paths
            assert [t['id'] for t in results[1]['answer']['task_state']['tasks']] == ['trace', 'entry']
            assert results[1]['answer']['task_state']['focus_ids'] == ['entry']
            assert [r['answer']['task_state']['tasks'][0]['lifecycle'] for r in results] == [
                'OPEN', 'PAUSED', 'OPEN', 'RESOLVED']
            assert results[2]['answer']['customer_memory']['entries'][0]['source']['offset'] == 8
            assert [m.calls for m in models] == ([2, 2, 3, 1] if architecture == 'single' else [3, 3, 4, 2])
            # An unfinished saved run must not silently switch architecture or reset phase/budget.
            with agent_db.connection() as c:
                c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                          "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
            runtime.architecture = 'single' if architecture == 'staged-v1' else 'staged-v1'
            response = api.post('/internal/v1/support-runs', json=body, headers=headers)
            assert response.status_code == 409 and response.json()['detail'] == 'MANIFEST_MISMATCH'
            assert active[0].calls == 0
