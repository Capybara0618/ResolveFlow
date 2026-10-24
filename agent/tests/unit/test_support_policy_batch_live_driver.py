"""Keep criteria out of generation and bound new provider requests before transmission."""

import pytest
from scripts import accept_support_policy_batch_live_v1 as driver

from resolveflow.support.protocol import SupportFailure


def test_three_cases_prepare_scoped_requests_without_gold():
    cases = driver.cases()
    assert len(cases) == 3
    for case in cases:
        req, history = driver.current.prepare_turn(case, 0, [])
        assert "criteria" not in req.context and len(history) == 1
    assert cases[0]["snapshot"]["input_without_deadline"]["merchant_id"] != (
        cases[1]["snapshot"]["input_without_deadline"]["merchant_id"])


def test_batch_cap_stops_before_new_provider_transmission(monkeypatch):
    sent = []
    monkeypatch.setattr(driver.current.RecordedStreamingModel, "decide", lambda self, **kw: sent.append(kw))
    model = object.__new__(driver.capped_model_class(200))
    model.usage_ledger = {"used": 218}
    with pytest.raises(SupportFailure, match="EVALUATION_ALLOWANCE_EXHAUSTED"):
        model.decide()
    assert not sent and model.usage_ledger["used"] == 218
