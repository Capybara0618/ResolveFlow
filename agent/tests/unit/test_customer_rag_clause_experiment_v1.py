import pytest
from scripts.customer_rag_clause_experiment_v1 import summarize
from scripts.evaluation.customer_clause_retrieval_v1 import VARIANTS


def rows():
    return [{'id': 'Q', 'variant': v, 'repeat': r, 'category': 'compound', 'elapsed_ms': float(r),
        'packet': {'body_sha256': 'h', 'body_tokens': 20, 'selected_chunks': ['P']},
        'quality': {str(k): {'complete': True, 'any_required': True} for k in [1, 3, 5]}}
        for v in VARIANTS for r in [1, 2, 3]]


def test_unique_quality_denominator_and_actual_parent_count():
    summary = summarize(rows(), [{'id': 'Q', 'answerability': 'ANSWERABLE', 'category': 'compound'}])
    for result in summary.values():
        assert result['answerable_questions'] == 1
        assert result['complete_at_3_count'] == 1
        assert result['timed_requests'] == 3
        assert result['mean_parent_count'] == 1


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'nan'])
def test_broken_measurement_matrix_rejected(bad):
    values = rows()
    if bad == 'missing':
        values.pop()
    elif bad == 'duplicate':
        values.append(values[0])
    else:
        values[0]['elapsed_ms'] = float('nan')
    with pytest.raises(ValueError):
        summarize(values, [{'id': 'Q', 'answerability': 'ANSWERABLE', 'category': 'compound'}])
