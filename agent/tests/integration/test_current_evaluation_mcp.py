"""Real MCP subprocesses on isolated synthetic sources; no Java or model calls."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from resolveflow.harness.mcp_client import ToolCallFailedError

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.evaluation.dataset import export_case  # noqa: E402
from scripts.evaluation.environment import business_tools  # noqa: E402


def test_aligned_dispatch_and_actual_first_model_request():
    import uuid

    from resolveflow.harness.model import MockModelClient
    from resolveflow.harness.sdk_runner import AgentScopeRunner
    from scripts.evaluation.dataset import ALIGNED_DATA
    from scripts.evaluation.environment import dispatch_facts

    from tests.conftest import input_text_of

    case = export_case("A13A", ALIGNED_DATA)
    pin = {"merchant_id": case["scope"]["merchant_id"], "bundle_ids": [case["bundle_id"]],
           "manifest_hash": "a" * 64, "safety_epoch": 2}
    run_id = str(uuid.uuid4())
    facts = dispatch_facts(case, pin, run_id=run_id, case_id=case["case_id"])
    model = MockModelClient(script=[{"kind": "ESCALATE", "reason_codes": ["PROBE"], "summary": "Synthetic"}])
    with business_tools(case, pin, run_id=run_id, case_id=case["case_id"]) as (tools, requests):
        wire = tools.call_tool(run_id=run_id, tool_name="get_case_evidence", arguments={})
        assert wire.result == case["backend"]["evidence"]
        assert "materials" not in wire.result
        assert len(requests) == 1
        result = AgentScopeRunner(model=model, tools=tools, facts=facts).run()
        assert result.completed and model.calls == 1
        actual = input_text_of(model, 0)
        for material in facts.review_context["materials"]:
            assert material["content"] in actual
            assert material["content_hash"] in actual
        assert "allowed_actions" not in actual and "support_requirements" not in actual


def test_all_five_scoped_reads_and_out_of_scope_refusal():
    case = export_case("A05A")
    pin = {
        "merchant_id": case["scope"]["merchant_id"],
        "bundle_ids": [case["bundle_id"]],
        "manifest_hash": "a" * 64,
        "safety_epoch": 2,
    }
    with business_tools(case, pin, run_id="eval-run", case_id="eval-case") as (tools, requests):
        for name in (
            "get_order_context",
            "get_shipment_trace",
            "get_case_evidence",
            "get_policy_manifest",
            "get_refund_status",
        ):
            observation = tools.call_tool(run_id="eval-run", tool_name=name, arguments={})
            assert observation.error is None and observation.source_version and observation.content_hash
            assert "allowed_actions" not in str(observation.result)
        assert len(requests) == 5 and all(r["authorized"] for r in requests)
        # The MCP server ignores surplus args; its bound subject cannot be changed.
        # The domain ActionGate additionally rejects this argument before model tool use.
        bound = tools.call_tool(run_id="eval-run", tool_name="get_order_context", arguments={"line_id": "another-line"})
        assert bound.result["line_id"] == case["scope"]["line_id"]
        assert "another-line" not in requests[-1]["path"]
        with pytest.raises(ToolCallFailedError):
            tools.call_tool(run_id="different-run", tool_name="get_order_context", arguments={})
        assert len(requests) == 6


def test_unavailable_source_is_an_error_observation():
    case = export_case("A08B")
    with business_tools(case, {}, run_id="eval-run", case_id="eval-case") as (tools, requests):
        observation = tools.call_tool(run_id="eval-run", tool_name="get_shipment_trace", arguments={})
        assert observation.error is not None and observation.result is None
        assert observation.source_version is None and observation.content_hash is None
        assert len(requests) == 1
