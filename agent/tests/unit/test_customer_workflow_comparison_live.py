"""Dispatch, history isolation and budget stops are tested without provider calls."""

import json
from copy import deepcopy

import pytest
from scripts import customer_workflow_comparison_live as driver
from scripts.customer_workflow_comparison_prepare import DATA, digest, load_dataset, runtime_rows


def test_matrix_has_own_history_and_no_gold_in_model_packets():
    cases = driver.cases()
    seen = []
    def execute(case, variant, index, completed):
        packet, _ = driver.plain_turn(case, variant, index, completed)
        seen.append((case['id'], variant, index, deepcopy(packet)))
        return {**driver.empty_row(case, variant, index), 'status': 'SUCCEEDED',
            'answer': {'text': variant + ' actual answer'}, 'elapsed_ms': 1}
    report = {'version': load_dataset()['version'], 'dataset_sha256': digest(DATA), 'state': 'RUNNING', 'rows': []}
    driver.run_matrix(cases, report, execute, lambda: None)
    assert report['state'] == 'FINISHED' and len(runtime_rows(load_dataset(), report, digest(DATA))) == 100
    assert [v for _, v, i, _ in seen[:2]] == ['agent', 'basic_workflow']
    for _, variant, index, packet in seen:
        serialized = json.dumps(packet, ensure_ascii=False, default=str)
        assert 'business_expectations' not in serialized and 'expected_artifact' not in serialized
        assert 'previous_tasks' not in serialized and 'customer_memory' not in serialized
        if index:
            assert variant + ' actual answer' in serialized
            assert ('basic_workflow' if variant == 'agent' else 'agent') + ' actual answer' not in serialized


def test_global_stop_keeps_completed_costs_and_fills_unrun_denominator():
    cases, attempts = driver.cases(), []
    def execute(case, variant, index, completed):
        attempts.append(variant)
        return {**driver.empty_row(case, variant, index), 'status': 'BUDGET_EXHAUSTED', 'models': [
            {'provider_sent': True, 'usage': None}], 'elapsed_ms': 12, 'reason': 'EVALUATION_ALLOWANCE_EXHAUSTED'}
    report = {'rows': []}
    driver.run_matrix(cases, report, execute, lambda: None)
    assert len(attempts) == 1 and len(report['rows']) == 100
    assert report['rows'][0]['models'] and sum(r['status'] == 'NOT_RUN' for r in report['rows']) == 99
    assert all(r['elapsed_ms'] is None for r in report['rows'][1:])


def test_plain_history_keeps_actual_drafts_and_does_not_invent_failed_answers():
    case = next(c for c in driver.cases() if len(c['turns']) >= 2)
    row = {**driver.empty_row(case, 'basic_workflow', 0), 'status': 'SUCCEEDED',
        'answer': {'text': '原回答', 'handoff_summary': '原草稿'}}
    packet, _ = driver.plain_turn(case, 'basic_workflow', 1, [row])
    assert '原草稿' in packet['context']['history'][-2]['text']
    row.update(status='FAILED', answer=None)
    packet, _ = driver.plain_turn(case, 'basic_workflow', 1, [row])
    assert all(m['author'] == 'CUSTOMER' for m in packet['context']['history'])
    with pytest.raises(ValueError, match='prefix'):
        driver.plain_turn(case, 'basic_workflow', 1, [])


def test_execute_cannot_be_implicit_and_outputs_cannot_be_overwritten(tmp_path):
    with pytest.raises(SystemExit):
        driver.main(['execute', '--output', str(tmp_path / 'out.json')])
    output = tmp_path / 'out.json'
    driver.write_new(output, {'state': 'original'})
    with pytest.raises(FileExistsError):
        driver.write_new(output, {'state': 'new'})
    assert json.loads(output.read_text()) == {'state': 'original'}


def test_freeze_binds_source_and_parameters_and_cannot_overwrite(tmp_path):
    path = tmp_path / 'manifest.json'
    driver.freeze(path)
    assert driver.load_plan(path)['turns'] == 100
    with pytest.raises(FileExistsError):
        driver.freeze(path)
    changed = json.loads(path.read_text(encoding='utf-8'))
    changed['parameters']['temperature'] = 1
    path.write_text(json.dumps(changed), encoding='utf-8')
    with pytest.raises(ValueError, match='frozen'):
        driver.load_plan(path)
