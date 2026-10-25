import copy

import pytest
from scripts.customer_rag_dataset_v3 import DATA, read
from scripts.evaluation.customer_clause_retrieval_v1 import build_clauses, project_parents
from scripts.evaluation.customer_policy_benchmark_v3 import covers


def test_clause_originals_and_all_gold_spans_survive():
    parents = read(DATA / 'chunks.json')['chunks']
    children = build_clauses(parents)
    index = {p['id']: p for p in parents}
    for child in children:
        assert child['parent_ids']
        for pid in child['parent_ids']:
            parent = index[pid]
            assert child['subject'] == parent['subject']
            assert all(covers(parent['fragments'], p) for p in child['fragments'])
    pieces = [p for c in children for p in c['fragments']]
    for query in read(DATA / 'queries.json')['queries']:
        assert all(covers(pieces, a) for a in query['required_evidence']), query['id']


def fixtures():
    parents = {name: {'id': name, 'source_id': 's', 'subject': 'EXTERNAL:S', 'raw_sha256': 'v'}
        for name in ['A', 'B', 'C']}
    children = [({'id': str(i), 'source_id': 's', 'subject': 'EXTERNAL:S',
        'raw_sha256': 'v', 'parent_ids': [name]}, 1 - i / 10) for i, name in enumerate(['A', 'A', 'A', 'B', 'C'])]
    return parents, children


def test_grouping_fills_distinct_parent_slots_and_does_not_invent_content():
    parents, children = fixtures()
    naive = project_parents(children, parents, naive=True)
    grouped = project_parents(children, parents, naive=False)
    assert [p['id'] for p, _ in naive] == ['A']
    assert [p['id'] for p, _ in grouped[:3]] == ['A', 'B', 'C']
    assert all(p is parents[p['id']] for p, _ in grouped)


@pytest.mark.parametrize('bad', ['unknown_parent', 'cross_subject', 'cross_source', 'cross_version'])
def test_invalid_parent_binding_is_rejected(bad):
    parents, children = fixtures()
    children = copy.deepcopy(children)
    child = children[0][0]
    if bad == 'unknown_parent':
        child['parent_ids'] = ['missing']
    else:
        child[{'cross_subject': 'subject', 'cross_source': 'source_id', 'cross_version': 'raw_sha256'}[bad]] = 'other'
    with pytest.raises(ValueError, match='parent'):
        project_parents(children, parents, naive=False)
