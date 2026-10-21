from dataclasses import asdict

import httpx
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


def test_saved_guide_source_and_local_spend_survive_crash_without_reading_new_asset(agent_db, monkeypatch):
    from resolveflow.harness.model import MockModelClient
    from resolveflow.support.engine import SupportAgent
    from resolveflow.support.sources import BoundSources

    req = request()
    store = SupportStore(agent_db)
    journal, _ = store.claim(req, {"guide_version": "2026.10.21-v1"})
    model = MockModelClient(script=[
        {"kind": "READ_TOOL", "tool_name": "get_support_guide", "arguments": {}},
        {"kind": "ANSWER", "text": "不申请退款也可以请商家核查。", "citations": ["O1"]},
    ])
    with httpx.Client() as client:
        source = BoundSources(req, case_url="http://unused", token="token", client=client)
        monkeypatch.setattr(source, "check_current", lambda: None)
        first = SupportAgent(req, model, source, journal=journal).run()
        assert first["status"] == "SUCCEEDED"
        assert len(first["answer"]["citations"][0]["data"]["sections"]) == 10
        with agent_db.connection() as c:
            c.execute("UPDATE support_agent_run SET lease_until=now()-interval '1 second'")
        resumed, _ = store.claim(req, {"guide_version": "2026.10.21-v1"})
        monkeypatch.setattr("resolveflow.support.sources.guide_source", lambda: pytest.fail("must use saved guide"))
        second_model = MockModelClient(script=[])
        second = SupportAgent(req, second_model, source, journal=resumed).run()
    assert second == first and second_model.calls == 0
    assert second["spend"]["local_reads"] == 1


def test_recovery_rebuilds_source_failure_state_from_saved_calls_without_new_requests(agent_db):
    from resolveflow.harness.model import MockModelClient
    from resolveflow.support.engine import SupportAgent
    from tests.unit.test_support_agent import answer, read
    from tests.unit.test_support_recovery import Unavailable

    req = request()
    store = SupportStore(agent_db)
    journal, _ = store.claim(req, {"version": "recovery-v1"})
    model = MockModelClient(script=[read(), read(), read("get_support_guide"), answer(citations=["O1"])])
    original = SupportAgent(req, model, Unavailable(), journal=journal).run()
    assert original["status"] == "SUCCEEDED"
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET lease_until=now()-interval '1 second'")
    resumed, _ = store.claim(req, {"version": "recovery-v1"})
    source = Unavailable()
    recovered = SupportAgent(req, MockModelClient(script=[]), source, journal=resumed)
    result = recovered.run()
    assert result == original and source.calls == []
    assert recovered.recovery.packet()[0]["failures"] == 2
    assert recovered.recovery.packet()[0]["retry_allowed"] is False


def test_layered_context_and_tasks_rebuild_exactly_from_saved_calls(agent_db):
    from resolveflow.harness.model import MockModelClient
    from resolveflow.support.engine import SupportAgent
    from tests.unit.test_support_agent import Reads, answer, read
    from tests.unit.test_support_context import long_request
    from tests.unit.test_support_tasks import task

    req = long_request()
    raw = req.context["history"][0]["text"]
    pending = [task("locate")]
    final = [task("locate", status="NEEDS_MERCHANT", evidence_refs=["O1"], response_excerpt="请商家核查")]
    store = SupportStore(agent_db)
    journal, _ = store.claim(req, {"version": "layered-v1"})
    model = MockModelClient(script=[{**read("read_context", reference="H21", offset=len(raw)-16, limit=16),
                                    "tasks": pending}, answer(text="请商家核查。", citations=["O1"], tasks=final)])
    original = SupportAgent(req, model, Reads(), journal=journal).run()
    assert original["status"] == "SUCCEEDED", original["reason"]
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET lease_until=now()-interval '1 second'")
    resumed, _ = store.claim(req, {"version": "layered-v1"})
    source = Reads()
    empty = MockModelClient(script=[])
    rebuilt = SupportAgent(req, empty, source, journal=resumed)
    assert rebuilt.run() == original and empty.calls == 0 and source.calls == []
    assert rebuilt.tasks.packet() == original["answer"]["task_state"]
