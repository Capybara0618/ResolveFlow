"""Fixed multi-turn inputs keep criteria out of prompts and preserve the attempt cap."""

import pytest
from scripts import accept_support_close_v1 as driver

from resolveflow.support.protocol import SupportFailure


def test_three_conversations_ten_turns_start_without_gold_or_fabricated_history():
    selected = driver.cases()
    assert [len(c["turns"]) for c in selected] == [4, 3, 3]
    for case in selected:
        request, history = driver.current.prepare_turn(case, 0, [])
        assert "criteria" not in request.context and len(history) == 1
        assert request.context["previous_tasks"] is None


def test_cap_blocks_before_transmission_or_increment(monkeypatch):
    calls = []
    monkeypatch.setattr(driver.current.RecordedStreamingModel, "decide", lambda self, **kw: calls.append(kw))
    cls = driver.capped_model_class(100)
    model = object.__new__(cls)
    model.usage_ledger = {"used": 140}
    with pytest.raises(SupportFailure):
        model.decide()
    assert not calls and model.usage_ledger["used"] == 140
