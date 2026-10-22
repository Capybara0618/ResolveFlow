"""New finite executor through actual ASGI/PG, with an explicitly scripted provider."""

import pytest
from scripts import customer_agent_experience_v2 as runner

from resolveflow.support.embeddings import SupportEmbeddings
from resolveflow.support.service import SupportRuntime
from tests.integration.test_customer_agent_experience_v1 import OfflineProvider
from tests.unit.test_support_agent import read
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


def test_new_version_exports_actual_calls_and_cleans_only_own_schema(postgres_dsn, monkeypatch, tmp_path):
    case = runner.load_cases()[0]
    plan = tmp_path / 'manifest.json'
    runner.prior.write_new(plan, {'version': 'offline-wrapper-test'})
    monkeypatch.setattr(runner, 'PLAN', plan)
    monkeypatch.setattr(runner, 'load_plan', lambda: ({'version': 'offline-wrapper-test'}, [case]))
    monkeypatch.setattr(runner.prior, 'DSN', postgres_dsn)
    monkeypatch.setenv('RESOLVEFLOW_MODEL_API_KEY', 'scripted-offline-test')
    monkeypatch.setattr(SupportEmbeddings, 'prewarm', lambda self, path: 0)
    monkeypatch.setattr(SupportEmbeddings, 'get', lambda self, path: None)
    model = OfflineProvider(mode='live', script=[read(), parts(part('trace', '当前物流运输中。', ['O1']),
        tasks=[task('trace')], dialogue_events=[group('ADD', ['trace'], case['turns'][0]['text'])])])

    def factory(self):
        return self.model_factory() if self.model_factory else model

    monkeypatch.setattr(SupportRuntime, '_model', factory)
    output, usage = tmp_path / 'result.json', tmp_path / 'usage.json'
    old_bindings = runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn
    runner.evaluate(output, usage)
    result = runner.prior.read_json(output)
    assert result['version'] == 'offline-wrapper-test' and result['state'] == 'FINISHED'
    assert result['rows'][0]['result']['status'] == 'SUCCEEDED'
    assert model.calls == 2 and len(result['all_runs']) == 1 and len(result['all_calls']) == 3
    assert result['public_before'] == result['public_after'] and result['isolated_schema_dropped']
    assert (runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn) == old_bindings
    with pytest.raises(FileExistsError):
        runner.evaluate(output, usage)
    assert model.calls == 2
