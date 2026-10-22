from copy import deepcopy

import pytest
from scripts import customer_agent_experience_v2 as runner

from tests.unit.test_customer_agent_eval_v2 import completed


def test_new_freeze_keeps_old_evidence_and_covers_current_sources(tmp_path):
    old = runner.prior.PLAN.read_bytes()
    path = tmp_path / 'manifest.json'
    runner.freeze(path)
    plan, cases = runner.load_plan(path)
    assert plan['version'] == runner.VERSION and plan['not_resume_metrics']
    assert len(cases) == 5 and sum(len(c['turns']) for c in cases) == 8
    assert 'agent/src/resolveflow/support/completion.py' in plan['files']
    plan['files']['agent/src/resolveflow/support/activity.py'] = '0' * 64
    bad = tmp_path / 'bad.json'
    runner.prior.write_new(bad, plan)
    with pytest.raises(ValueError, match='frozen source changed'):
        runner.load_plan(bad)
    assert runner.prior.PLAN.read_bytes() == old


def test_fresh_identity_and_actual_failed_history_are_retained():
    case = runner.load_cases()[-1]
    first, _ = runner.prepare_turn(case, 0, [])
    old, _ = runner.prior.prepare_turn(case, 0, [])
    assert first.run_id != old.run_id and first.conversation_id != old.conversation_id
    success = completed(first, text='实际答复')
    second, _ = runner.prepare_turn(case, 1, [success])
    failed = {**completed(second), 'status': 'FAILED', 'answer': None, 'reason': 'INVALID_DECISION'}
    third, archive = runner.prepare_turn(case, 2, [success, failed])
    assert third.context['previous_customer_memory'] == success['answer']['customer_memory']
    assert [m['text'] for m in archive if m['author'] == 'ASSISTANT'] == ['实际答复']
    foreign = deepcopy(success)
    foreign['answer']['customer_memory']['line_id'] = 'foreign'
    with pytest.raises(ValueError, match='memory scope'):
        runner.prepare_turn(case, 1, [foreign])


def test_scoped_executor_binding_is_restored_even_on_failure(monkeypatch, tmp_path):
    old = runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn

    def fail(output, usage):
        assert runner.prior.PLAN == runner.PLAN
        assert runner.prior.load_plan is runner.load_plan and runner.prior.prepare_turn is runner.prepare_turn
        raise RuntimeError('scripted interruption')

    monkeypatch.setattr(runner.prior, 'evaluate', fail)
    with pytest.raises(RuntimeError, match='scripted interruption'):
        runner.evaluate(tmp_path / 'result.json', tmp_path / 'usage.json')
    assert (runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn) == old
