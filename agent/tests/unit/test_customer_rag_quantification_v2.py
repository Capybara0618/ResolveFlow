"""Positive lexical votes, fixed evidence budget and complete measurement denominator."""

from copy import deepcopy

import pytest
from scripts import customer_rag_quantification_v2 as experiment


def test_zero_lexical_hits_do_not_receive_votes_but_dense_has_no_threshold():
    dense = [({'id': 'dense'}, 0.)]
    lexical = [({'id': 'noise'}, 0.)]
    legacy = experiment.fuse_routes(dense, lexical, lexical, positive=False)
    actual = experiment.fuse_routes(dense, lexical, lexical, positive=True)
    assert legacy[0][0]['id'] == 'noise'
    assert [c['id'] for c, _ in actual] == ['dense']


def test_ranking_packet_never_receives_labels_or_expected_answer():
    query = {'id': 'R', 'query': '退款条件', 'subject': 'M', 'scope': [],
        'evidence_sets': [{'GOLD': True}], 'expected': 'GOLD', 'answerability': 'ANSWERABLE'}
    packet = experiment.public_query(query)
    assert set(packet) == {'query', 'subject', 'scope'}
    assert 'GOLD' not in str(packet)


def test_six_paths_keep_real_source_scope_and_packets_preserve_admitted_anchors():
    from scripts.customer_rag_evidence import assert_anchors
    queries, _, children, index = experiment.load_data()
    query = experiment.public_query(queries[0])
    class Encoder:
        def embed(self, values):
            return [children['chunks'][0]['embedding'] for _ in values]
    tokenizer = experiment.load_tokenizer()
    scope = {(x['source_id'], x['raw_sha256']) for x in query['scope']}
    for variant in experiment.VARIANTS:
        ranked, _ = experiment.retrieve(query, children, Encoder(), variant)
        assert all((c['source_id'], c['raw_sha256']) in scope and c['subject'] == query['subject'] for c, _ in ranked)
        anchors = [c for c, _ in ranked[:3]]
        packet = experiment.assemble(query, anchors, children, index, tokenizer, expand=variant.endswith('-parent'))
        assert packet['body_chars'] <= 8000 and packet['body_tokens'] <= 4096
        assert_anchors(packet, anchors)


def fixture():
    queries = [{'id': 'a', 'answerability': 'ANSWERABLE'}, {'id': 'n', 'answerability': 'NOT_IN_CORPUS'}]
    rows = [{'id': q['id'], 'variant': v, 'repeat': r, 'answerability': q['answerability'],
        'elapsed_ms': 10 + r, 'packet_complete': True if q['id'] == 'a' else None,
        'direct_complete_at_3': True if q['id'] == 'a' else None,
        'direct_complete_at_5': True if q['id'] == 'a' else None,
        'packet_complete_at_5': True if q['id'] == 'a' else None,
        'packet': {'body_tokens': 100, 'packet_sha256': q['id']+v}, 'hits': [q['id']]}
        for q in queries for v in experiment.VARIANTS for r in (1, 2, 3)]
    return rows, queries


def test_summary_uses_unique_answerable_questions_and_actual_mean_not_repeats_as_n():
    rows, queries = fixture()
    stats = experiment.summarize(rows, queries)
    assert all(s['answerable_questions'] == 1 and s['timed_requests'] == 6 for s in stats.values())
    assert all(s['packet_complete_count'] == 1 and s['mean_ms'] == 12 for s in stats.values())
    assert all(s['ranking_and_packet_stable'] for s in stats.values())


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'nonfinite'])
def test_summary_rejects_incomplete_or_invalid_measurement(change):
    rows, queries = fixture()
    if change == 'missing':
        rows.pop()
    elif change == 'duplicate':
        rows.append(deepcopy(rows[0]))
    else:
        rows[0]['elapsed_ms'] = float('nan')
    with pytest.raises(ValueError):
        experiment.summarize(rows, queries)
