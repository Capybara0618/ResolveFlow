import copy
import json

import pytest
from scripts.agent_rag_source_review import object_hash
from scripts.evaluation.handoff_comparison import DIMENSIONS, ROOT, audit, project, semantic_review


def fixture():
    case = {'description': 'customer claim'}
    entry = {'id': 'sample', 'completed': True, 'model_calls': 2, 'joint_correct': False,
             'action_correct': True}
    review = {'origin': 'CODEX_REVIEW', 'blind': False, 'report_sha256': 'bound', 'reviewed_at': '2026-10-06',
              'cases': [{'id': 'sample', 'entry_sha256': object_hash(entry), 'case_sha256': object_hash(case),
                         'notes': 'Check actual material, not assumed final action.',
                         **dict.fromkeys(DIMENSIONS, 'PASS')}]}
    return case, entry, review


def test_projection_keeps_failed_entries_and_original_report():
    _, entry, _ = fixture()
    before = {'results': [entry, {**entry, 'id': 'other'}], 'summary': {'n': 2}}
    original = copy.deepcopy(before)
    projected = project(before, ['sample'])
    assert projected['results'] == [entry]
    assert projected['summary']['joint_correct'] == 0
    assert before == original


@pytest.mark.parametrize('ids', [[], ['sample', 'sample'], ['missing']])
def test_projection_rejects_incomplete_selection(ids):
    _, entry, _ = fixture()
    with pytest.raises(ValueError):
        project({'results': [entry]}, ids)


def test_review_accepts_source_bound_codex_labels():
    case, entry, review = fixture()
    assert semantic_review(review, [entry], {'sample': case}, 'bound')['responsibility'] == {'PASS': 1}


@pytest.mark.parametrize('change', ['wrong_hash', 'missing', 'blind', 'edited_entry', 'invalid_value', 'incomplete'])
def test_review_rejects_detached_or_promoted_labels(change):
    case, entry, review = fixture()
    if change == 'wrong_hash':
        review['report_sha256'] = 'different'
    elif change == 'missing':
        review['cases'] = []
    elif change == 'blind':
        review['blind'] = True
    elif change == 'edited_entry':
        entry['model_calls'] = 9
    elif change == 'invalid_value':
        review['cases'][0]['responsibility'] = 'PENDING'
    else:
        entry['completed'] = False
        review['cases'][0]['entry_sha256'] = object_hash(entry)
    with pytest.raises(ValueError):
        semantic_review(review, [entry], {'sample': case}, 'bound')


def saved_fixture():
    # Saved synthetic case used as an offline protocol fixture; these PASS labels are not a quality review.
    baseline = json.loads((ROOT / 'reports/rag-delivery/agent-live.json').read_text(encoding='utf-8'))
    candidate = project(baseline, ['A01A'])
    case = next(c for c in json.loads((ROOT / 'evals/calibrated-v3/agent/cases.json').read_text(encoding='utf-8'))
                if c['id'] == 'A01A')
    entry = candidate['results'][0]
    labels = {'origin': 'CODEX_REVIEW', 'blind': False, 'report_sha256': 'test-only', 'reviewed_at': 'test-only',
              'cases': [{'id': 'A01A', 'entry_sha256': object_hash(entry), 'case_sha256': object_hash(case),
                         'notes': 'Protocol test fixture, not empirical semantic judgment.',
                         **dict.fromkeys(DIMENSIONS, 'PASS')}]}
    cohort = {'inputs': {}, 'dataset': 'evals/calibrated-v3', 'case_ids': ['A01A'],
              'code_commit': candidate['code_commit']}
    return cohort, candidate, baseline, labels


def test_audit_saved_fixture_preserves_original_score_and_no_model_calls():
    cohort, candidate, baseline, labels = saved_fixture()
    output = audit(cohort, candidate, baseline, labels, 'test-only')
    assert output['comparison']['n'] == 1
    assert output['comparison']['before'] == output['comparison']['after'] == 1
    assert output['new_model_calls'] == 0


@pytest.mark.parametrize('change', ['cohort', 'commit', 'budget', 'score', 'source'])
def test_full_audit_rejects_saved_report_changes(change):
    cohort, candidate, baseline, labels = saved_fixture()
    if change == 'cohort':
        cohort['case_ids'] = ['A01A', 'A01B']
    elif change == 'commit':
        candidate['code_commit'] = 'different'
    elif change == 'budget':
        candidate['evaluation_config']['model_calls'] = 6
    elif change == 'score':
        candidate['results'][0]['joint_correct'] = False
    else:
        observation = next(o for o in candidate['results'][0]['observations'] if o['tool_name'] == 'search_policy')
        observation['result']['hits'][0]['text'] = 'edited'
    with pytest.raises(ValueError):
        audit(cohort, candidate, baseline, labels, 'test-only')
