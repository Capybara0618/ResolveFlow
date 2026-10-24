"""The small real acceptance cannot silently grow or mutate the original cohort."""

from copy import deepcopy

import pytest
from scripts import accept_support_boundary_live_v1 as driver

from resolveflow.support.protocol import SupportFailure


def test_six_single_turn_cases_keep_original_snapshots_and_no_gold_in_model_request():
    before = deepcopy(driver.current.load_cases())
    selected = driver.cases()
    assert len(selected) == 6 and sum(len(c["turns"]) for c in selected) == 6
    assert driver.current.load_cases() == before
    for case in selected:
        request, _ = driver.current.prepare_turn(case, 0, [])
        assert "criteria" not in request.context and request.context["previous_tasks"] is None
        assert request.context["current_request"] == case["turns"][0]["text"]
    private, _ = driver.current.prepare_turn(selected[0], 0, [])
    assert private.context["conversation_state"]["current_recipient"] == "ASSISTANT"
    assert private.context["conversation_state"]["default_recipient"] == "MERCHANT"


def test_local_attempt_cap_stops_before_provider_method_or_ledger_increment(monkeypatch):
    calls = []
    monkeypatch.setattr(driver.current.RecordedStreamingModel, "decide",
                        lambda self, **kwargs: calls.append(kwargs) or "reply")
    cls = driver.capped_model_class(100)
    model = object.__new__(cls)
    model.usage_ledger = {"used": 124}
    with pytest.raises(SupportFailure, match="EVALUATION_ALLOWANCE_EXHAUSTED"):
        model.decide()
    assert calls == [] and model.usage_ledger["used"] == 124
    model.usage_ledger["used"] = 123
    assert model.decide(marker="last allowed") == "reply" and len(calls) == 1
