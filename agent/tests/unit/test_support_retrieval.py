"""Rank fusion deduplicates scoped identities and does not turn ranking metadata into policy facts."""

from dataclasses import replace

import pytest

from resolveflow.policies.index import PolicyHit
from resolveflow.support.retrieval import reciprocal_rank_fusion


def hit(chunk, merchant="M-A"):
    return PolicyHit(
        bundle_id="bundle-A",
        merchant_id=merchant,
        version="v1",
        manifest_hash="hash",
        rule_id=chunk,
        chunk_id=chunk,
        content_hash="digest-" + chunk,
        title="title",
        text="原始条件及例外",
        score=0.5,
        path="dense",
    )


def test_rank_fusion_counts_each_document_once_per_route_and_preserves_source():
    a, b = hit("A"), hit("B")
    ranking = reciprocal_rank_fusion([[a, a, b], [b, a]], top_k=2)
    assert [h.rule_id for h in ranking] == ["A", "B"]
    assert ranking[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert ranking[0].text == a.text and ranking[0].content_hash == a.content_hash
    assert a.score == 0.5  # No mutation of an observation reused in another comparison.


def test_cross_scope_and_conflicting_originals_are_rejected_before_fusion():
    a = hit("A")
    for other in [hit("B", merchant="M-B"), replace(a, text="不同条件"), replace(a, manifest_hash="other")]:
        with pytest.raises(ValueError):
            reciprocal_rank_fusion([[a], [other]], top_k=3)


def test_ties_are_stable_and_rank_bounds_are_explicit():
    assert [h.rule_id for h in reciprocal_rank_fusion([[hit("B")], [hit("A")]], top_k=2)] == ["A", "B"]
    assert reciprocal_rank_fusion([[], []], top_k=3) == []
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[hit("A")]], top_k=6)
