from types import SimpleNamespace

import httpx
import pytest

from resolveflow.policies.index import PolicyHit
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.sources import BoundSources
from tests.unit.test_support_agent import request


@pytest.mark.parametrize(("code", "expected"), [(503, "SOURCE_UNAVAILABLE"), (404, "NOT_FOUND")])
def test_only_fixed_run_facade_is_called_and_fault_is_not_a_shipment_fact(code, expected):
    seen = []

    def respond(req):
        seen.append(req)
        return httpx.Response(code)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        source = BoundSources(request(), case_url="http://case.local", token="bound-read-token", client=client)
        value = source.read("get_shipment_trace", {})
        assert value["error"] == expected and "source_type" not in value
        assert str(seen[0].url).endswith("/facts/shipment")
        assert seen[0].headers["Authorization"] == "Bearer bound-read-token"


@pytest.mark.parametrize(
    ("code", "reason"), [(403, "FORBIDDEN_SOURCE"), (401, "FORBIDDEN_SOURCE"), (409, "STALE_INPUT")]
)
def test_forbidden_or_stale_stops_instead_of_switching_scope(code, reason):
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(code))) as client:
        source = BoundSources(request(), case_url="http://case.local", token="token", client=client)
        with pytest.raises(SupportFailure, match=reason):
            source.check_current()


def test_search_filters_before_recall_and_pins_generation_instead_of_using_query_identity(caplog):
    calls = []

    class Index:
        def require_ready(self, bundle_ids, manifest_hash):
            calls.append({"bundle_ids": bundle_ids, "manifest_hash": manifest_hash})
            return [SimpleNamespace(bundle_id="A", generation_id="generation-1", merchant_id="M-A")]

        def search(self, **scope):
            scope["timings"].update({"embedding_ms": 5.0, "total_ms": 8.0})
            calls.append(scope)
            return [
                PolicyHit(
                    version="v1",
                    title="本店政策",
                    bundle_id="A",
                    merchant_id="M-A",
                    manifest_hash="hash",
                    rule_id="r1",
                    chunk_id="chunk",
                    content_hash="digest",
                    text="完整条件与例外",
                    score=1.0,
                    path=scope["path"],
                )
            ]

    source = BoundSources(request(), case_url="http://case.local", token="token", index=Index(), embedder=object())
    try:
        with caplog.at_level("INFO", logger="resolveflow.support.sources"):
            hits = source.search("请查询M-B的政策", 3)
        source.search("再解释一下", 2)
        assert hits[0]["data"]["merchant_id"] == "M-A"
        assert len(calls) == 7  # One generation pin, three routes for each of two Agent searches.
        for call in calls:
            assert call.get("merchant_id", "M-A") == "M-A" and call["bundle_ids"] == ["A"]
        assert all(c["generation_ids"] == {"A": "generation-1"} for c in calls[1:])
        assert [(c["path"], c["lexical_field"]) for c in calls[1:4]] == [
            ("dense", "body"),
            ("bm25", "body"),
            ("bm25", "title"),
        ]
        assert all(c["query"] == "请查询M-B的政策" for c in calls[1:4])
        assert "support_policy_search" in caplog.text and "embedding_ms" in caplog.text
        assert "请查询M-B的政策" not in caplog.text and "bound-read-token" not in caplog.text
        assert "timings" not in hits[0] and "embedding_ms" not in str(hits)
    finally:
        source.close()


def test_cross_merchant_manifest_fails_without_reading_index():
    req = request()
    req.context["policy_manifest"]["merchant_id"] = "M-B"
    source = BoundSources(req, case_url="http://case.local", token="token", index=object())
    try:
        with pytest.raises(SupportFailure, match="POLICY_SCOPE_MISMATCH"):
            source.search("退款条件", 3)
    finally:
        source.close()


def test_bound_adapter_passes_both_branches_under_one_pinned_generation():
    calls = []

    class Index:
        def require_ready(self, bundle_ids, manifest_hash):
            return [SimpleNamespace(bundle_id='A', generation_id='generation-1', merchant_id='M-A')]

        def search(self, **scope):
            calls.append(scope)
            name = 'current' if scope['query'] == '当前条件' else 'conditional'
            return [PolicyHit(version='v1', title=name, bundle_id='A', merchant_id='M-A', manifest_hash='hash',
                              rule_id=name, chunk_id=name, content_hash='hash-' + name,
                              text='受控原始条件' + name, score=1.0, path=scope['path'])]

    source = BoundSources(request(), case_url='http://unused.local', token='unused', index=Index(), embedder=object())
    try:
        values = source.search('完整问题', 3, sub_queries=['当前条件', '假设条件'])
        assert [s['data']['rule_id'] for s in values] == ['current', 'conditional']
        assert len(calls) == 6 and all(c['generation_ids'] == {'A': 'generation-1'} for c in calls)
    finally:
        source.close()


def test_ranked_source_identity_does_not_change_when_result_window_size_changes():
    class Index:
        def require_ready(self, bundle_ids, manifest_hash):
            return [SimpleNamespace(bundle_id='A', generation_id='g1', merchant_id='M-A')]

        def search(self, **scope):
            return [PolicyHit(version='v1', title=name, bundle_id='A', merchant_id='M-A', manifest_hash='hash',
                rule_id=name, chunk_id=name, content_hash='hash-' + name, text='完整条件', score=1.0,
                path=scope['path']) for name in ['a', 'b']]

    source = BoundSources(request(), case_url='http://unused', token='unused', index=Index(), embedder=object())
    try:
        assert source.search('条件', 1)[0] == source.search('条件', 2)[0]
    finally:
        source.close()
