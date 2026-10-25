"""Independent baseline: ordinary branches work without production Agent imports."""

import ast
import json
from copy import deepcopy
from pathlib import Path

import pytest
from scripts.evaluation import basic_customer_workflow as baseline


class Model:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, *, stage, messages, max_output_tokens):
        self.calls.append({"stage": stage, "messages": deepcopy(messages), "max_output_tokens": max_output_tokens})
        value = next(self.replies)
        return baseline.ModelReply(json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value,
            usage={"input_tokens": 10, "output_tokens": 5}, mode="scripted")


class Sources:
    def __init__(self, failures=None):
        self.failures = failures or {}
        self.calls = []

    def __call__(self, category, *, query=None):
        self.calls.append((category, query))
        status = self.failures.get(category, 200)
        return {"status_code": status, "body": {"source": category, "query": query, "raw": "原始接口结果"}}


def run(intent="LOGISTICS", *, answer=None, failures=None, replies=None, history=None, subject=None):
    model = Model(replies or [
        {"intent": intent, "customer_description": "客户称没收到", "policy_query": "签收争议条件"},
        answer or {"text": "物流记录非本人实收，待核查", "refund_summary": None, "handoff_summary": None}])
    sources = Sources(failures)
    result = baseline.run_turn(current_request="帮我核对一下", history=history or [],
        subject=subject or {"merchant_id": "M", "customer_id": "C", "line_id": "L", "product": {"name": "耳机"}},
        model=model, read=sources)
    return result, model, sources


@pytest.mark.parametrize(("intent", "expected"), [
    ("ORDER", ["GUIDE", "ORDER"]), ("LOGISTICS", ["GUIDE", "SHIPMENT"]),
    ("QUALITY", ["GUIDE", "ORDER", "POLICY"]), ("POLICY", ["GUIDE", "POLICY"]),
    ("REFUND", ["GUIDE", "ORDER", "SHIPMENT", "POLICY"]),
    ("HANDOFF", ["GUIDE"]), ("GUIDE", ["GUIDE"]), ("OTHER", ["GUIDE"]),
])
def test_every_ordinary_branch_uses_its_fixed_path_and_one_common_guide(intent, expected):
    result, model, sources = run(intent)
    assert result["status"] == "SUCCEEDED"
    assert [c for c, _ in sources.calls] == expected
    assert [c["stage"] for c in model.calls] == ["ROUTE", "ANSWER"]
    assert len(result["models"]) == 2 and len(result["tools"]) == len(expected)


def test_drafts_are_exact_model_output_and_never_programmatically_assembled():
    answer = {"text": "先核对草稿", "refund_summary": "客户称没收到，未核验，未提交。", "handoff_summary": None}
    result, _, _ = run("REFUND", answer=answer)
    assert result["answer"] == answer
    missing, _, _ = run("REFUND", answer={"text": "我整理好了", "refund_summary": None, "handoff_summary": None})
    assert missing["answer"]["refund_summary"] is None


def test_one_transient_retry_and_original_failure_are_visible_to_final_model():
    result, model, sources = run(failures={"SHIPMENT": 503})
    assert result["status"] == "SUCCEEDED"
    assert [c for c, _ in sources.calls] == ["GUIDE", "SHIPMENT", "SHIPMENT"]
    final_input = json.loads(model.calls[-1]["messages"][-1]["content"])
    assert [t["response"]["status_code"] for t in final_input["observations"]] == [200, 503, 503]


def test_order_not_found_is_not_retried_or_replaced_with_product_price():
    result, model, sources = run("ORDER", failures={"ORDER": 404})
    assert result["status"] == "SUCCEEDED" and [c for c, _ in sources.calls] == ["GUIDE", "ORDER"]
    packet = json.loads(model.calls[-1]["messages"][-1]["content"])
    assert packet["observations"][-1]["response"]["status_code"] == 404
    assert "payment" not in packet


def test_only_plain_history_and_public_subject_are_passed_not_agent_state_or_gold():
    history = [{"role": "user", "content": str(i), "task_state": "PRIVATE"} for i in range(23)]
    subject = {"merchant_id": "M", "customer_id": "C", "line_id": "L", "product": {"name": "耳机"},
        "previous_tasks": "PRIVATE", "business_expectations": "GOLD", "customer_memory": "PRIVATE"}
    original = deepcopy(history)
    _, model, _ = run(history=history, subject=subject)
    for call in model.calls:
        packet = json.loads(call["messages"][-1]["content"])
        assert len(packet["history"]) == 20 and packet["history"][0]["content"] == "3"
        assert "PRIVATE" not in call["messages"][-1]["content"] and "GOLD" not in call["messages"][-1]["content"]
    assert history == original


def test_json_format_repair_once_does_not_change_or_repeat_fixed_investigation():
    replies = ["bad json", {"intent": "GUIDE", "customer_description": "流程", "policy_query": None},
        "bad json", {"text": "说明流程", "refund_summary": None, "handoff_summary": None}]
    result, model, sources = run(replies=replies)
    assert result["status"] == "SUCCEEDED" and len(model.calls) == 4
    assert [c for c, _ in sources.calls] == ["GUIDE"]
    failed, calls, _ = run(replies=["bad", "still bad"])
    assert failed["status"] == "FAILED" and failed["answer"] is None and len(calls.calls) == 2


def test_model_cannot_add_an_investigation_action_during_answering():
    result, _, sources = run(replies=[{"intent": "LOGISTICS", "customer_description": "未收"},
        {"kind": "READ_TOOL", "tool_name": "search_policy"},
        {"text": "据现有记录说明", "refund_summary": None, "handoff_summary": None}])
    assert result["status"] == "SUCCEEDED"
    assert [c for c, _ in sources.calls] == ["GUIDE", "SHIPMENT"]


def test_independent_module_does_not_import_production_or_another_agent_controller():
    module = ast.parse(Path(baseline.__file__).read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imports.extend(n.name for n in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module)
    assert set(imports) <= {"__future__", "json", "time", "copy", "dataclasses", "typing", "pydantic"}


def test_budget_and_deadline_stop_before_publishing_and_keep_actual_attempts():
    model, sources = Model([{"intent": "LOGISTICS"}]), Sources()
    result = baseline.run_turn(current_request="物流", history=[], subject={}, model=model, read=sources,
        max_model_calls=1)
    assert result["status"] == "BUDGET_EXHAUSTED" and len(result["models"]) == 1
    assert result["answer"] is None
    result = baseline.run_turn(current_request="物流", history=[], subject={}, model=model, read=sources,
        timeout_seconds=0)
    assert result["status"] == "TIMEOUT" and not result["models"] and result["answer"] is None


def test_transport_exception_is_one_recorded_attempt_with_unknown_usage():
    class Broken:
        def complete(self, **_):
            raise TimeoutError("provider timed out")

    snapshots = []
    result = baseline.run_turn(current_request="物流", history=[], subject={}, model=Broken(), read=Sources(),
        on_record=snapshots.append)
    assert result["status"] == "FAILED" and len(result["models"]) == 1
    assert result["models"][0]["state"] == "ERROR" and result["models"][0]["usage"] is None
    assert snapshots[-1] == result


def test_allowance_block_is_not_recorded_as_a_provider_transmission():
    class Blocked:
        last_sent = False

        def complete(self, **_):
            raise RuntimeError("BUDGET_EXHAUSTED")

    result = baseline.run_turn(current_request="物流", history=[], subject={}, model=Blocked(), read=Sources())
    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["models"][0]["provider_sent"] is False


def test_retained_timer_uses_only_successful_answer_after_format_repair():
    class Timed(Model):
        def complete(self, **kwargs):
            reply = super().complete(**kwargs)
            return baseline.ModelReply(reply.text, reply.usage, reply.mode, 20.0)

    model = Timed([{"intent": "GUIDE"}, "bad", {"text": "实际正文"}])
    result = baseline.run_turn(current_request="流程", history=[], subject={}, model=model, read=Sources())
    assert result["status"] == "SUCCEEDED" and len(result["models"]) == 3
    assert result["first_body_ms"] == result["models"][-1]["started_ms"] + 20.0
