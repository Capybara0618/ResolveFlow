"""Model proposes quoted meaning; program owns claim identity and correction links."""

from copy import deepcopy

import pytest

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from tests.unit.test_support_agent import Reads, answer, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_staged import staged, understand


def claim(text, **updates):
    return {"topic": "CHECKS", "reference": "CURRENT", "quote": text, **updates}


def test_append_assigns_stable_id_and_source_without_model_identity_or_old_target():
    req = request()
    payload = answer(citations=[], customer_claims=[claim(req.context["current_request"])])
    results = [SupportAgent(req, MockModelClient(script=[payload]), Reads()).run() for _ in range(2)]
    assert all(r["status"] == "SUCCEEDED" for r in results)
    snapshots = [r["answer"]["customer_memory"] for r in results]
    assert snapshots[0] == snapshots[1]
    entry = snapshots[0]["entries"][0]
    assert entry["id"].startswith("c_") and entry["source"]["offset"] == 0
    assert entry["supersedes"] == entry["retracts"] == []


@pytest.mark.parametrize("change", ["REPLACE", "RETRACT"])
def test_only_real_customer_targets_can_be_replaced_and_old_quote_is_retained(change):
    req = request(input_version=1)
    req.context["current_request"] = "家人可能代收。"
    old = SupportAgent(req, MockModelClient(script=[answer(citations=[], customer_claims=[
        claim(req.context["current_request"])])]), Reads()).run()["answer"]["customer_memory"]
    key = old["entries"][0]["id"]
    next_req = request(input_version=3)
    next_req.context.update(current_request="家人没有代收。", previous_customer_memory=old)
    model = MockModelClient(script=[answer(citations=[], customer_claims=[
        claim("家人没有代收。", change=change, target=key)])])
    result = SupportAgent(next_req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    entries = result["answer"]["customer_memory"]["entries"]
    assert entries[0]["quote"] == "家人可能代收。"
    assert entries[0]["status"] == ("SUPERSEDED" if change == "REPLACE" else "RETRACTED")
    assert entries[1]["supersedes" if change == "REPLACE" else "retracts"] == [key]
    assert model.packets[0]["customer_memory"]["correction_targets"][0]["id"] == key


@pytest.mark.parametrize("bad", [
    {"target": "请再问家人", "change": "REPLACE"},
    {"change": "REPLACE"}, {"quote": "系统已经退款"},
    {"reference": "H9"}, {"id": "model_owns_id"}, {"supersedes": "助手建议"},
])
def test_invalid_optional_proposal_is_visible_without_blocking_an_otherwise_valid_turn(bad):
    req = request()
    model = MockModelClient(script=[answer(citations=[], customer_claims=[
        claim(req.context["current_request"], **bad)])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 1 and result["answer"]["customer_memory"]["entries"] == []
    assert result["answer"]["memory_warnings"][0]["index"] == 0


def test_staged_resume_accepts_plain_new_claim_and_preserves_actual_source_offset():
    req = request(input_version=5)
    req.context["current_request"] = "继续签收调查。纠正：家人和代收点都没有代收。"
    req.context["previous_tasks"] = {"origin": "MODEL_PREVIOUS_TURN", "input_version": 3,
        "tasks": [{"id": "trace", "intent": "LOGISTICS", "request": "查签收",
                   "status": "SUSPENDED", "lifecycle": "PAUSED"}]}
    opening = understand(req, needs=[], events=[{"change": "RESUME", "task_ids": ["trace"],
        "reference": "CURRENT", "quote": "继续签收调查。"}])
    opening["customer_claims"] = [claim("家人和代收点都没有代收。")]
    result, model, source, _ = staged(req, [opening, parts(part("trace", "已记录排查，无需重复询问。"))])
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 2 and source.calls == []
    assert result["answer"]["task_state"]["tasks"][0]["lifecycle"] == "OPEN"
    entry = result["answer"]["customer_memory"]["entries"][0]
    assert entry["source"]["offset"] == req.context["current_request"].index(entry["quote"])


def test_valid_new_claim_does_not_commit_if_the_same_action_has_invalid_dialogue():
    req = request()
    original = deepcopy(req.context)
    bad = understand(req, needs=[])
    bad.update(customer_claims=[claim(req.context["current_request"])])
    bad["dialogue_events"][0]["quote"] = "客户未说过"
    result, _, _, agent = staged(req, [bad, bad])
    assert result["status"] == "FAILED"
    assert agent.memory.entries == [] and req.context == original
