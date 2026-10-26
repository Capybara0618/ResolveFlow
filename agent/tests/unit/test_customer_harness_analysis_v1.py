"""Do not convert missing reviews, unknown usage or failed recovery into positive metrics."""

import pytest
from scripts.analyze_customer_harness_live_v1 import cost, quality, reduction, reviewed_cost


def model(sent=True, *, known=True):
    return {'send_reserved': sent, 'usage_kind': 'PROVIDER' if known else 'UNKNOWN',
            'usage': {'input_tokens': 100, 'output_tokens': 20} if known else None}


def test_unknown_usage_is_not_zero_and_unsent_reservations_are_separate():
    assert cost([model(), model(known=False)]) == {
        'request_reservations': 2, 'unknown_usage_requests': 1, 'known_input_tokens': 100,
        'known_output_tokens': 20, 'input_tokens': None, 'output_tokens': None}
    assert cost([model(False, known=False)])['request_reservations'] == 0


def test_quality_requires_explicit_source_evidence_and_no_silent_unreviewed_pass():
    with pytest.raises(ValueError, match='source review'):
        quality([{'pass': None, 'reason': None, 'evidence': None}])
    with pytest.raises(ValueError, match='source review'):
        quality([{'pass': True, 'reason': 'good', 'evidence': None}])
    assert quality([{'pass': False, 'reason': 'missing answer', 'evidence': ['runtime#/row0']},
                    {'pass': True, 'reason': 'grounded answer', 'evidence': ['runtime#/row1']}]) == {
                        'passed': 1, 'total': 2, 'rate': 0.5}


def test_cost_reduction_only_compares_both_reviewed_successes():
    rows = [{'case_id': 'a', 'variant': 'raw', 'checkpoint': 1, 'models': [model(), model()]},
            {'case_id': 'a', 'variant': 'layered', 'checkpoint': 1, 'models': [model()]},
            {'case_id': 'b', 'variant': 'raw', 'checkpoint': 1, 'models': [model(), model()]},
            {'case_id': 'b', 'variant': 'layered', 'checkpoint': 1, 'models': []}]
    labels = [{**{k: r[k] for k in ('case_id', 'variant', 'checkpoint')},
               'pass': r['case_id'] != 'b' or r['variant'] == 'raw', 'reason': 'review', 'evidence': ['source']}
              for r in rows]
    result = reviewed_cost(rows, labels)
    assert result['paired_checkpoints'] == 1
    assert result['raw']['input_tokens'] == 200 and result['layered']['input_tokens'] == 100
    assert result['input_token_reduction'] == 0.5


def test_undefined_denominator_does_not_become_zero_percent():
    assert reduction(0, 0) is None
    assert reduction(100, None) is None
    assert reduction(100, 125) == -0.25
