import copy

import pytest
from agent.tests.unit.test_agent_rag_source_review import bundle, observation
from scripts.agent_rag_business_review import audit_snapshot
from scripts.agent_rag_source_review import object_hash


def inputs():
    b = bundle()
    o = observation()
    table = {
        "messages": [
            {
                "role": "user",
                "content": "【P2·policy:1】"
                '{"bundle_id":"b","version":"v2","ref":"P1","rule_id":"r",'
                '"text":"完整条件；末尾例外仍须保留。"}',
            }
        ]
    }
    snapshot = {
        "mode": "READ_ONLY_EXISTING_RUN",
        "run_id": "run",
        "case_id": "case",
        "models": [
            {
                "state": "SAVED",
                "request_body": {"messages": []},
                "response": {
                    "mode": "live",
                    "decision": {"kind": "SEARCH_POLICY", "query": "条件", "arguments": {"top_k": 1}},
                },
            },
            {"state": "SAVED", "request_body": table, "response": {"mode": "live", "decision": {"kind": "ESCALATE"}}},
        ],
        "tools": [{"observation": o}],
    }
    acceptance = {
        "run_id": "run",
        "case_id": "case",
        "model_calls": 2,
        "policy_queries": ["条件"],
        "policy_refs": [
            {k: o["result"]["hits"][0][k] for k in ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")}
        ],
        "recommended_action": "MANUAL_REVIEW",
    }
    return snapshot, b, acceptance


def test_saved_business_source_roundtrip_does_not_claim_accuracy():
    source, b, accepted = inputs()
    original = copy.deepcopy(source)
    result = audit_snapshot(source, b, accepted)
    assert result["searches"][0]["observation_sha256"] == object_hash(source["tools"][0]["observation"])
    assert result["new_model_calls"] == result["production_writes"] == 0
    assert result["scope"] == "one source roundtrip, not quality accuracy"
    assert source == original


@pytest.mark.parametrize("mutation", ["scope", "state", "query", "body", "citation", "citation_hash"])
def test_business_source_changes_are_not_silently_accepted(mutation):
    source, b, accepted = inputs()
    if mutation == "scope":
        source["run_id"] = "another"
    elif mutation == "state":
        source["models"][0]["state"] = "UNKNOWN"
    elif mutation == "query":
        accepted["policy_queries"] = ["another"]
    elif mutation == "body":
        source["models"][1]["request_body"]["messages"][0]["content"] = source["models"][1]["request_body"]["messages"][
            0
        ]["content"].replace("末尾例外仍须保留。", "")
    elif mutation == "citation":
        accepted["policy_refs"][0]["rule_id"] = "not-retrieved"
    else:
        accepted["policy_refs"][0]["content_hash"] = "0" * 64
    with pytest.raises(ValueError):
        audit_snapshot(source, b, accepted)


def test_zero_executed_queries_are_not_a_successful_source_audit():
    source, b, accepted = inputs()
    source["models"][0]["response"]["decision"] = {"kind": "ESCALATE"}
    source["tools"] = []
    accepted["policy_queries"] = []
    with pytest.raises(ValueError):
        audit_snapshot(source, b, accepted)
