"""Profiling must preserve ranking/citations and work with both stored retrieval layouts."""

import hashlib
from dataclasses import asdict

import pytest

from resolveflow.policies.index import PolicyIndex
from tests.integration.test_policy_index import LOGISTICS_SEPTEMBER


@pytest.mark.parametrize("layout", ["whole", "children"])
def test_profile_is_per_search_and_does_not_change_hits(agent_db, stub_embedder, layout):
    class ChildEncoder:
        model = stub_embedder.model
        revision = stub_embedder.revision
        dimension = stub_embedder.dimension
        embed = stub_embedder.embed

        def policy_segments(self, text):
            return [
                {
                    "text": text,
                    "start": 0,
                    "end": len(text),
                    "encoder_tokens": len(text),
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            ]

    encoder = stub_embedder if layout == "whole" else ChildEncoder()
    index = PolicyIndex(agent_db)
    bundle = LOGISTICS_SEPTEMBER
    generation = index.build(bundle, embedder=encoder)
    args = dict(
        merchant_id=bundle.merchant_id,
        bundle_ids=[bundle.bundle_id],
        manifest_hash=bundle.manifest_hash,
        generation_ids={bundle.bundle_id: generation.generation_id},
        query="承运商丢失",
        top_k=2,
    )
    expected = index.search(**args, path="dense", embedder=encoder)
    profile = {"previous_search": 999.0}
    measured = index.search(**args, path="dense", embedder=encoder, timings=profile)
    assert [asdict(hit) for hit in expected] == [asdict(hit) for hit in measured]
    assert "previous_search" not in profile
    assert {"scope_ms", "parent_read_ms", "embedding_ms", "ranking_ms", "result_ms", "total_ms"} <= set(profile)
    assert all(value >= 0 for value in profile.values())
    assert profile["total_ms"] >= profile["embedding_ms"]
    index.search(**args, path="bm25", timings=profile)
    assert "embedding_ms" not in profile
    assert {"scope_ms", "parent_read_ms", "ranking_ms", "result_ms", "total_ms"} == set(profile)
