import copy

import pytest
from resolveflow.policies.chunking import chunks_of_bundle
from scripts.agent_rag_source_review import match_searches, policy_rows, saved_observation, validate_labels, verify_hits


def bundle():
    return {
        "bundle_id": "b",
        "merchant_id": "m",
        "version": "v2",
        "rules": [{"rule_id": "r", "title": "退款", "text": "完整条件；末尾例外仍须保留。"}],
    }


def observation(query="条件", text=None):
    b = bundle()
    chunk = chunks_of_bundle("b", b["rules"])[0]
    hit = {
        **chunk.citation,
        "bundle_id": "b",
        "version": "v2",
        "title": chunk.title,
        "text": chunk.text if text is None else text,
        "source_ref": "policy:b/c-01",
        "score": 0.7,
    }
    return {
        "observation_id": "search-1",
        "tool_name": "search_policy",
        "error": None,
        "result": {"query": query, "hit_count": 1, "hits": [hit]},
    }


def entry():
    return {
        "requests": [{"decision": {"kind": "SEARCH_POLICY", "query": "条件", "arguments": {"top_k": 1}}}],
        "observations": [observation()],
    }


def test_refused_search_is_not_a_retrieval_failure_and_does_not_consume_next_observation():
    e = entry()
    e["requests"].insert(0, {"decision": {"type": "action", **e["requests"][0]["decision"]}})
    rows = match_searches(e)
    assert [r["execution"] for r in rows] == ["ACTION_REFUSED", "EXECUTED"]
    assert rows[1]["turn"] == 2 and rows[0]["observation"] is None


def test_unmatched_or_ambiguous_observations_cannot_be_silently_assigned():
    for mutate in (
        lambda e: e["observations"].append(observation("other")),
        lambda e: e["requests"].append(copy.deepcopy(e["requests"][0])),
    ):
        e = entry()
        mutate(e)
        with pytest.raises(ValueError):
            match_searches(e)


def test_full_source_identity_is_checked_not_only_ref_hash():
    assert verify_hits(observation(), bundle()) == ["r"]
    for key, value in [
        ("text", "截断正文"),
        ("version", "v1"),
        ("bundle_id", "other"),
        ("content_hash", "0" * 64),
        ("source_ref", "policy:other/c-01"),
    ]:
        o = observation()
        o["result"]["hits"][0][key] = value
        with pytest.raises(ValueError):
            verify_hits(o, bundle())


def test_bad_hit_count_and_duplicate_identity_are_rejected():
    for value in (0, True):
        o = observation()
        o["result"]["hit_count"] = value
        with pytest.raises(ValueError):
            verify_hits(o, bundle())
    o = observation()
    o["result"]["hits"] *= 2
    o["result"]["hit_count"] = 2
    with pytest.raises(ValueError):
        verify_hits(o, bundle())


def test_policy_table_retains_bundle_version_fields_and_exact_body():
    request = {
        "messages": [
            {
                "role": "user",
                "content": "【P2·policy_table】rows对应fields；bundle/version适用于全部行。\n"
                '{"bundle_id":"b","version":"v2","fields":["ref","rule_id","text"],'
                '"rows":[["P1","r","正文；例外。"]]}\n【P4·index:0】O1',
            }
        ]
    }
    assert policy_rows(request) == [
        {"bundle_id": "b", "version": "v2", "ref": "P1", "rule_id": "r", "text": "正文；例外。"}
    ]
    request["messages"][0]["content"] = request["messages"][0]["content"].replace('"text"', '"rule_id"')
    with pytest.raises(ValueError):
        policy_rows(request)


def test_empty_or_missing_labels_are_not_success_and_case_labels_do_not_replace_query_labels():
    for label in ({"queries": [], "cases": []}, {"queries": [{"id": "c:1"}], "cases": []}):
        with pytest.raises(ValueError):
            validate_labels(label, {"c"}, {"c:1"})


def test_archived_failed_observation_defaults_are_not_wire_citations():
    value = {
        "observation_id": "error-1",
        "tool_name": "get_order_context",
        "source_type": "ORDER_LINE",
        "source_ref": "commerce:/internal/v1/order-lines/a/context",
        "source_version": None,
        "content_hash": None,
        "observed_at": "2026-10-06T10:00:00Z",
        "result": None,
        "error": {"code": "NOT_FOUND", "message": "not found", "retryable": False},
    }
    original = copy.deepcopy(value)
    decoded = saved_observation(value)
    assert decoded.error.code == "NOT_FOUND" and decoded.content_hash is None
    assert value == original
    for changes in ({"source_version": "v1"}, {"content_hash": "0" * 64}, {"error": None}):
        with pytest.raises(ValueError):
            saved_observation({**value, **changes})
