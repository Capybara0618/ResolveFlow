from dataclasses import asdict

import pytest

from resolveflow.harness.budget import RunSpend
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.store import SupportStore
from tests.unit.test_support_agent import request


def test_completed_dispatch_reuses_result_and_changed_input_is_refused(agent_db):
    store = SupportStore(agent_db)
    req = request()
    lease, result = store.claim(req, {"version": "v1"})
    assert result is None
    lease.finish({"status": "SUCCEEDED", "answer": {"text": "已回答"}})
    assert store.claim(req, {"version": "new-config"})[1]["answer"]["text"] == "已回答"
    changed = req.model_copy(update={"input_version": 3})
    with pytest.raises(SupportFailure, match="INPUT_MISMATCH"):
        store.claim(changed, {"version": "v1"})


def test_lease_fence_and_frozen_manifest_are_checked_on_every_write(agent_db):
    store = SupportStore(agent_db)
    req = request()
    old, _ = store.claim(req, {"version": "v1"})
    with pytest.raises(SupportFailure, match="RUN_BUSY"):
        store.claim(req, {"version": "v1"})
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET lease_until=now()-interval '1 second'")
    with pytest.raises(SupportFailure, match="MANIFEST_MISMATCH"):
        store.claim(req, {"version": "v2"})
    newer, _ = store.claim(req, {"version": "v1"})
    with pytest.raises(SupportFailure, match="STALE_FENCE"):
        old.finish({"status": "SUCCEEDED"})
    newer.finish({"status": "FAILED", "reason": "test"})


def test_saved_result_reuses_exact_request_and_unfinished_call_keeps_reservation(agent_db):
    store = SupportStore(agent_db)
    req = request()
    lease, _ = store.claim(req, {"version": "v1"})
    spend = asdict(RunSpend(model_calls=1, input_tokens=100, output_tokens=1024))
    lease.start("model", 1, {"messages": ["actual payload"]}, spend)
    with pytest.raises(SupportFailure, match="UNKNOWN_MODEL_RESULT"):
        lease.cached("model", 1, {"messages": ["actual payload"]})
    lease.complete("model", 1, {"decision": {"kind": "ANSWER"}}, spend)
    assert lease.cached("model", 1, {"messages": ["actual payload"]})["decision"]["kind"] == "ANSWER"
    with pytest.raises(SupportFailure, match="CALL_MISMATCH"):
        lease.cached("model", 1, {"messages": ["changed"]})
    assert lease.spend()["model_calls"] == 1 and lease.spend()["output_tokens"] == 1024
    lease.pin_generations({"A": "generation-1"})
    assert lease.generations() == {"A": "generation-1"}
    with pytest.raises(SupportFailure, match="GENERATION_MISMATCH"):
        lease.pin_generations({"A": "generation-2"})


def test_crash_after_saved_model_result_reconstructs_sdk_without_more_calls(agent_db):
    from resolveflow.harness.model import MockModelClient
    from resolveflow.support.engine import SupportAgent
    from tests.unit.test_support_agent import Reads, answer, read

    req = request()
    store = SupportStore(agent_db)
    journal, _ = store.claim(req, {"version": "v1"})
    first_model = MockModelClient(script=[read(), answer(citations=["O1"])])
    first = SupportAgent(req, first_model, Reads(), journal=journal).run()
    assert first["status"] == "SUCCEEDED"
    # Result was saved, process died before final run update. Rebuild SDK from the journal, not a new budget.
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET lease_until=now()-interval '1 second'")
    resumed, _ = store.claim(req, {"version": "v1"})
    second_model = MockModelClient(script=[])
    source = Reads()
    result = SupportAgent(req, second_model, source, journal=resumed).run()
    assert result == first and second_model.calls == 0 and source.calls == []
    resumed.finish(result)
    assert store.claim(req, {"version": "v1"})[1] == first


def test_bound_sources_uses_existing_index_api_with_scoped_dense_candidates(agent_db):
    from resolveflow.policies.index import PolicyIndex, ServedBundle
    from resolveflow.support.sources import BoundSources
    from tests.conftest import StubEmbedder

    req = request()
    bundle = ServedBundle(
        "A",
        "M-A",
        "v1",
        "a" * 64,
        1,
        [{"rule_id": "signed", "title": "签收争议", "text": "显示签收但客户未收到时需要商家核验。"}],
    )
    encoder = StubEmbedder()
    index = PolicyIndex(agent_db)
    index.build(bundle, embedder=encoder)
    req.context["policy_manifest"] = {"merchant_id": "M-A", "bundle_ids": ["A"], "manifest_hash": "a" * 64}
    sources = BoundSources(req, case_url="http://unused", token="token", index=index, embedder=encoder)
    try:
        hits = sources.search("签收未收到如何核验", 3)
        assert hits[0]["source_type"] == "POLICY" and hits[0]["data"]["merchant_id"] == "M-A"
        assert sources.generations["A"]
    finally:
        sources.close()
