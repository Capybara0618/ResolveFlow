import copy

import pytest
from scripts.customer_rag_dataset_v3 import DATA, read
from scripts.customer_rag_questions_v3 import validate_questions


def dataset():
    return read(DATA / 'queries.json'), read(DATA / 'corpus.json')


def test_source_bound_cases_and_split_counts():
    data, corpus = dataset()
    summary = validate_questions(data, corpus)
    assert summary['questions'] == 100
    assert summary['development'] == 40
    assert summary['acceptance'] == 60
    assert summary['answerable_acceptance'] == 48
    assert summary['unanswerable'] == 20
    assert summary['positive_sources'] == 15


@pytest.mark.parametrize('change', ['quote', 'scope', 'split', 'negative', 'duplicate'])
def test_bad_gold_scope_leak_and_matrix_rejected(change):
    data, corpus = dataset()
    data = copy.deepcopy(data)
    if change == 'quote':
        data['queries'][0]['required_evidence'][0]['quote'] += '伪造'
    elif change == 'scope':
        data['queries'][0]['scope'] = data['queries'][0]['scope'][:1]
    elif change == 'split':
        data['queries'][0]['split'] = 'acceptance'
    elif change == 'negative':
        data['queries'][-1]['missing_reason'] = None
    else:
        data['queries'][1]['id'] = data['queries'][0]['id']
    with pytest.raises(ValueError):
        validate_questions(data, corpus)
