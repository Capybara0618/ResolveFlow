import copy

import pytest
from scripts.customer_rag_benchmark_v3 import summarize
from scripts.evaluation.customer_policy_benchmark_v3 import VARIANTS


def rows():
    return [{'id': 'Q', 'variant': v, 'repeat': r, 'category': 'ordinary', 'elapsed_ms': r,
        'packet': {'selected_chunks': ['C'], 'body_sha256': 'h', 'body_tokens': 10},
        'quality': {str(k): {'complete': True, 'any_required': True} for k in [1, 3, 5]}}
        for v in VARIANTS for r in [1, 2, 3]]


def test_denominator_not_tripled_and_mean_not_median():
    queries = [{'id': 'Q', 'answerability': 'ANSWERABLE', 'category': 'ordinary'}]
    values = rows()
    for row in values:
        row['elapsed_ms'] = [1., 2., 12.][row['repeat'] - 1]
    result = summarize(values, queries)
    for summary in result.values():
        assert summary['answerable_questions'] == 1
        assert summary['complete_at_3_rate'] == 1.
        assert summary['mean_ms'] == 5.
        assert summary['p50_ms'] == 2.
        assert summary['timed_requests'] == 3


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'nan', 'negative'])
def test_incomplete_or_invalid_measurements_fail(bad):
    values = copy.deepcopy(rows())
    if bad == 'missing':
        values.pop()
    elif bad == 'duplicate':
        values.append(values[0])
    else:
        values[0]['elapsed_ms'] = float('nan') if bad == 'nan' else -1
    with pytest.raises(ValueError):
        summarize(values, [{'id': 'Q', 'answerability': 'ANSWERABLE', 'category': 'ordinary'}])
