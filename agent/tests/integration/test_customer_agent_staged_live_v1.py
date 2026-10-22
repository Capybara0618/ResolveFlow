"""Actual paired executor dispatches the requested architecture; providers are scripted."""

import pytest
from scripts import customer_agent_staged_live_v1 as runner

from resolveflow.support import service
from resolveflow.support.embeddings import SupportEmbeddings
from tests.integration.test_customer_agent_experience_v1 import OfflineProvider
from tests.unit.test_support_agent import read
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_staged import understand
from tests.unit.test_support_tasks import task


def test_paired_runs_select_manifest_architecture_and_use_real_previous_result(postgres_dsn, monkeypatch, tmp_path):
    selected = runner.load_cases()[:2]
    for c in selected:
        c['turns'] = c['turns'][:1]
    plan = tmp_path / 'manifest.json'
    runner.prior.write_new(plan, {'version': 'offline-paired-test'})
    monkeypatch.setattr(runner, 'PLAN', plan)
    monkeypatch.setattr(runner, 'load_plan', lambda: ({'version': 'offline-paired-test'}, selected))
    monkeypatch.setattr(runner.prior, 'DSN', postgres_dsn)
    monkeypatch.setenv('RESOLVEFLOW_MODEL_API_KEY', 'scripted-offline-test')
    monkeypatch.setattr(SupportEmbeddings, 'prewarm', lambda self, path: 0)
    monkeypatch.setattr(SupportEmbeddings, 'get', lambda self, path: None)
    one, _ = runner.prepare_turn(selected[0], 0, [])
    two, _ = runner.prepare_turn(selected[1], 0, [])
    scripts = [
        [read(), parts(part('trace', '承运记录为已签收，不代表本人已收到。', ['O1']), tasks=[task('trace')],
                       dialogue_events=[group('ADD', ['trace'], one.context['current_request'])])],
        [understand(two), read(), parts(part('trace', '承运记录为已签收，不代表本人已收到。', ['O1']))],
    ]
    original_runtime = service.SupportRuntime
    models = []

    def factory(self):
        if self.model_factory:
            return self.model_factory()
        model = OfflineProvider(mode='live', script=scripts[len(models)])
        models.append(model)
        return model

    monkeypatch.setattr(original_runtime, '_model', factory)
    output, usage = tmp_path / 'result.json', tmp_path / 'usage.json'
    runner.evaluate(output, usage)
    r = runner.prior.read_json(output)
    assert r['state'] == 'FINISHED' and r['isolated_schema_dropped']
    assert r['public_before'] == r['public_after']
    assert [row['result']['status'] for row in r['rows']] == ['SUCCEEDED', 'SUCCEEDED']
    assert [row['run']['manifest_json']['architecture'] for row in r['rows']] == ['single', 'staged-v1']
    assert [m.calls for m in models] == [2, 3] and len(r['all_calls']) == 7
    assert service.SupportRuntime is original_runtime
    with pytest.raises(FileExistsError):
        runner.evaluate(output, usage)
    assert runner.prior.read_json(usage)['used'] == 5
