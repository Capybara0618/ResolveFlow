"""Real SDK/PG/MCP plumbing, with an explicitly stubbed provider transport."""

import json
import sys
from pathlib import Path

import pytest
from resolveflow.harness.live_model import HttpResponse, LiveModelClient
from resolveflow.harness.token_counting import FLASH_VERSION, counter_for
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.runs import RunStore
from resolveflow.runtime.worker import RunWorker

from tests.integration.test_run_worker import CASE_DISPATCHER, RUN_ID, a_run
from tests.unit.test_harness_loop import StubTools

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.evaluation.build_calibration import CALIBRATED_DATA  # noqa: E402
from scripts.evaluation.dataset import export_case  # noqa: E402
from scripts.evaluation.environment import business_tools  # noqa: E402


def test_flash_counter_and_durable_reservation_share_manifest_and_actual_body(agent_db):
    sent = []

    def transport(url, body, headers, timeout):
        sent.append(json.loads(body))
        return HttpResponse(200, json.dumps({"choices": [{"message": {"content": json.dumps(
            {"kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN_VERIFICATION"]})}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}}).encode())

    client = LiveModelClient(endpoint="https://api.deepseek.com/chat/completions", model_id="deepseek-flash",
                             provider="deepseek", transport=transport)
    # UTF-8 exceeds the old limit; the pinned tokenizer fits without removing required claims.
    description = "客户请求退款并需要人工核对。" * 230
    RunStore(agent_db).queue(a_run(description=description), caller=CASE_DISPATCHER)
    config = DeploymentConfig(mode="live", provider="deepseek", endpoint=client.endpoint,
                              model_id=client.model_id, api_key="transport-stub")
    outcome = RunWorker(agent_db, build_investigation(database=agent_db, config=config,
                         model=client, tools=StubTools()), recoverable=True).run_once()
    assert outcome.result.completed and len(sent) == 1
    assert description in sent[0]["messages"][-1]["content"]
    with agent_db.connection() as connection:
        row = connection.execute("SELECT reserved_input,request_body FROM agent_model_call WHERE run_id=%s",
                                 (RUN_ID,)).fetchone()
        run = connection.execute("SELECT manifest FROM agent_run_model_budget WHERE run_id=%s",
                                 (RUN_ID,)).fetchone()
        spent = connection.execute("SELECT budget_spent FROM agent_run WHERE run_id=%s", (RUN_ID,)).fetchone()
    assert row["request_body"] == sent[0]
    assert counter_for(client).count(sent[0]) <= row["reserved_input"] <= 8192
    assert run["manifest"]["model"]["token_counter_version"] == FLASH_VERSION
    assert spent["budget_spent"]["input_tokens"] == 100  # actual stub usage, not local estimate


@pytest.mark.parametrize("identifier", ["A03B", "A07B", "A16B", "A13A"])
def test_calibrated_responses_survive_the_real_mcp_contract_gate(identifier):
    case = export_case(identifier, CALIBRATED_DATA)
    with business_tools(case, {}, run_id="calibration-probe", case_id=case["case_id"]) as (tools, requests):
        for name in ("get_order_context", "get_refund_status", "get_shipment_trace"):
            result = tools.call_tool(run_id="calibration-probe", tool_name=name, arguments={})
            assert result.error is None and result.source_version and result.content_hash
        assert len(requests) == 3


def test_unpaid_draft_source_missing_is_not_a_citable_order():
    case = export_case("A04B", CALIBRATED_DATA)
    with business_tools(case, {}, run_id="calibration-probe", case_id=case["case_id"]) as (tools, _):
        result = tools.call_tool(run_id="calibration-probe", tool_name="get_order_context", arguments={})
        assert result.error.code == "NOT_FOUND" and not result.error.retryable
        assert result.result is None and result.source_version is None and result.content_hash is None
