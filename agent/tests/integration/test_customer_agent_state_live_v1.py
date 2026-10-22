"""Use the real finite ASGI/PG executor with a failed answer and accepted pause."""

import pytest
from scripts import customer_agent_state_live_v1 as runner

from resolveflow.support import service
from resolveflow.support.embeddings import SupportEmbeddings
from tests.integration.test_customer_agent_experience_v1 import OfflineProvider
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_staged import understand


def test_actual_executor_inherits_failed_accepted_state_and_never_fakes_an_assistant_answer(
    postgres_dsn, monkeypatch, tmp_path
):
    case = runner.load_cases()[1]
    case['turns'] = case['turns'][:3]
    plan = tmp_path / 'manifest.json'
    runner.prior.write_new(plan, {'version': 'offline-state-test'})
    monkeypatch.setattr(runner, 'PLAN', plan)
    monkeypatch.setattr(runner, 'load_plan', lambda: ({'version': 'offline-state-test'}, [case]))
    monkeypatch.setattr(runner.prior, 'DSN', postgres_dsn)
    monkeypatch.setenv('RESOLVEFLOW_MODEL_API_KEY', 'scripted-offline-test')
    monkeypatch.setattr(SupportEmbeddings, 'prewarm', lambda *a: 0)
    monkeypatch.setattr(SupportEmbeddings, 'get', lambda *a: None)
    texts = [t['text'] for t in case['turns']]
    req = request()
    req.context['current_request'] = texts[0]
    opening = understand(req, key='trace')
    req.context['current_request'] = texts[1]
    pause = understand(req, key='entry', intent='APPLICATION', needs=['GUIDE'], events=[
        group('PAUSE', ['trace'], texts[1]), group('ADD', ['entry'], texts[1])])
    req.context['current_request'] = texts[2]
    resume = understand(req, key='trace', needs=['SHIPMENT', 'GUIDE'], events=[
        group('RESUME', ['trace'], texts[2])])
    resume['customer_claims'] = [{'topic': 'CHECKS', 'reference': 'CURRENT', 'quote': '我问过家人和代收点了，都没代收'}]
    bad = parts(part('entry', '未读取指南的入口回答。'))
    scripts = [
        [opening, read(), parts(part('trace', '系统签收与客户未找到尚有争议。', ['O1']))],
        [pause, bad, bad],
        [resume, read(), read('get_support_guide'),
         parts(part('trace', '已记录排查；从售后咨询预览确认请商家核查。', ['O1', 'O2']))],
    ]
    original = service.SupportRuntime
    models = []

    def factory(self):
        if self.model_factory:
            return self.model_factory()
        model = OfflineProvider(mode='live', script=scripts[len(models)])
        models.append(model)
        return model

    monkeypatch.setattr(original, '_model', factory)
    output, usage = tmp_path / 'result.json', tmp_path / 'usage.json'
    runner.evaluate(output, usage)
    report = runner.prior.read_json(output)
    assert report['state'] == 'FINISHED' and report['isolated_schema_dropped']
    assert report['public_before'] == report['public_after']
    assert [r['result']['status'] for r in report['rows']] == ['SUCCEEDED', 'FAILED', 'SUCCEEDED']
    third = report['rows'][2]
    assert third['input']['context']['previous_tasks']['tasks'][0]['lifecycle'] == 'PAUSED'
    assert len([m for m in third['input']['context']['history'] if m['author'] == 'ASSISTANT']) == 1
    assert third['result']['answer']['customer_memory']['entries'][0]['quote'] == '我问过家人和代收点了，都没代收'
    assert [m.calls for m in models] == [3, 3, 4]
    assert service.SupportRuntime is original
    with pytest.raises(FileExistsError):
        runner.evaluate(output, usage)
