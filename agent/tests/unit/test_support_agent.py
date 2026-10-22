import datetime as dt

import pytest

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import SupportInput


def request(**updates):
    return SupportInput.model_validate(
        {
            "run_id": "00000000-0000-4000-8000-000000000001",
            "conversation_id": "00000000-0000-4000-8000-000000000002",
            "input_version": 2,
            "merchant_id": "M-A",
            "customer_id": "C-A",
            "line_id": "line-A",
            "deadline_at": (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)).isoformat(),
            "context": {
                "current_request": "已经问过家人和代收点，都没有找到，能否请商家核查？",
                "history": [],
                "product": {"name": "耳机"},
                "policy_manifest": {"merchant_id": "M-A", "bundle_ids": ["A"], "manifest_hash": "hash"},
            },
            **updates,
        }
    )


class Reads:
    def __init__(self):
        self.calls = []

    def read(self, name, arguments):
        self.calls.append((name, arguments))
        return {"source_type": "SHIPMENT", "version": 3, "data": {"status": "DELIVERED", "synthetic": True}}

    def search(self, query, top_k):
        self.calls.append(("search_policy", {"query": query, "top_k": top_k}))
        return [
            {
                "source_type": "POLICY",
                "version": "2026.10",
                "title": "签收争议",
                "data": {"rule_id": "signed", "text": "有签收争议时须商家核验，不因客户陈述直接退款。"},
            }
        ]


class GuideReads(Reads):
    def read(self, name, arguments):
        if name == "get_support_guide":
            self.calls.append((name, arguments))
            return guide_source()
        return super().read(name, arguments)


def read(name="get_shipment_trace", **arguments):
    return {"kind": "READ_TOOL", "tool_name": name, "arguments": arguments}


def answer(**updates):
    return {
        "kind": "ANSWER",
        "text": "系统有签收记录，你反馈尚未收到；可以请商家核验。",
        "citations": ["O1", "P1"],
        "handoff_summary": "已查到签收记录，客户反馈未收到且已问过家人/代收点，请商家核查。",
        **updates,
    }


def test_sdk_drives_model_chosen_reads_and_search_before_grounded_answer():
    model = MockModelClient(
        script=[read(), {"kind": "SEARCH_POLICY", "query": "签收但未收到，退款需什么核验", "top_k": 3}, answer()]
    )
    source = Reads()
    result = SupportAgent(request(), model, source).run()
    assert result["status"] == "SUCCEEDED"
    assert result["answer"]["citations"][0]["source_id"] == "O1"
    assert result["answer"]["citations"][1]["data"]["rule_id"] == "signed"
    assert len(source.calls) == 2 and model.calls == 3
    assert result["mode"] == "mock"
    assert result["answer"]["handoff_summary"]
    assert not any("case_id" in packet for packet in model.packets)


def test_ordinary_logistics_question_does_not_force_policy_search_or_order_read():
    model = MockModelClient(script=[read(), answer(citations=["O1"], handoff_summary=None)])
    source = Reads()
    assert SupportAgent(request(), model, source).run()["status"] == "SUCCEEDED"
    assert source.calls == [("get_shipment_trace", {})]


@pytest.mark.parametrize(
    "decision",
    [
        read("refund"),
        read(merchant_id="M-B"),
        {"kind": "SEARCH_POLICY", "query": "签收", "top_k": 3, "merchant_id": "M-B"},
        answer(citations=["P999"]),
        answer(case_id="fake"),
        {"kind": "PROPOSE", "recommended_action": "REFUND"},
    ],
)
def test_writes_identity_overrides_and_unknown_citations_never_execute(decision):
    source = Reads()
    result = SupportAgent(request(), MockModelClient(script=[decision]), source).run()
    assert result["status"] == "FAILED"
    assert not source.calls


def test_repeat_reads_are_bounded_and_model_requests_are_capped():
    source = Reads()
    result = SupportAgent(request(), MockModelClient.always(read()), source).run()
    assert result["status"] == "FAILED" and result["reason"] == "NO_PROGRESS"
    assert len(source.calls) <= 3
    model = MockModelClient.always(read())
    result = SupportAgent(request(), model, Reads(), budget=RunBudget(model_calls=1)).run()
    assert result["status"] == "FAILED" and model.calls == 1


def test_expired_or_oversize_current_request_fails_before_model():
    for req in [
        request(deadline_at="2020-01-01T00:00:00Z"),
        request(context={"current_request": "汉" * 5000, "history": []}),
    ]:
        model = MockModelClient(script=[answer()])
        assert SupportAgent(req, model, Reads()).run()["status"] == "FAILED"
        assert model.calls == 0


def test_query_failure_is_observation_not_a_delivered_or_unknown_fact():
    class Failing(Reads):
        def read(self, name, arguments):
            return {"error": "SOURCE_UNAVAILABLE", "retryable": True}

    model = MockModelClient(script=[read(), answer(text="当前物流查询暂不可用，可请商家核查。", citations=[])])
    result = SupportAgent(request(), model, Failing()).run()
    assert result["status"] == "SUCCEEDED" and result["answer"]["citations"] == []
    assert model.packets[-1]["observations"][0]["error"] == "SOURCE_UNAVAILABLE"


def test_actual_model_input_is_bounded_and_no_sdk_history_is_appended():
    model = MockModelClient(script=[read(), answer(citations=["O1"])])
    assert SupportAgent(request(), model, Reads()).run()["status"] == "SUCCEEDED"
    for messages in model.conversations:
        assert len(messages) == 2 and messages[0].role == "system"
    assert model.output_limits == [1024, 1024]
