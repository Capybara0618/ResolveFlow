import pytest
from scripts.analyze_customer_rag_development_v3 import paired_delta, selected_queries


def test_focus_filters_acceptance_and_does_not_inspect_its_ranks():
    development = {'id': 'D', 'split': 'development'}
    assert selected_queries({'queries': [development, {'id': 'A', 'split': 'acceptance'}]}) == [development]


def test_net_gain_keeps_regressions_and_unique_denominator():
    first = {}
    for identity, old, new in [('Q1', False, True), ('Q2', True, False), ('Q3', False, True)]:
        for variant, value in [('old', old), ('new', new)]:
            first[(identity, variant)] = {'quality': {'3': {'complete': value}}}
    delta = paired_delta(first, ['Q1', 'Q2', 'Q3'], 'old', 'new')
    assert delta['gained'] == ['Q1', 'Q3']
    assert delta['regressed'] == ['Q2']
    assert delta['net_count'] == 1
    assert delta['percentage_point_change'] == pytest.approx(100 / 3)
