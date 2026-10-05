"""Progress means new sources or policy chunks, not a changed search wrapper."""

from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_adapter import AgentScopeModelAdapter
from resolveflow.harness.sdk_runner import ActionGateMiddleware, AgentScopeRunner

from tests.unit.test_harness_loop import FACTS, StubTools, observation, propose, read
from tests.unit.test_proposal_verifier import RULE, search


def test_alternating_reads_without_new_sources_stop_before_another_repeat():
    a = observation("get_order_context")
    b = observation("get_refund_status").model_copy(update={"content_hash": "b" * 64})
    model = MockModelClient(script=[read(name) for name in [
        "get_order_context", "get_refund_status", "get_order_context", "get_refund_status", "get_order_context"]])
    tools = StubTools(a, b, a, b, a)
    result = AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
    assert not result.completed and result.reason_code == "NO_PROGRESS"
    assert len(tools.calls) == 4 and result.spend.model_calls == 5
    assert sum(n.startswith("NO_PROGRESS") for n in result.notices) == 2


def test_rephrased_query_ranking_and_scores_do_not_create_new_policy_evidence():
    adapter = AgentScopeModelAdapter(MockModelClient(script=[]), system="")
    second_rule = {**RULE, "chunk_id": "second-known-condition", "content_hash": "c" * 64}
    first = search(RULE, second_rule)
    again = first.model_copy(update={"content_hash": "f" * 64, "result": {
        "query": "换一种退款问法", "hits": [{**second_rule, "score": .99}, RULE], "hit_count": 2}})
    assert adapter.record_observation(first)
    assert not adapter.record_observation(again)
    assert adapter.record_observation(search({**RULE, "chunk_id": "new-condition", "content_hash": "e" * 64}))


def test_new_version_is_progress_even_if_content_bytes_are_unchanged():
    adapter = AgentScopeModelAdapter(MockModelClient(script=[]), system="")
    first = observation()
    assert adapter.record_observation(first)
    assert adapter.record_observation(first.model_copy(update={"source_version": "4"}))


def test_different_subject_source_is_not_deduplicated_by_equal_payload_hash():
    adapter = AgentScopeModelAdapter(MockModelClient(script=[]), system="")
    assert adapter.record_observation(observation("get_order_context"))
    assert adapter.record_observation(observation("get_refund_status"))


def test_three_empty_different_searches_stop_after_observing_the_last_result():
    gate = ActionGateMiddleware()
    for index in range(3):
        assert gate.check({"kind": "SEARCH_POLICY", "query": f"different query {index}"}) is not None
        gate.note_evidence(False)
    assert gate.stop_reason == "NO_PROGRESS" and gate.progress.rounds == 3
    assert len(gate.notices) == 2


def test_new_policy_from_a_different_query_clears_the_no_progress_streak():
    gate = ActionGateMiddleware()
    for index in range(2):
        gate.check({"kind": "SEARCH_POLICY", "query": f"empty query {index}"})
        gate.note_evidence(False)
    assert gate.check({"kind": "SEARCH_POLICY", "query": "new relevant query"}) is not None
    gate.note_evidence(True)
    assert gate.stop_reason is None and gate.progress.rounds == 0
    assert gate.check(propose("MANUAL_REVIEW")) is not None
