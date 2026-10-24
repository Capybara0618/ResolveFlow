"""Four fixed real turns keep quality criteria out of prompts and cap transmissions."""

import pytest
from scripts import accept_support_goal_confirm_v1 as driver

from resolveflow.support.protocol import SupportFailure


def test_three_conversations_four_turns_keep_gold_out_of_prompt():
    selected = driver.cases()
    assert [len(c["turns"]) for c in selected] == [2, 1, 1]
    for case in selected:
        request, history = driver.current.prepare_turn(case, 0, [])
        assert "criteria" not in request.context and len(history) == 1
        assert request.context["previous_tasks"] is None


def test_cap_blocks_before_transmission_or_increment(monkeypatch):
    calls = []
    monkeypatch.setattr(driver.current.RecordedStreamingModel, "decide", lambda self, **kw: calls.append(kw))
    cls = driver.capped_model_class(2318)
    model = object.__new__(cls)
    model.usage_ledger = {"used": 2338}
    with pytest.raises(SupportFailure):
        model.decide()
    assert not calls and model.usage_ledger["used"] == 2338
