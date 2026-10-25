import copy
from types import SimpleNamespace

import pytest
from scripts.customer_rag_dataset_v3 import DATA, read, sha
from scripts.evaluation.customer_policy_benchmark_v3 import (
    assemble,
    build_chunks,
    covers,
    public_query,
    retrieve,
)


class Tokenizer:
    def encode(self, text):
        return SimpleNamespace(ids=list(text))


def test_every_required_span_survives_shared_chunking():
    corpus, data = read(DATA / 'corpus.json'), read(DATA / 'queries.json')
    chunks = build_chunks(corpus)
    all_pieces = [p for chunk in chunks for p in chunk['fragments']]
    for query in data['queries']:
        assert all(covers(all_pieces, atom) for atom in query['required_evidence']), query['id']
    assert all(len(chunk['body']) <= 320 for chunk in chunks)
    assert all(chunk['content_sha256'] == sha(chunk['text'].encode()) for chunk in chunks)


def test_retriever_cannot_see_gold_and_scope_precedes_ranking():
    corpus, data = read(DATA / 'corpus.json'), read(DATA / 'queries.json')
    query = data['queries'][0]
    chunks = build_chunks(corpus)
    public = public_query(query)
    assert set(public) == {'query', 'subject', 'scope'}
    scoped = [c for c in chunks if c['subject'] == query['subject']]
    class Encoder:
        def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]
    vectors = {c['id']: [1.0, 0.0] for c in chunks}
    ranked, _ = retrieve(public, chunks, vectors, Encoder(), None, 'dense')
    assert all(c['subject'] == query['subject'] for c, _ in ranked)
    assert len(ranked) == min(20, len(scoped))
    bad = copy.deepcopy(public)
    bad['scope'] = bad['scope'][:1]
    with pytest.raises(ValueError, match='scope'):
        retrieve(bad, chunks, vectors, Encoder(), None, 'dense')


def test_packet_budget_deduplicates_source_spans_and_never_expands_parents():
    corpus = read(DATA / 'corpus.json')
    chunks = build_chunks(corpus)
    selected = [(chunks[0], 1.0), (chunks[0], .5)]
    packet = assemble(selected, Tokenizer(), k=3, max_tokens=4096)
    assert len(packet['selected_chunks']) == 1
    assert packet['body_chars'] <= 8000
    assert all(p['block_id'] in {f['block_id'] for f in chunks[0]['fragments']} for p in packet['pieces'])
    small = assemble(selected, Tokenizer(), k=3, max_tokens=1)
    assert small['body'] == ''
    assert small['skipped_chunks']


def test_rrf_uses_two_routes_and_ce_scores_actual_candidates():
    chunks = build_chunks(read(DATA / 'corpus.json'))
    query = public_query(read(DATA / 'queries.json')['queries'][0])
    class Encoder:
        def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]
    class Scorer:
        def rank(self, text, hits):
            assert text == query['query']
            assert 0 < len(hits) <= 20
            return list(reversed(hits)), {'pairs': len(hits), 'max_pair_tokens': 100}
    vectors = {c['id']: [1.0, 0.0] for c in chunks}
    fused, _ = retrieve(query, chunks, vectors, Encoder(), None, 'hybrid-rrf')
    reranked, trace = retrieve(query, chunks, vectors, Encoder(), Scorer(), 'hybrid-rrf-ce')
    assert [c['id'] for c, _ in reranked] == [c['id'] for c, _ in reversed(fused)]
    assert trace['rerank']['pairs'] == len(fused)


def test_wrong_variant_is_rejected():
    with pytest.raises(ValueError, match='variant'):
        retrieve({}, [], {}, None, None, 'fallback')
