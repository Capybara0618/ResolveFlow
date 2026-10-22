"""The experience driver uses actual preceding API results; provider and weights are explicitly scripted."""

from scripts import customer_agent_experience_v1 as runner

from resolveflow.support.embeddings import SupportEmbeddings
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import read
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


class OfflineProvider(TokenizedScript):
    def prepare_request(self, *, system, messages, max_output_tokens):
        return {'model': 'scripted-offline', 'max_tokens': max_output_tokens, 'messages': [
            {'role': m.role, 'content': ''.join(b.text for b in m.get_content_blocks() if hasattr(b, 'text'))}
            for m in messages]}


def test_autonomous_driver_exports_two_actual_turns_and_drops_only_its_own_schema(
    postgres_dsn, monkeypatch, tmp_path,
):
    case = runner.load_cases()[-1]
    case['turns'] = case['turns'][:2]
    manifest = tmp_path / 'manifest.json'
    runner.write_new(manifest, {'offline': True})
    monkeypatch.setattr(runner, 'PLAN', manifest)
    monkeypatch.setattr(runner, 'load_plan', lambda: ({'version': 'scripted-experience-test'}, [case]))
    monkeypatch.setattr(runner, 'DSN', postgres_dsn)
    monkeypatch.setenv('RESOLVEFLOW_MODEL_API_KEY', 'scripted-offline-test')
    monkeypatch.setattr(SupportEmbeddings, 'prewarm', lambda self, path: 0)
    monkeypatch.setattr(SupportEmbeddings, 'get', lambda self, path: None)
    scripts = [
        parts(part('trace', '可先请商家核查。', status='NEEDS_MERCHANT'), tasks=[task('trace')],
              dialogue_events=[group('ADD', ['trace'], case['turns'][0]['text'])]),
        [read('get_support_guide'),
         parts(part('trace', '签收问题稍后继续。', status='SUSPENDED'),
               part('entry', '正式申请入口为我的售后。', ['O1']),
              tasks=[task('trace', status='SUSPENDED'), task('entry', 'APPLICATION')],
              dialogue_events=[group('PAUSE', ['trace'], case['turns'][1]['text']),
                               group('ADD', ['entry'], case['turns'][1]['text'])])],
    ]
    models = []

    def model_factory(self):
        if self.model_factory:
            return self.model_factory()
        script = scripts[len(models)]
        model = OfflineProvider(script=script if isinstance(script, list) else [script], mode='live')
        models.append(model)
        return model

    monkeypatch.setattr(SupportRuntime, '_model', model_factory)
    output, usage = tmp_path / 'result.json', tmp_path / 'usage.json'
    runner.evaluate(output, usage)
    report = runner.read_json(output)
    assert report['state'] == 'FINISHED' and len(report['rows']) == 2
    assert all(row['variant'] == 'agent' and row['result']['status'] == 'SUCCEEDED' for row in report['rows'])
    assert len(report['all_runs']) == 2 and len(report['all_calls']) == 4
    assert report['isolated_schema_dropped'] and report['public_before'] == report['public_after']
    previous = report['rows'][1]['input']['context']['previous_tasks']
    assert previous['tasks'][0]['id'] == 'trace' and previous['tasks'][0]['status'] == 'NEEDS_MERCHANT'
    assert [m.calls for m in models] == [1, 2] and runner.read_json(usage)['used'] == 3
    assert all(row['models'][0]['body']['model'] == 'scripted-offline' for row in report['rows'])
    import pytest

    with pytest.raises(FileExistsError):
        runner.evaluate(output, usage)
    assert len(models) == 2
