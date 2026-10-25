"""Actual AgentScope/PG/progress + separate basic controller over the same frozen HTTP fixtures."""

import json
from copy import deepcopy

import httpx
import pytest
from scripts import customer_workflow_comparison_live as driver
from scripts.evaluation.customer_comparison_environment import PlainChatClient, RequestAllowance

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.protocol import SupportInput
from resolveflow.support.service import SupportRuntime
from tests.unit.test_customer_comparison_environment import stream_response
from tests.unit.test_support_orchestration import plan


def test_production_agent_and_independent_workflow_execute_without_real_provider(agent_db):
    case = deepcopy(driver.cases()[0])
    case.update(id='control-only', turns=[{'text': '请告诉我售后咨询入口'}, {'text': '好的，继续说明'}])
    ledger = {'used': 0, 'save': lambda: None}
    budget = RequestAllowance(ledger, 0, 12)
    results = {v: [] for v in driver.VARIANTS}
    for number in range(2):
        req, _ = driver.agent_turn(case, number, results['agent'])
        opening = plan(req, intent='OTHER', goal='EXPLAIN').model_dump()
        if number:
            opening['dialogue_events'][0]['change'] = 'CONTINUE'
        replies = iter([opening, {'kind': 'RESPOND',
            'parts': [{'task_id': 'trace', 'text': '可以在聊天中咨询售后。'}]}])
        captured = []
        def handle(call, captured=captured, replies=replies):
            captured.append(json.loads(call.content))
            return httpx.Response(200, text=stream_response(json.dumps(next(replies), ensure_ascii=False)))
        agent_row = driver.empty_row(case, 'agent', number)
        model = driver.RecordedAgentModel(budget=budget, records=agent_row['models'], save=lambda: None,
            provider='deepseek', model_id='deepseek-flash', endpoint=driver.ENDPOINT, api_key='test',
            parameters=driver.PARAMETERS, stream_transport=httpx.MockTransport(handle))
        driver.execute_agent(case, number, results['agent'], agent_row, db=agent_db,
            index_service=None, model=model, save=lambda: None)
        assert agent_row['status'] == 'SUCCEEDED', json.dumps(agent_row['models'], ensure_ascii=False)[-6500:]
        assert len(agent_row['models']) == 2 and all(m['provider_sent'] for m in agent_row['models'])
        assert all(body['max_tokens'] == 1024 for body in captured)
        assert agent_row['first_body_ms'] is not None
        assert agent_row['tools'][0]['category'] == 'GUIDE'
        results['agent'].append(agent_row)
        replies = iter([{'intent': 'GUIDE'}, {'text': '独立基础流程回答', 'handoff_summary': None}])
        with httpx.Client(transport=httpx.MockTransport(lambda _, replies=replies:
                httpx.Response(200, text=stream_response(json.dumps(next(replies), ensure_ascii=False))))) as http:
            plain = PlainChatClient(http, driver.ENDPOINT, 'test', budget)
            basic_row = driver.empty_row(case, 'basic_workflow', number)
            driver.execute_basic(case, number, results['basic_workflow'], basic_row,
                policy=None, model=plain, save=lambda: None)
        assert basic_row['status'] == 'SUCCEEDED' and len(basic_row['models']) == 2
        assert all(m['body']['max_tokens'] == 1024 for m in basic_row['models'])
        assert basic_row['first_body_ms'] is not None and basic_row['tools'][0]['category'] == 'GUIDE'
        results['basic_workflow'].append(basic_row)
    assert ledger['used'] == 8
    assert '独立基础流程回答' not in json.dumps(results['agent'][1]['input'], ensure_ascii=False)
    assert '可以在聊天中咨询售后' not in json.dumps(results['basic_workflow'][1]['input'],
        ensure_ascii=False, default=str)
    # Recover the existing Agent run from PG: no extra provider attempts or source calls.
    previous_count = ledger['used']
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='live', provider='deepseek', model_id='deepseek-flash',
        endpoint=driver.ENDPOINT, api_key='', context_window_tokens=32768, case_base_url='http://frozen-case.local'),
        model_factory=lambda: model, architecture='orchestrated-v1')
    restored = runtime.run(SupportInput.model_validate(results['agent'][1]['input']), 'test', progress_token='test')
    assert restored == results['agent'][1]['raw_result'] and ledger['used'] == previous_count


@pytest.mark.parametrize('cap', [1, 3])
def test_full_driver_stops_at_actual_shared_cap_exports_and_cleans_only_owned_schema(
    agent_db, tmp_path, monkeypatch, cap,
):
    # Uses the original PG readonly sources and a fresh driver-owned schema; all provider HTTP is mocked.
    original_client, sends = httpx.Client, []
    def fake_provider(call):
        sends.append(call.url.host)
        return httpx.Response(200, text=stream_response('not a valid decision'))
    def client(*args, **kwargs):
        if kwargs.get('transport') is None:
            kwargs['transport'] = httpx.MockTransport(fake_provider)
        return original_client(*args, **kwargs)
    monkeypatch.setattr(httpx, 'Client', client)
    ledger = tmp_path / 'ledger.json'
    ledger.write_text('{"used":0}', encoding='utf-8')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{"test":"control only"}', encoding='utf-8')
    monkeypatch.setattr(driver, 'PLAN', manifest)
    monkeypatch.setattr(driver, 'USAGE', ledger)
    monkeypatch.setattr(driver, 'load_plan', lambda: {'parameters': driver.PARAMETERS})
    monkeypatch.setenv('RESOLVEFLOW_MODEL_API_KEY', 'test-only-provider-key')
    output = tmp_path / 'result.json'
    driver.execute(output, cap)
    report = json.loads(output.read_text(encoding='utf-8'))
    assert len(sends) == cap and all(host == 'api.deepseek.com' for host in sends)
    assert report['state'] == 'FINISHED' and len(report['rows']) == 100
    assert sum(r['status'] == 'NOT_RUN' for r in report['rows']) == (99 if cap == 1 else 98)
    assert report['usage_after'] == cap and report['isolated_schema_dropped']
    assert report['public_before'] == report['public_after']
    assert report['all_runs'] and report['all_calls']
    assert 'test-only-provider-key' not in output.read_text(encoding='utf-8')
    from scripts.customer_workflow_comparison_prepare import DATA, digest, load_dataset, performance, runtime_rows
    runtime_rows(load_dataset(), report, digest(DATA))
    assert performance(report['rows'])['provider_attempts'] == cap
