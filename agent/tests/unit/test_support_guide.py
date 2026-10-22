import hashlib
import json

import httpx
import pytest
from pydantic import ValidationError

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import Read
from resolveflow.support.sources import BoundSources
from tests.unit.test_support_agent import request


def test_guide_is_versioned_source_bound_and_not_refund_policy():
    source = guide_source()
    assert source["source_type"] == "KNOWLEDGE"
    assert source["version"] == "2026.10.22-v2"
    assert source["data"]["authority"] == "APPLICATION_GUIDE"
    assert "policy_manifest" not in source["data"] and "rule_id" not in source["data"]
    assert len(source["data"]["sections"]) == 10
    assert "不需要填写退款金额" in source["data"]["text"]
    assert "并不会自动创建退款工单" in source["data"]["text"]
    assert "Case关联" not in source["data"]["text"]
    assert "尚未接通" not in source["data"]["text"]
    assert len(json.dumps(source, ensure_ascii=False).encode()) < 8192
    assert len(source["data"]["knowledge_sha256"]) == 64


def test_guide_returns_independent_values_with_exact_source_fingerprint():
    first = guide_source()
    first["data"]["text"] = "tampered"
    second = guide_source()
    assert second["data"]["text"] != "tampered"
    assert second["data"]["text_sha256"] == hashlib.sha256(second["data"]["text"].encode()).hexdigest()


def test_agent_reads_guide_on_demand_without_policy_index_or_business_fact_reads():
    req = request()
    seen = []

    def current(call):
        seen.append(call.url.path)
        return httpx.Response(200, json={"conversation_id": req.conversation_id, "input_version": req.input_version})

    model = MockModelClient(script=[
        {"kind": "READ_TOOL", "tool_name": "get_support_guide", "arguments": {}},
        {"kind": "ANSWER", "text": "可以先请商家核查，不需要填写退款金额。", "citations": ["O1"]},
    ])
    with httpx.Client(transport=httpx.MockTransport(current)) as client:
        sources = BoundSources(req, case_url="http://case.local", token="read-token", client=client)
        result = SupportAgent(req, model, sources).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["mode"] == "mock"
    assert result["answer"]["citations"][0]["source_type"] == "KNOWLEDGE"
    assert len(result["answer"]["citations"][0]["data"]["sections"]) == 10
    assert result["spend"]["local_reads"] == 1
    assert all(path.endswith("/current") for path in seen)
    assert model.packets[-1]["observations"][0]["version"] == "2026.10.22-v2"
    assert "sections" not in model.packets[-1]["observations"][0]["data"]


@pytest.mark.parametrize("arguments", [{"merchant_id": "M-B"}, {"query": "refund"}])
def test_guide_tool_has_no_scope_or_search_arguments(arguments):
    with pytest.raises(ValidationError):
        Read.model_validate({"kind": "READ_TOOL", "tool_name": "get_support_guide", "arguments": arguments})


def test_guide_read_obeys_local_budget_before_source_access():
    model = MockModelClient(script=[{"kind": "READ_TOOL", "tool_name": "get_support_guide", "arguments": {}}])
    result = SupportAgent(request(), model, object(), budget=RunBudget(local_reads=0)).run()
    assert result["status"] == "FAILED" and result["reason"] == "BUDGET_LOCAL_READS"
    assert result["spend"]["local_reads"] == 0
