"""Corrections retain independent facts; summary references are resolved by the program."""

from copy import deepcopy

import pytest

from resolveflow.support.memory import CustomerMemory
from tests.unit.test_support_agent import request


def seeded_memory():
    req = request(input_version=1)
    req.context["current_request"] = "本人尚未收到；我仍未拿到；家人还没回复；外箱有破损"
    mem = CustomerMemory(req)
    mem.propose([{"topic": "RECEIPT", "reference": "CURRENT", "quote": q}
                 for q in ("本人尚未收到", "我仍未拿到", "家人还没回复")]
                + [{"topic": "MATERIAL", "reference": "CURRENT", "quote": "外箱有破损"}], [])
    next_req = request(input_version=3)
    next_req.context.update(current_request="包裹已找到，未收到的问题结束。", previous_customer_memory=mem.snapshot())
    return next_req, CustomerMemory(next_req)


@pytest.mark.parametrize("change,expected", [("REPLACE", "SUPERSEDED"), ("RETRACT", "RETRACTED")])
def test_one_explicit_correction_invalidates_all_selected_claims_and_keeps_independent_facts(change, expected):
    req, mem = seeded_memory()
    ids = [e["id"] for e in mem.entries[:2]]
    mem.propose([{"topic": "RECEIPT", "reference": "CURRENT", "quote": req.context["current_request"],
                  "change": change, "targets": ids}], [])
    assert mem.warnings == []
    assert [e["status"] for e in mem.entries] == [expected, expected, "ACTIVE", "ACTIVE", "ACTIVE"]
    assert mem.entries[-1]["supersedes" if change == "REPLACE" else "retracts"] == ids
    restored = request(input_version=5)
    restored.context["previous_customer_memory"] = mem.snapshot()
    assert [e["quote"] for e in CustomerMemory(restored).packet()["active"]] == [
        "家人还没回复", "外箱有破损", req.context["current_request"]]


@pytest.mark.parametrize("bad", ["missing", "different_topic", "duplicate", "both"])
def test_multi_target_correction_is_atomic_if_any_selected_target_is_invalid(bad):
    req, mem = seeded_memory()
    before = deepcopy(mem.snapshot())
    first = mem.entries[0]["id"]
    target = {"missing": "unknown", "different_topic": mem.entries[3]["id"], "duplicate": first,
              "both": mem.entries[1]["id"]}[bad]
    proposal = {"topic": "RECEIPT", "reference": "CURRENT", "quote": req.context["current_request"],
                "change": "REPLACE", "targets": [first, target]}
    if bad == "both":
        proposal["target"] = first
    mem.propose([proposal], [])
    assert mem.snapshot() == before and len(mem.warnings) == 1


def test_multi_target_extension_of_same_quote_is_atomic_and_idempotent():
    req, mem = seeded_memory()
    original_ids = [e["id"] for e in mem.entries[:2]]
    base = {"topic": "RECEIPT", "reference": "CURRENT", "quote": req.context["current_request"]}
    mem.propose([base], [])
    before = deepcopy(mem.snapshot())
    mem.propose([{**base, "change": "REPLACE", "targets": [original_ids[0], "unknown"]}], [])
    assert mem.snapshot() == before and mem.warnings
    correction = {**base, "change": "REPLACE", "targets": original_ids}
    mem.propose([correction, correction], [])
    assert not mem.warnings and len(mem.entries) == 5
    assert mem.entries[-1]["supersedes"] == original_ids
