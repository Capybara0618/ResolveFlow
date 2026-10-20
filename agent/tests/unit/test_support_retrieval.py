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


def test_consultation_search_calls_three_scoped_routes_with_same_unmodified_query():
    from resolveflow.support.retrieval import retrieve_policy

    calls = []

    class Index:
        def search(self, **kwargs):
            calls.append(kwargs)
            kwargs["timings"]["total_ms"] = 1.0
            return [hit("A"), hit("B")] if kwargs["path"] == "dense" else [hit("B")]

    profile = {"previous": 99.0}
    result = retrieve_policy(
        Index(),
        merchant_id="M-A",
        bundle_ids=["bundle-A"],
        manifest_hash="hash",
        generation_ids={"bundle-A": "generation-1"},
        query="原始查询",
        top_k=1,
        embedder=object(),
        timings=profile,
    )
    assert result[0].rule_id == "B" and len(result) == 1
    assert [(c["path"], c.get("lexical_field", "body")) for c in calls] == [
        ("dense", "body"),
        ("bm25", "body"),
        ("bm25", "title"),
    ]
    assert all(c["query"] == "原始查询" and c["top_k"] == 5 for c in calls)
    assert all(c["generation_ids"] == {"bundle-A": "generation-1"} and c["merchant_id"] == "M-A" for c in calls)
    assert "previous" not in profile and {
        "dense_ms",
        "body_lexical_ms",
        "title_lexical_ms",
        "fusion_ms",
        "total_ms",
    } <= set(profile)


def test_dense_failure_does_not_fall_back_to_lexical_or_return_partial_evidence():
    from resolveflow.policies.retrieval import EmbeddingUnavailableError
    from resolveflow.support.retrieval import retrieve_policy

    calls = []

    class Index:
        def search(self, **kwargs):
            calls.append(kwargs)
            raise EmbeddingUnavailableError("weights unavailable")

    with pytest.raises(EmbeddingUnavailableError):
        retrieve_policy(
            Index(),
            merchant_id="M-A",
            bundle_ids=["bundle-A"],
            manifest_hash="hash",
            generation_ids={"bundle-A": "generation-1"},
            query="query",
            top_k=3,
            embedder=object(),
            timings={},
        )
    assert len(calls) == 1 and calls[0]["path"] == "dense"


def test_later_route_version_change_aborts_instead_of_returning_dense_only():
    from resolveflow.policies.index import PolicyIndexNotReadyError
    from resolveflow.support.retrieval import retrieve_policy

    class Index:
        def search(self, **kwargs):
            if kwargs["path"] == "dense":
                return [hit("A")]
            raise PolicyIndexNotReadyError("pinned generation retired")

    with pytest.raises(PolicyIndexNotReadyError):
        retrieve_policy(
            Index(),
            merchant_id="M-A",
            bundle_ids=["bundle-A"],
            manifest_hash="hash",
            generation_ids={"bundle-A": "generation-1"},
            query="query",
            top_k=3,
            embedder=object(),
            timings={},
        )
