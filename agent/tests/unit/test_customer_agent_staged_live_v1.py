from copy import deepcopy

import pytest
from scripts import customer_agent_staged_live_v1 as runner

from tests.unit.test_customer_agent_eval_v2 import completed


def test_paired_cases_keep_questions_facts_and_bound_new_identities(tmp_path):
    cases = runner.load_cases()
    assert len(cases) == 6 and sum(len(c['turns']) for c in cases) == 12
    original = {c['id']: c for c in runner.base.load_cases()}
    seen = set()
    for case in cases:
        old = original[case['source_id']]
        assert case['turns'] == old['turns'] and case['snapshot'] == old['snapshot']
        first, _ = runner.prepare_turn(case, 0, [])
        assert first.conversation_id not in seen
        seen.add(first.conversation_id)
        assert case['architecture'] not in str(first.context)
        assert 'criteria' not in str(first.context)
    manifest = tmp_path / 'manifest.json'
    runner.freeze(manifest)
    plan, _ = runner.load_plan(manifest)
    assert plan['turns'] == 12 and plan['not_pure_decomposition_ablation']
    plan['files']['agent/src/resolveflow/support/stages.py'] = '0' * 64
    bad = tmp_path / 'bad.json'
    runner.prior.write_new(bad, plan)
    with pytest.raises(ValueError, match='frozen source changed'):
        runner.load_plan(bad)


def test_failed_prefix_and_actual_lifecycle_remain_architecture_local():
    cases = runner.load_cases()
    one, two = cases[0], cases[1]
    req, _ = runner.prepare_turn(one, 0, [])
    result = completed(req)
    result['answer']['task_state']['tasks'] = [
        {'id': 'trace', 'intent': 'LOGISTICS', 'request': '调查', 'status': 'ANSWERED', 'lifecycle': 'OPEN'}]
    next_req, _ = runner.prepare_turn(one, 1, [result])
    assert next_req.context['previous_tasks']['tasks'][0]['lifecycle'] == 'OPEN'
    failed = {**completed(next_req), 'status': 'FAILED', 'answer': None, 'reason': 'INVALID_DECISION'}
    third, archive = runner.prepare_turn(one, 2, [result, failed])
    assert third.context['previous_customer_memory'] == result['answer']['customer_memory']
    assert len([m for m in archive if m['author'] == 'ASSISTANT']) == 1
    with pytest.raises(ValueError, match='identity'):
        runner.prepare_turn(two, 1, [deepcopy(result)])


def test_temporary_bindings_restore_after_interruption(monkeypatch, tmp_path):
    from resolveflow.support import service

    old = runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn, service.SupportRuntime

    def fail(output, usage):
        assert runner.prior.PLAN == runner.PLAN
        assert service.SupportRuntime is not old[3]
        raise RuntimeError('scripted interruption')

    monkeypatch.setattr(runner.prior, 'evaluate', fail)
    with pytest.raises(RuntimeError, match='scripted interruption'):
        runner.evaluate(tmp_path / 'result.json', tmp_path / 'usage.json')
    assert (runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn, service.SupportRuntime) == old
