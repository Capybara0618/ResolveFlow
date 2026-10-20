from types import SimpleNamespace

import httpx
import pytest

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


def test_search_filters_before_recall_and_pins_generation_instead_of_using_query_identity():
    calls = []

    class Index:
        def require_ready(self, bundle_ids, manifest_hash):
            calls.append({"bundle_ids": bundle_ids, "manifest_hash": manifest_hash})
            return [SimpleNamespace(bundle_id="A", generation_id="generation-1", merchant_id="M-A")]

        def search(self, **scope):
            calls.append(scope)
            return [
                SimpleNamespace(
                    version="v1",
                    title="本店政策",
                    bundle_id="A",
                    merchant_id="M-A",
                    manifest_hash="hash",
                    rule_id="r1",
                    chunk_id="chunk",
                    content_hash="digest",
                    text="完整条件与例外",
                )
            ]

    source = BoundSources(request(), case_url="http://case.local", token="token", index=Index(), embedder=object())
    try:
        hits = source.search("请查询M-B的政策", 3)
        source.search("再解释一下", 2)
        assert hits[0]["data"]["merchant_id"] == "M-A"
        assert len(calls) == 3
        for call in calls:
            assert call.get("merchant_id", "M-A") == "M-A" and call["bundle_ids"] == ["A"]
        assert calls[-1]["generation_ids"] == {"A": "generation-1"} and calls[-1]["path"] == "dense"
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
