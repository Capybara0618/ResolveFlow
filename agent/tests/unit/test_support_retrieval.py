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


def test_branch_merge_keeps_each_head_before_filling_from_fused_candidates():
    from resolveflow.support.retrieval import merge_query_branches

    a, b, common = hit('A'), hit('B'), hit('common')
    result = merge_query_branches([[a, common, b], [b, common, a]], top_k=3)
    assert [h.rule_id for h in result] == ['A', 'B', 'common']
    assert [h.rule_id for h in merge_query_branches([[a, b], [a, b]], top_k=3)] == ['A', 'B']
    assert merge_query_branches([[], []], top_k=3) == []
    with pytest.raises(ValueError):
        merge_query_branches([[a], [hit('B', merchant='M-B')]], top_k=3)


def test_optional_two_queries_share_pins_and_use_six_bounded_routes_in_one_search():
    from resolveflow.support.retrieval import retrieve_policy

    calls = []

    class Index:
        def search(self, **kwargs):
            calls.append(kwargs)
            return [hit('A'), hit('common')] if kwargs['query'] == '当前分支' else [hit('B'), hit('common')]

    timings = {}
    result = retrieve_policy(Index(), merchant_id='M-A', bundle_ids=['bundle-A'], manifest_hash='hash',
        generation_ids={'bundle-A': 'generation-1'}, query='完整问题', sub_queries=['当前分支', '假设分支'],
        top_k=3, embedder=object(), timings=timings)
    assert [h.rule_id for h in result] == ['A', 'B', 'common']
    assert len(calls) == 6 and [c['query'] for c in calls] == ['当前分支'] * 3 + ['假设分支'] * 3
    assert all(c['generation_ids'] == {'bundle-A': 'generation-1'} and c['top_k'] == 5 for c in calls)
    assert 'branch_0_total_ms' in timings and 'branch_1_total_ms' in timings


def test_second_branch_failure_cannot_return_first_branch_evidence():
    from resolveflow.policies.index import PolicyIndexNotReadyError
    from resolveflow.support.retrieval import retrieve_policy

    class Index:
        def search(self, **kwargs):
            if kwargs['query'] == '第二分支':
                raise PolicyIndexNotReadyError('generation unavailable')
            return [hit('A')]

    with pytest.raises(PolicyIndexNotReadyError):
        retrieve_policy(Index(), merchant_id='M-A', bundle_ids=['bundle-A'], manifest_hash='hash',
            generation_ids={'bundle-A': 'generation-1'}, query='完整问题', sub_queries=['第一分支', '第二分支'],
            top_k=3, embedder=object(), timings={})


@pytest.mark.parametrize('queries', [[], ['只有一个'], ['a', 'b', 'c'], ['相同', ' 相同 '], ['', 'b']])
def test_query_decomposition_is_explicit_bounded_and_distinct(queries):
    from pydantic import ValidationError

    from resolveflow.support.protocol import SearchArguments

    with pytest.raises(ValidationError):
        SearchArguments(query='完整问题', sub_queries=queries)


def test_two_branch_request_requires_room_and_is_in_the_sdk_schema():
    from pydantic import ValidationError

    from resolveflow.support.guidance import tool_schema
    from resolveflow.support.protocol import SearchArguments

    with pytest.raises(ValidationError):
        SearchArguments(query='完整问题', sub_queries=['a', 'b'], top_k=1)
    value = SearchArguments(query='完整问题', sub_queries=['a', 'b'])
    assert value.sub_queries == ['a', 'b']
    assert tool_schema('search_policy')['properties']['sub_queries']['maxItems'] == 2
