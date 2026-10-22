"""Actual ASGI/PG six-turn executor wiring; four-turn lifecycle prefix uses a scripted provider."""

import pytest
from resolveflow.support.embeddings import SupportEmbeddings
from resolveflow.support.service import SupportRuntime
from scripts import customer_agent_experience_v3 as runner

from tests.integration.test_customer_agent_experience_v1 import OfflineProvider
from tests.unit.test_support_agent import read
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


def test_answered_prefix_pause_resume_correction_cancel_via_saved_runtime(postgres_dsn, monkeypatch, tmp_path):
    case = runner.load_cases()[0]
    texts = [t['text'] for t in case['turns']]
    plan = tmp_path / 'manifest.json'
    runner.prior.write_new(plan, {'version': 'offline-v3-test'})
    monkeypatch.setattr(runner, 'PLAN', plan)
    monkeypatch.setattr(runner, 'load_plan', lambda: ({'version': 'offline-v3-test'}, [case]))
    monkeypatch.setattr(runner.prior, 'DSN', postgres_dsn)
    monkeypatch.setenv('RESOLVEFLOW_MODEL_API_KEY', 'scripted-offline-test')
    monkeypatch.setattr(SupportEmbeddings, 'prewarm', lambda self, path: 0)
    monkeypatch.setattr(SupportEmbeddings, 'get', lambda self, path: None)
    scripts = [
        [read(), parts(part('trace', '有签收记录，但你是否亲收仍待核查。', ['O1']), tasks=[task('trace')],
            dialogue_events=[group('ADD', ['trace'], texts[0])],
            memory_updates=[{'id': 'receipt', 'topic': 'RECEIPT', 'reference': 'CURRENT',
                             'quote': '可能家人代收了。'}])],
        [read('get_support_guide'), parts(
            part('trace', '签收核查暂停。', status='SUSPENDED'),
            part('entry', '正式申请入口为我的售后。', ['O1']),
            tasks=[task('trace', status='SUSPENDED'), task('entry', 'APPLICATION')],
            dialogue_events=[group('PAUSE', ['trace'], texts[1]), group('ADD', ['entry'], texts[1])])],
        [read(), parts(part('trace', '已记录两处排查，仍须商家核验签收。', ['O1'], status='NEEDS_MERCHANT'),
            tasks=[task('trace')], dialogue_events=[group('RESUME', ['trace'], texts[2])],
            memory_updates=[{'id': 'checked', 'topic': 'RECEIPT', 'reference': 'CURRENT',
                             'quote': '我问过家人和代收点了，都没代收', 'supersedes': ['receipt']}])],
        [parts(part('trace', '已记录找到包裹，不再核查。', status='CANCELLED'), tasks=[task('trace')],
            dialogue_events=[group('CANCEL', ['trace'], texts[3])], memory_updates=[
                {'id': 'found', 'topic': 'RECEIPT', 'reference': 'CURRENT', 'quote': texts[3],
                 'supersedes': ['checked']}])],
    ]
    models = []

    def factory(self):
        if self.model_factory:
            return self.model_factory()
        model = OfflineProvider(mode='live', script=scripts[len(models)])
        models.append(model)
        return model

    monkeypatch.setattr(SupportRuntime, '_model', factory)
    output, usage = tmp_path / 'result.json', tmp_path / 'usage.json'
    old_bindings = runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn
    runner.evaluate(output, usage)
    result = runner.prior.read_json(output)
    assert result['state'] == 'FINISHED'
    assert all(row['result']['status'] == 'SUCCEEDED' for row in result['rows'])
    assert [row['result']['answer']['task_state']['tasks'][0]['lifecycle'] for row in result['rows']] == [
        'OPEN', 'PAUSED', 'OPEN', 'CANCELLED']
    previous = result['rows'][1]['input']['context']['previous_tasks']['tasks'][0]
    assert previous['status'] == 'ANSWERED' and previous['lifecycle'] == 'OPEN'
    claim = next(c for c in result['rows'][2]['result']['answer']['customer_memory']['entries']
                 if c['id'] == 'checked')
    assert claim['source']['offset'] > 0
    assert [model.calls for model in models] == [2, 2, 2, 1]
    assert len(result['all_runs']) == 4 and len(result['all_calls']) == 10
    assert result['public_before'] == result['public_after'] and result['isolated_schema_dropped']
    assert (runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn) == old_bindings
    with pytest.raises(FileExistsError):
        runner.evaluate(output, usage)
    assert runner.prior.read_json(usage)['used'] == 7
