from copy import deepcopy

import pytest
from scripts import customer_agent_experience_v3 as runner

from tests.unit.test_customer_agent_eval_v2 import completed


def test_three_conversations_six_turns_keep_original_inputs_and_freeze_sources(tmp_path):
    old = runner.prior.read_json(runner.OLD_DIRECTORY / 'scenarios.json')['cases']
    selected = runner.load_cases()
    assert [c['id'] for c in selected] == ['U05', 'U02', 'U03']
    assert sum(len(c['turns']) for c in selected) == 6
    for case in selected:
        assert case['turns'] == next(c for c in old if c['id'] == case['id'])['turns']
    path = tmp_path / 'manifest.json'
    runner.freeze(path)
    plan, _ = runner.load_plan(path)
    assert plan['version'] == runner.VERSION and plan['turns'] == 6
    assert 'agent/src/resolveflow/support/dialogue.py' in plan['files']
    assert 'reports/customer-agent-experience-v2/runtime-results.json' in plan['files']
    plan['files']['agent/src/resolveflow/support/context.py'] = '0' * 64
    bad = tmp_path / 'bad.json'
    runner.prior.write_new(bad, plan)
    with pytest.raises(ValueError, match='frozen source changed'):
        runner.load_plan(bad)


def test_new_identities_keep_actual_answered_lifecycle_and_failed_prefix():
    case = runner.load_cases()[0]
    first, _ = runner.prepare_turn(case, 0, [])
    old, _ = runner.prior.prepare_turn(case, 0, [])
    assert first.run_id != old.run_id and first.conversation_id != old.conversation_id
    success = completed(first, text='实际首轮答复')
    success['answer']['task_state']['tasks'] = [
        {'id': 'trace', 'intent': 'LOGISTICS', 'request': '签收调查', 'status': 'ANSWERED', 'lifecycle': 'OPEN'}]
    second, _ = runner.prepare_turn(case, 1, [success])
    assert second.context['previous_tasks']['tasks'][0]['lifecycle'] == 'OPEN'
    failed = {**completed(second), 'status': 'FAILED', 'answer': None, 'reason': 'INVALID_DECISION'}
    third, archive = runner.prepare_turn(case, 2, [success, failed])
    assert third.context['previous_customer_memory'] == success['answer']['customer_memory']
    assert [m['text'] for m in archive if m['author'] == 'ASSISTANT'] == ['实际首轮答复']
    foreign = deepcopy(success)
    foreign['answer']['customer_memory']['line_id'] = 'foreign'
    with pytest.raises(ValueError, match='memory scope'):
        runner.prepare_turn(case, 1, [foreign])


def test_executor_binding_restores_after_exception(monkeypatch, tmp_path):
    old = runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn

    def fail(output, usage):
        assert runner.prior.PLAN == runner.PLAN
        assert runner.prior.load_plan is runner.load_plan
        raise RuntimeError('scripted interruption')

    monkeypatch.setattr(runner.prior, 'evaluate', fail)
    with pytest.raises(RuntimeError, match='scripted interruption'):
        runner.evaluate(tmp_path / 'result.json', tmp_path / 'usage.json')
    assert (runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn) == old
