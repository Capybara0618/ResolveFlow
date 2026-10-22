from copy import deepcopy

import pytest
from scripts import customer_agent_state_live_v1 as runner

from tests.unit.test_customer_agent_eval_v2 import completed


def test_cases_freeze_same_questions_and_add_only_explicit_money_question(tmp_path):
    cases = runner.load_cases()
    assert len(cases) == 8 and sum(len(c['turns']) for c in cases) == 14
    old = runner.base.load_cases()
    assert cases[:6] == old
    for c in cases[6:]:
        assert c['source_id'] == 'U06' and c['turns'][0]['criteria']
    conversations = set()
    for c in cases:
        req, _ = runner.prepare_turn(c, 0, [])
        assert req.conversation_id not in conversations
        conversations.add(req.conversation_id)
        assert 'criteria' not in str(req.context) and c['architecture'] not in str(req.context)
    manifest = tmp_path / 'manifest.json'
    runner.freeze(manifest)
    plan, _ = runner.load_plan(manifest)
    assert plan['turns'] == 14 and plan['files']['agent/src/resolveflow/support/grounding.py']
    plan['files']['agent/src/resolveflow/support/engine.py'] = '0' * 64
    bad = tmp_path / 'bad.json'
    runner.prior.write_new(bad, plan)
    with pytest.raises(ValueError, match='frozen source changed'):
        runner.load_plan(bad)


def test_accepted_state_from_failed_answer_is_carried_without_fabricated_assistant_history():
    one, two = runner.load_cases()[:2]
    req, _ = runner.prepare_turn(one, 0, [])
    first = completed(req)
    second_req, _ = runner.prepare_turn(one, 1, [first])
    update = {'version': 'support-state-v1', **{k: getattr(second_req, k) for k in [
        'run_id', 'conversation_id', 'input_version', 'merchant_id', 'customer_id', 'line_id']},
        'task_state': {'origin': 'MODEL', 'tasks': [{'id': 'trace', 'intent': 'LOGISTICS', 'request': '调查',
            'status': 'SUSPENDED', 'lifecycle': 'PAUSED', 'evidence_refs': [], 'response_excerpt': None}]},
        'customer_memory': {**first['answer']['customer_memory'], 'input_version': second_req.input_version},
        'dialogue_state': {'events': []}, 'memory_warnings': []}
    failed = {**completed(second_req), 'status': 'FAILED', 'answer': None,
              'reason': 'INVALID_DECISION', 'conversation_update': update}
    third, history = runner.prepare_turn(one, 2, [first, failed])
    assert third.context['previous_tasks']['input_version'] == second_req.input_version
    assert third.context['previous_tasks']['tasks'][0]['lifecycle'] == 'PAUSED'
    assert third.context['previous_customer_memory']['input_version'] == second_req.input_version
    assert len([m for m in history if m['author'] == 'ASSISTANT']) == 1
    with pytest.raises(ValueError, match='identity'):
        runner.prepare_turn(two, 1, [deepcopy(first)])
    bad = deepcopy(failed)
    bad['conversation_update']['line_id'] = 'foreign'
    with pytest.raises(ValueError, match='scope'):
        runner.prepare_turn(one, 2, [first, bad])


def test_executor_bindings_restore_on_exception(monkeypatch, tmp_path):
    from resolveflow.support import service

    old = runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn, service.SupportRuntime

    def fail(*args):
        assert runner.prior.PLAN == runner.PLAN and service.SupportRuntime is not old[3]
        raise RuntimeError('offline interruption')

    monkeypatch.setattr(runner.prior, 'evaluate', fail)
    with pytest.raises(RuntimeError):
        runner.evaluate(tmp_path / 'result.json', tmp_path / 'usage.json')
    assert (runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn, service.SupportRuntime) == old
