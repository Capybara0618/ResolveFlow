from copy import deepcopy

import pytest
from scripts import customer_agent_correction_v1 as runner

from tests.unit.test_customer_agent_eval_v2 import completed


def test_new_six_turns_freeze_without_exposing_criteria_or_old_identity(tmp_path):
    cases = runner.load_cases()
    assert [len(c['turns']) for c in cases] == [4, 1, 1]
    ids = set()
    for case in cases:
        req, _ = runner.prepare_turn(case, 0, [])
        assert req.conversation_id not in ids
        ids.add(req.conversation_id)
        assert 'criteria' not in str(req.context) and 'staged-v1' not in str(req.context)
    path = tmp_path / 'manifest.json'
    runner.freeze(path)
    plan, _ = runner.load_plan(path)
    assert plan['turns'] == 6
    plan['files']['agent/src/resolveflow/support/memory.py'] = '0' * 64
    invalid = tmp_path / 'invalid.json'
    runner.prior.write_new(invalid, plan)
    with pytest.raises(ValueError, match='frozen source changed'):
        runner.load_plan(invalid)


def test_failed_accepted_state_is_inherited_without_fabricated_answer():
    case = runner.load_cases()[0]
    req, _ = runner.prepare_turn(case, 0, [])
    result = completed(req)
    result.update(status='FAILED', answer=None, conversation_update={
        'version': 'support-state-v1', **{k: getattr(req, k) for k in (
            'run_id', 'conversation_id', 'input_version', 'merchant_id', 'customer_id', 'line_id')},
        'task_state': {'tasks': [{'id': 'trace', 'intent': 'LOGISTICS', 'request': '运输',
                                'status': 'PENDING', 'evidence_refs': []}]},
        'customer_memory': completed(req)['answer']['customer_memory']})
    later, archive = runner.prepare_turn(case, 1, [result])
    assert later.context['previous_customer_memory'] == result['conversation_update']['customer_memory']
    assert not any(m['author'] == 'ASSISTANT' for m in archive)
    bad = deepcopy(result)
    bad['conversation_update']['line_id'] = 'foreign'
    with pytest.raises(ValueError, match='scope'):
        runner.prepare_turn(case, 1, [bad])


def test_executor_restores_bindings_on_failure(monkeypatch, tmp_path):
    from resolveflow.support import service

    before = runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn, service.SupportRuntime

    def fail(*args):
        assert runner.prior.PLAN == runner.PLAN
        raise RuntimeError('local interruption')

    monkeypatch.setattr(runner.prior, 'evaluate', fail)
    with pytest.raises(RuntimeError):
        runner.evaluate(tmp_path / 'result.json', tmp_path / 'usage.json')
    assert before == (runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn, service.SupportRuntime)
