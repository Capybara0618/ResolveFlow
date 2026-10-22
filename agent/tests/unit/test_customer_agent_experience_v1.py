from copy import deepcopy

import pytest
from scripts import customer_agent_experience_v1 as runner

from tests.unit.test_customer_agent_eval_v2 import completed


def test_experience_selection_keeps_original_questions_and_checks_frozen_sources(tmp_path):
    cases = runner.load_cases()
    assert len(cases) == 5 and sum(len(c['turns']) for c in cases) == 8
    assert [c['source_case'] for c in cases] == ['D01', 'D02', 'D06', 'D07', 'D13']
    old = (runner.ROOT / 'evals/customer-agent-read-first-v1/manifest.json').read_bytes()
    path = tmp_path / 'manifest.json'
    runner.freeze(path)
    plan, loaded = runner.load_plan(path)
    assert plan['not_resume_metrics'] is True and len(loaded) == 5
    plan['files']['agent/src/resolveflow/support/engine.py'] = '0' * 64
    changed = tmp_path / 'changed.json'
    runner.write_new(changed, plan)
    with pytest.raises(ValueError, match='frozen source changed'):
        runner.load_plan(changed)
    assert (runner.ROOT / 'evals/customer-agent-read-first-v1/manifest.json').read_bytes() == old


def test_actual_failed_turn_stays_in_history_without_gold_answer_or_foreign_memory():
    case = runner.load_cases()[-1]
    one, _ = runner.prepare_turn(case, 0, [])
    actual = completed(one, text='实际助手答复')
    two, _ = runner.prepare_turn(case, 1, [actual])
    failed = {**completed(two), 'status': 'FAILED', 'answer': None, 'reason': 'INVALID_DECISION'}
    three, archive = runner.prepare_turn(case, 2, [actual, failed])
    assert three.context['previous_customer_memory'] == actual['answer']['customer_memory']
    assert [m['text'] for m in archive if m['author'] == 'ASSISTANT'] == ['实际助手答复']
    original, _ = runner.baseline.prepare_turn(runner.baseline.load_cases()[12], 0, [], 'agent')
    assert original.run_id != one.run_id and original.conversation_id != one.conversation_id
    foreign = deepcopy(actual)
    foreign['answer']['customer_memory']['line_id'] = 'foreign'
    with pytest.raises(ValueError, match='memory scope'):
        runner.prepare_turn(case, 1, [foreign])
