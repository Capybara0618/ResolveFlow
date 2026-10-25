"""Final acceptance measures actual state and enforces a finite provider allowance."""

import pytest
from scripts import accept_customer_final_v1 as driver

from resolveflow.support.protocol import SupportFailure
from tests.unit.test_customer_agent_eval_v2 import completed


def test_eleven_fixed_turns_keep_criteria_out_of_prompts_and_tenant_binding():
    cases = driver.cases()
    assert [len(c["turns"]) for c in cases] == [5, 3, 3]
    requests = [driver.current.prepare_turn(c, 0, [])[0] for c in cases]
    assert requests[0].merchant_id != requests[2].merchant_id
    assert all("criteria" not in str(r.model_dump()) for r in requests)
    first = completed(requests[0])
    later, archive = driver.current.prepare_turn(cases[0], 1, [first])
    assert later.context["previous_customer_memory"] == first["answer"]["customer_memory"]
    assert len([m for m in archive if m["author"] == "ASSISTANT"]) == 1


def test_allowance_is_checked_before_another_provider_request(monkeypatch):
    sent = []
    monkeypatch.setattr(driver.current.RecordedStreamingModel, "decide", lambda self, **kwargs: sent.append(kwargs))
    model = object.__new__(driver.capped_model_class(100))
    model.usage_ledger = {"used": 140}
    with pytest.raises(SupportFailure, match="EVALUATION_ALLOWANCE_EXHAUSTED"):
        model.decide()
    assert sent == [] and model.usage_ledger["used"] == 140
