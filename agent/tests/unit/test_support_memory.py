"""Inspect source-backed customer claims in real model packets, not fabricated system facts."""

from copy import deepcopy

import pytest

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from tests.unit.test_support_agent import Reads, answer, read, request
from tests.unit.test_support_context import message


def memory(key, quote, reference="CURRENT", offset=0, **updates):
    return {"id": key, "topic": "RECEIPT", "reference": reference, "offset": offset,
            "quote": quote, "supersedes": [], "retracts": [], **updates}


def test_original_customer_quotes_and_correction_links_survive_history_compression():
    req = request(input_version=5)
    old = "可能是家人代收了。"
    new = "纠正一下，家人没有代收，也问过代收点没有找到。"
    req.context.update(current_request=new, history=[message(1, old), message(5, new)])
    updates = [memory("old", old, "H1"), memory("current", new, supersedes=["old"])]
    model = MockModelClient(script=[{**read(), "memory_updates": updates}, answer(citations=["O1"])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    state = model.packets[1]["customer_memory"]
    assert state["origin"] == "GROUNDED_CUSTOMER_CLAIMS"
    assert [m["id"] for m in state["active"]] == ["current"]
    assert state["active"][0]["quote"] == new
    saved = result["answer"]["customer_memory"]
    assert saved["entries"][0]["status"] == "SUPERSEDED"
    assert saved["entries"][1]["source"]["sequence"] == 5


@pytest.mark.parametrize("update", [
    memory("fake", "系统已经退款成功。"),
    memory("fake", "助手说过的话", "H2"),
    memory("fake", "没有收到", "H999"),
    memory("fake", "没有收到", offset=999),
])
def test_fabricated_assistant_future_or_invalid_quotes_never_enter_memory(update):
    req = request(input_version=3)
    req.context.update(current_request="没有收到", history=[message(2, "助手说过的话", "ASSISTANT")])
    model = MockModelClient(script=[{**read(), "memory_updates": [update]}, answer(citations=[])])
    source = Reads()
    result = SupportAgent(req, model, source).run()
    assert result["status"] == "SUCCEEDED"
    assert '"field": "memory_updates"' in model.packets[1]["feedback"]
    assert model.packets[1]["customer_memory"]["active"] == [] and source.calls == []


def test_conflicting_claims_coexist_without_an_explicit_correction_and_bad_batch_is_atomic():
    req = request(input_version=3)
    req.context.update(current_request="没有收到", history=[message(1, "家人可能收了")])
    initial = [memory("a", "家人可能收了", "H1"), memory("b", "没有收到")]
    model = MockModelClient(script=[{**read(), "memory_updates": initial},
                                   answer(citations=["O1"], memory_updates=[memory("c", "没有收到", supersedes=["a"]),
                                                                           memory("bad", "不存在的句子")]),
                                   answer(citations=["O1"])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert [m["id"] for m in model.packets[2]["customer_memory"]["active"]] == ["a", "b"]


def test_bad_task_validation_does_not_commit_otherwise_valid_memory_update():
    req = request()
    original = deepcopy(req.context)
    update = memory("x", req.context["current_request"])
    model = MockModelClient(script=[answer(citations=["P99"], memory_updates=[update]),
                                   answer(citations=[])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED"
    assert model.packets[1]["customer_memory"]["active"] == [] and req.context == original


def saved_memory():
    req = request(input_version=3)
    req.context["current_request"] = "家人可能代收了"
    model = MockModelClient(script=[answer(citations=[], memory_updates=[memory("old", "家人可能代收了")])])
    return SupportAgent(req, model, Reads()).run()["answer"]["customer_memory"]


def test_imported_claim_is_injected_without_old_history_and_correction_is_persisted():
    req = request(input_version=7)
    req.context.update(current_request="纠正，家人没代收", history=[], previous_customer_memory=saved_memory())
    model = MockModelClient(script=[answer(citations=[], memory_updates=[
        memory("new", "纠正，家人没代收", supersedes=["old"])])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.packets[0]["customer_memory"]["active"][0]["quote"] == "家人可能代收了"
    assert [e["status"] for e in result["answer"]["customer_memory"]["entries"]] == ["SUPERSEDED", "ACTIVE"]


@pytest.mark.parametrize("field,value", [("conversation_id", "foreign"), ("merchant_id", "M-other"),
                                        ("line_id", "other-line"), ("input_version", 7)])
def test_foreign_or_nonhistorical_memory_is_refused_before_model_call(field, value):
    from resolveflow.support.protocol import SupportFailure

    snapshot = saved_memory()
    snapshot[field] = value
    req = request(input_version=7)
    req.context["previous_customer_memory"] = snapshot
    model = MockModelClient(script=[answer(citations=[])])
    with pytest.raises(SupportFailure, match="PREVIOUS_MEMORY_INVALID"):
        SupportAgent(req, model, Reads())
    assert model.calls == 0


def test_carried_active_claim_stays_in_budgeted_packet_when_recent_history_is_removed():
    from tests.unit.test_support_context import long_request

    req = long_request()
    req.context["previous_customer_memory"] = saved_memory()
    model = MockModelClient(script=[answer(citations=[])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.packets[0]["customer_memory"]["active"][0]["quote"] == "家人可能代收了"
    assert model.packets[0]["context_layout"]["recent_full"] < 4


def test_retraction_preserves_original_and_prevents_silent_overwrite():
    req = request(input_version=7)
    req.context.update(current_request="刚才的代收猜测撤回", previous_customer_memory=saved_memory())
    model = MockModelClient(script=[answer(citations=[], memory_updates=[
        memory("withdraw", "刚才的代收猜测撤回", retracts=["old"])])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    entries = result["answer"]["customer_memory"]["entries"]
    assert entries[0]["status"] == "RETRACTED" and entries[0]["quote"] == "家人可能代收了"
    assert entries[1]["retracts"] == ["old"]
