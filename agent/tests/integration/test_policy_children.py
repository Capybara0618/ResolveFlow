import datetime as dt

import pytest
from agent.tests.unit.test_policy_children import Segmented
from resolveflow.policies import PolicyIndex, PolicyIndexNotReadyError, ServedBundle


def bundle():
    return ServedBundle(
        "child-test",
        "merchant",
        "v1",
        "a" * 64,
        1,
        [{"rule_id": "R", "title": "完整条件", "text": "长条款。" * 80 + "已退款不得再退。"}],
    )


def search(index, b, encoder, **kwargs):
    return index.search(
        merchant_id=b.merchant_id,
        bundle_ids=[b.bundle_id],
        manifest_hash=b.manifest_hash,
        query="已退款",
        path="dense",
        embedder=encoder,
        **kwargs,
    )


def test_child_index_returns_complete_authority_rule(agent_db):
    index, b, encoder = PolicyIndex(agent_db), bundle(), Segmented()
    result = index.build(b, embedder=encoder)
    generation = index.generation_for(b.bundle_id, b.manifest_hash)
    assert generation.retrieval_layout == "token-children-v1" and generation.child_count > 1
    hits = search(index, b, encoder)
    assert len(hits) == 1 and hits[0].text == b.rules[0]["text"]
    assert hits[0].chunk_id == "c-01" and hits[0].citation()["content_hash"] == b.chunks()[0].content_hash
    with agent_db.connection() as connection:
        count = connection.execute(
            "SELECT count(*) AS n FROM policy_index_child WHERE generation_id=%s", (result.generation_id,)
        ).fetchone()["n"]
    assert count == generation.child_count


@pytest.mark.parametrize("field,value", [("text", "forged"), ("end_offset", 1), ("embedding", [1.0] * 8)])
def test_stored_children_tampering_refuses_search(agent_db, field, value):
    from psycopg import sql

    index, b, encoder = PolicyIndex(agent_db), bundle(), Segmented()
    result = index.build(b, embedder=encoder)
    with agent_db.connection() as connection:
        connection.execute(
            sql.SQL("UPDATE policy_index_child SET {}=%s WHERE generation_id=%s AND child_id=%s").format(
                sql.Identifier(field)
            ),
            (value, result.generation_id, "c-01:s0000"),
        )
    with pytest.raises(PolicyIndexNotReadyError, match="integrity"):
        search(index, b, encoder)


def test_generation_pin_does_not_jump_after_rebuild(agent_db):
    index, b, encoder = PolicyIndex(agent_db), bundle(), Segmented()
    old = index.build(b, embedder=encoder, now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    new = index.build(b, embedder=encoder, now=dt.datetime(2026, 1, 2, tzinfo=dt.UTC))
    assert old.generation_id != new.generation_id
    assert search(index, b, encoder, generation_ids={b.bundle_id: old.generation_id})
    index.fail(b.bundle_id, old.generation_id, "test")
    with pytest.raises(PolicyIndexNotReadyError, match="no substitution"):
        search(index, b, encoder, generation_ids={b.bundle_id: old.generation_id})
    assert search(index, b, encoder, generation_ids={b.bundle_id: new.generation_id})
