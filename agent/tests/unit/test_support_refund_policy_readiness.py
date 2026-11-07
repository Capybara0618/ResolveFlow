"""Refund preparation about fulfilment must not become ready without policy evidence."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from resolveflow.support.engine import SupportAgent
from resolveflow.support.orchestration import Orchestration, Response
from resolveflow.support.progress import ProgressReporter
from tests.recorded_sources import ProjectedSupportInput as SupportInput
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.recorded_sources import SavedSources
from tests.support_request_checks import approve_requests, checked_script
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestrated_engine import Sources, respond, run
from tests.unit.test_support_orchestration import plan, source_refs


def prepared():
    req = request()
    p = plan(req, needs=["SHIPMENT"])
    flow = Orchestration(req)
    flow.accept(p)
    approve_requests(flow, p.meaning())
    return req, p, flow


def policy_refs():
    return {**source_refs(), "P1": {"source_type": "POLICY", "version": "v1",
                                   "data": {"text": "须由商家核验争议后判断退款。"}}}


def test_fulfilment_refund_stays_waiting_even_if_model_omits_policy_need():
    _, p, flow = prepared()
    state = flow.snapshot(p.meaning(), source_refs(), [], {})
    assert state["phase"] == "INVESTIGATE"
    assert state["tasks"][0]["missing"] == ["POLICY"]
    assert "search_policy" in flow.failure_tools(p.meaning())["trace"]


def test_later_shipment_refinement_also_adds_policy_requirement():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    approve_requests(flow, p.meaning())
    meaning = p.meaning()
    assert flow.snapshot(meaning, source_refs(), [], {})["phase"] == "COMPOSE"
    meaning.focus[0].needs.append("SHIPMENT")
    assert flow.snapshot(meaning, source_refs(), [], {})["tasks"][0]["missing"] == ["POLICY"]


def test_required_policy_must_be_selected_in_response_not_just_present_in_packet():
    _, p, flow = prepared()
    response = Response.model_validate(respond())
    with pytest.raises(ValueError, match="POLICY"):
        flow.compose(response, p.meaning(), policy_refs(), [], {})
    response.parts[0].citations = ["P1"]
    response.parts[0].text = "先按条款核验争议，草稿不代表批准。"
    result = flow.compose(response, p.meaning(), policy_refs(), [], {})
    assert result.refund_summary and "P1" in result.parts[0].citations


@pytest.mark.parametrize("failure", [None, True, False])
def test_absent_retryable_and_final_policy_failure_have_distinct_readiness(failure):
    _, p, flow = prepared()
    failures = [] if failure is None else [{"tool_name": "search_policy", "error": "UNAVAILABLE",
                                           "retry_allowed": failure}]
    state = flow.snapshot(p.meaning(), source_refs(), failures, {})
    assert state["tasks"][0]["state"] == ("BLOCKED" if failure is False else "WAITING")
    if failure is False:
        result = flow.compose(Response.model_validate(respond(refund_reason=None)), p.meaning(),
                              source_refs(), failures, {})
        assert result.parts[0].status == "UNAVAILABLE" and not result.refund_summary
        assert result.parts[0].blocker.tool_name == "search_policy"


@pytest.mark.parametrize("goal,intent", [("EXPLAIN", "LOGISTICS"), ("EXPLAIN", "APPLICATION"),
                                        ("MERCHANT_REVIEW", "HANDOFF")])
def test_other_goals_do_not_inherit_refund_policy_floor(goal, intent):
    req = request()
    p = plan(req, goal=goal, intent=intent, needs=["SHIPMENT"])
    flow = Orchestration(req)
    flow.accept(p)
    approve_requests(flow, p.meaning())
    assert flow.snapshot(p.meaning(), source_refs(), [], {})["phase"] == "COMPOSE"


@pytest.mark.parametrize("life", ["CANCELLED", "PAUSED", "RESOLVED"])
def test_inactive_preparation_does_not_force_new_policy_reads(life):
    _, p, flow = prepared()
    assert flow.snapshot(p.meaning(), {}, [], {"trace": life})["phase"] == "COMPOSE"


def test_old_real_s02_response_cannot_publish_before_policy_read_or_stream_candidate():
    path = (Path(__file__).resolve().parents[3]
            / "agent/tests/fixtures/regressions/customer-agent-summary-live-v1/runtime-results.json")
    row = next(r for r in json.loads(path.read_text(encoding="utf-8"))["rows"]
               if (r["id"], r["turn"]) == ("S02", 1))
    req = SupportInput.model_validate({**row["input"], "deadline_at": request().deadline_at})
    batches = []
    reporter = ProgressReporter("http://synthetic.invalid", req.run_id, "test", transport=httpx.MockTransport(
        lambda r: (batches.append(json.loads(r.content)) or httpx.Response(200))))

    class Stream(TokenizedScript):
        def decide(self, **kwargs):
            reply = super().decide(**kwargs)
            reporter.content(json.dumps(reply.decision, ensure_ascii=False))
            return reply

    model = Stream(mode="live", script=checked_script(deepcopy([m["decision"] for m in row["models"]])))
    agent = SupportAgent(req, model, SavedSources(row["calls"]), architecture="orchestrated-v1", progress=reporter)
    result = agent.run()
    reporter.close()
    assert result["status"] == "FAILED" and result["answer"] is None
    assert agent._readiness()["tasks"][0]["missing"] == ["POLICY"]
    assert not any(e["kind"] == "answer.delta" for batch in batches for e in batch["events"])


def test_sdk_continues_to_model_chosen_policy_and_requires_cited_explanation():
    req = request()
    script = [plan(req, needs=["SHIPMENT"]).model_dump(),
              {"kind": "READ_TOOL", "tool_name": "get_shipment_trace", "arguments": {}},
              {"kind": "READ_TOOL", "tool_name": "get_order_context", "arguments": {}},
              respond(),  # Old-style early finish is not a protocol repair or a publishable answer.
              {"kind": "READ_TOOL", "tool_name": "search_policy", "arguments": {"query": "签收争议如何核验"}},
              respond(parts=[{"task_id": "trace", "text": "按条款需商家核验争议，草稿不代表批准。",
                              "citations": ["P1"]}])]
    result, agent, model, sources = run(script, req, Sources())
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert agent.repairs == 0 and model.calls == 7
    assert model.packets[5]["orchestration"]["tasks"][0]["missing"] == ["POLICY"]
    assert sources.calls[-1][0] == "search_policy"
    assert "P1" in [c["source_id"] for c in result["answer"]["citations"]]
