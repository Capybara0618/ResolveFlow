"""A ranking must use exactly its chosen generation and compatible finite vectors."""

import datetime as dt
from dataclasses import replace

import pytest
from resolveflow.policies import PolicyIndex, PolicyIndexNotReadyError

from tests.integration.test_policy_index import LOGISTICS_SEPTEMBER, _StubForDense


def lookup(index, bundle=LOGISTICS_SEPTEMBER, encoder=None, **changes):
    return index.search(merchant_id=bundle.merchant_id, bundle_ids=[bundle.bundle_id],
        manifest_hash=bundle.manifest_hash, query="包裹找不到了", path="dense" if encoder else "bm25",
        embedder=encoder, **changes)


def test_only_selected_latest_generation_is_read(agent_db):
    index = PolicyIndex(agent_db)
    index.build(LOGISTICS_SEPTEMBER, generation_id="old", now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    changed = replace(LOGISTICS_SEPTEMBER, rules=[{"rule_id": "NEW", "title": "新索引", "text": "包裹找不到"}])
    index.build(changed, generation_id="new", now=dt.datetime(2026, 1, 2, tzinfo=dt.UTC))
    hits = lookup(index)
    assert [h.rule_id for h in hits] == ["NEW"]


def test_mixed_merchant_pins_refuse_even_if_one_merchant_matches(agent_db):
    index = PolicyIndex(agent_db)
    other = replace(LOGISTICS_SEPTEMBER, bundle_id="other", merchant_id="M-2002")
    index.build(LOGISTICS_SEPTEMBER)
    index.build(other)
    with pytest.raises(PolicyIndexNotReadyError, match="merchant"):
        index.search(merchant_id=LOGISTICS_SEPTEMBER.merchant_id,
            bundle_ids=[LOGISTICS_SEPTEMBER.bundle_id, other.bundle_id],
            manifest_hash=LOGISTICS_SEPTEMBER.manifest_hash, query="包裹", path="bm25")


@pytest.mark.parametrize("field,value", [("model", "different"), ("revision", "different"), ("dimension", 7)])
def test_query_encoder_identity_must_match_generation(agent_db, field, value):
    index = PolicyIndex(agent_db)
    index.build(LOGISTICS_SEPTEMBER, embedder=_StubForDense())
    encoder = _StubForDense()
    setattr(encoder, field, value)
    with pytest.raises(PolicyIndexNotReadyError, match="embedding"):
        lookup(index, encoder=encoder)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0.0])
def test_invalid_vectors_do_not_create_ready_generation(agent_db, value):
    encoder = _StubForDense()
    encoder.embed = lambda texts: [[value] * encoder.dimension for _ in texts]
    index = PolicyIndex(agent_db)
    with pytest.raises(ValueError, match="vector"):
        index.build(LOGISTICS_SEPTEMBER, embedder=encoder)
    assert index.generations() == []


@pytest.mark.parametrize("vectors", [[], [[0.0] * 8], [[float("nan")] * 8], [[1.0] * 7]])
def test_invalid_query_vector_refuses_instead_of_empty_or_random_ranking(agent_db, vectors):
    index = PolicyIndex(agent_db)
    encoder = _StubForDense()
    index.build(LOGISTICS_SEPTEMBER, embedder=encoder)
    encoder.embed = lambda texts: vectors
    with pytest.raises(ValueError, match="vector"):
        lookup(index, encoder=encoder)


def test_corrupt_stored_vector_is_not_a_policy_miss(agent_db):
    index = PolicyIndex(agent_db)
    encoder = _StubForDense()
    index.build(LOGISTICS_SEPTEMBER, embedder=encoder)
    with agent_db.connection() as connection:
        connection.execute("UPDATE policy_index_chunk SET embedding=ARRAY[0.0]::real[]")
    with pytest.raises(PolicyIndexNotReadyError, match="vector"):
        lookup(index, encoder=encoder)


def test_ready_with_missing_chunks_refuses_instead_of_partial_policy(agent_db):
    index = PolicyIndex(agent_db)
    index.build(LOGISTICS_SEPTEMBER)
    with agent_db.connection() as connection:
        connection.execute("DELETE FROM policy_index_chunk WHERE chunk_id='c-01'")
    with pytest.raises(PolicyIndexNotReadyError, match="chunk count"):
        lookup(index)
