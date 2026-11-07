"""All five business response components and the MCP boundary, with no provider calls."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from resolveflow.harness.mcp_client import ToolCallFailedError, _observation_of
from resolveflow.tools import catalog
from resolveflow.tools.result_validation import InvalidToolResult, validate_result

from tests.unit.test_tool_catalog import client_for, context, valid_order, valid_refund


def payloads():
    return {
        "get_order_context": valid_order(),
        "get_refund_status": valid_refund(),
        "get_shipment_trace": {"line_id": "7001", "synthetic": True, "status": "LOST",
            "carrier_conclusion": "LOST", "events": [], "source_version": 1,
            "updated_at": "2026-10-05T00:00:00Z"},
        "get_case_evidence": {"case_id": context().case_id, "input_revision": 1, "evidence": []},
        "get_policy_manifest": {"merchant_id": "M-1001", "bundles": [{"bundle_ids": ["bundle-1"],
            "manifest_hash": "a" * 64, "safety_epoch": 1}], "effective_from": "2026-10-05T00:00:00Z"},
    }


@pytest.mark.parametrize("tool", payloads())
def test_each_valid_payload_survives_catalog_and_real_mcp_shape(tool):
    obs = getattr(catalog, tool)(client_for(payloads()[tool]), context())
    assert obs.error is None
    parsed = _observation_of(SimpleNamespace(structured_content=obs.model_dump(mode="json", exclude_none=True)), tool)
    assert parsed == obs


@pytest.mark.parametrize("tool", payloads())
@pytest.mark.parametrize("mutation", ["missing", "unknown", "wrong_type"])
def test_each_tool_rejects_bad_schema_without_echoing_payload(tool, mutation):
    body = deepcopy(payloads()[tool])
    if mutation == "missing":
        body.clear()
    elif mutation == "unknown":
        body["unexpected"] = "PRIVATE SOURCE CONTENT"
    else:
        for key in body:
            body[key] = ["PRIVATE SOURCE CONTENT"]
    obs = getattr(catalog, tool)(client_for(body), context())
    assert obs.error.code == "TOOL_RESULT_INVALID" and not obs.error.retryable
    assert obs.result is None and obs.content_hash is None and obs.source_version is None
    assert "PRIVATE SOURCE CONTENT" not in obs.error.message


@pytest.mark.parametrize("tool,key", [("get_order_context", "line_id"), ("get_refund_status", "line_id"),
    ("get_shipment_trace", "line_id"), ("get_case_evidence", "case_id")])
def test_correct_shape_wrong_subject_is_security_failure(tool, key):
    body = payloads()[tool]
    body[key] = "00000000-0000-4000-8000-000000000099"
    obs = getattr(catalog, tool)(client_for(body), context())
    assert obs.error.code == "SOURCE_MISMATCH" and obs.result is None


@pytest.mark.parametrize("field,value", [("line_paid_amount", "32900"), ("line_paid_amount", 32900.0),
    ("line_paid_amount", -1),
    ("line_paid_amount", True), ("fulfillment_status", "INVALID_STATUS"), ("paid_at", "not a date"),
    ("version", 0)])
def test_amount_enum_time_and_version_are_checked(field, value):
    body = {**valid_order(), "fulfillment_status": "NOT_SHIPPED", "fulfillment_version": 1, field: value}
    with pytest.raises(InvalidToolResult):
        validate_result("get_order_context", body, line_id="7001", case_id=context().case_id)


def test_mcp_peer_cannot_bypass_business_payload_validation():
    obs = catalog.get_order_context(client_for(valid_order()), context()).model_dump(mode="json", exclude_none=True)
    obs["result"]["line_paid_amount"] = "wrong"
    with pytest.raises(ToolCallFailedError) as refused:
        _observation_of(SimpleNamespace(structured_content=obs), "get_order_context")
    assert refused.value.code == "TOOL_RESULT_INVALID"


@pytest.mark.parametrize("change", ["merchant_id", "buyer_id", "source_ref", "input_revision"])
def test_executor_verifies_bound_tenant_and_revision(monkeypatch, change):
    import resolveflow.harness.mcp_client as module
    tool = "get_case_evidence" if change == "input_revision" else "get_order_context"
    obs = getattr(catalog, tool)(client_for(payloads()[tool]), context())
    if change == "source_ref":
        obs = obs.model_copy(update={"source_ref": "commerce:/internal/v1/order-lines/other/context"})
    else:
        body = {**obs.result, change: 2 if change == "input_revision" else "another-principal"}
        obs = obs.model_copy(update={"result": body})

    def answered(coroutine, *, timeout):
        coroutine.close()
        return obs, "none"

    monkeypatch.setattr(module, "_run_sync", answered)
    executor = module.McpToolExecutor(line_id="7001", run_id="run-1", case_id=context().case_id,
                                     merchant_id="M-1001", buyer_id="C-2002", input_revision=1)
    result = executor.call_tool(run_id="run-1", tool_name=tool, arguments={})
    assert result.error.code == "SOURCE_MISMATCH" and result.result is None and result.content_hash is None


def test_labeled_large_evidence_excerpt_keeps_its_revision_binding(monkeypatch):
    import resolveflow.harness.mcp_client as module
    body = {"case_id": context().case_id, "input_revision": 1, "evidence": [
        {"observation_id": f"obs-{i}", "source_ref": "case:" + "x" * 100,
         "source_version": "1", "content_hash": "a" * 64} for i in range(64)]}
    obs = catalog.get_case_evidence(client_for(body), context())
    assert obs.result["truncated"]

    def answered(coroutine, *, timeout):
        coroutine.close()
        return obs, "none"

    monkeypatch.setattr(module, "_run_sync", answered)
    executor = module.McpToolExecutor(line_id="7001", run_id="run-1", case_id=context().case_id, input_revision=1)
    result = executor.call_tool(run_id="run-1", tool_name="get_case_evidence", arguments={})
    assert result.error is None and result.source_version == "1"
    assert result.result["truncated"] and "evidence" not in result.result
