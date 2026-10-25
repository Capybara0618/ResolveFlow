"""A driver interruption cannot silently reexecute paid answers or restart half a conversation."""

from copy import deepcopy

import pytest
from scripts import customer_workflow_comparison_continue as continuation
from scripts import customer_workflow_comparison_live as driver
from scripts.customer_workflow_comparison_prepare import DATA, digest


def fixture():
    rows = continuation.matrix()[:55]
    for row in rows:
        row.update(status='SUCCEEDED', answer={'text': '实际已发布回答'}, elapsed_ms=1,
            models=[{'state': 'COMPLETE', 'provider_sent': True, 'usage': None}])
    return {'version': driver.VERSION, 'dataset_sha256': digest(DATA), 'state': 'ERROR',
        'error_type': 'PermissionError', 'isolated_schema_dropped': True, 'rows': rows,
        'usage_before': 10, 'usage_after': 65, 'max_new_provider_requests': 400}


def test_saved_answers_are_exactly_reused_and_only_45_unexecuted_turns_call_executor():
    prefix, calls = fixture(), []
    assert continuation.validate_prefix(prefix, 65) == 345
    before = deepcopy(prefix)
    def execute(case, variant, index, completed):
        calls.append((case['id'], variant, index))
        return {**driver.empty_row(case, variant, index), 'status': 'SUCCEEDED', 'answer': {'text': '新回答'}}
    report = {'rows': []}
    continuation.continuation_matrix(driver.run_matrix, prefix)(driver.cases(), report, execute, lambda: None)
    assert len(calls) == 45 and len(report['rows']) == 100
    assert report['rows'][:55] == prefix['rows'] and prefix == before
    assert calls[0] == ('Q16', 'agent', 0)


@pytest.mark.parametrize('change', ['unfinished', 'identity', 'ledger', 'mid_conversation', 'inflight'])
def test_invalid_or_ambiguous_prefix_requires_explicit_audit(change):
    prefix, used = fixture(), 65
    if change == 'unfinished':
        prefix['rows'][-1]['status'] = 'NOT_RUN'
    if change == 'identity':
        prefix['rows'][1]['run_id'] = 'wrong'
    if change == 'ledger':
        used += 1
    if change == 'mid_conversation':
        prefix['rows'].pop()
        prefix['usage_after'] -= 1
        used -= 1
    if change == 'inflight':
        prefix['rows'][-1]['models'][0]['state'] = 'STARTED'
    with pytest.raises(ValueError):
        continuation.validate_prefix(prefix, used)
