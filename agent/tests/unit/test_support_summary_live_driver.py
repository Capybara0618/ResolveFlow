"""Keep live acceptance inputs fixed and injected mock prefix out of provider counts."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from scripts import accept_support_summary_live_v1 as driver

from resolveflow.support.protocol import SupportFailure


def test_five_turns_keep_quality_criteria_out_of_provider_context():
    cases = driver.cases()
    assert [len(c["turns"]) for c in cases] == [3, 2]
    for case in cases:
        request, history = driver.current.prepare_turn(case, 0, [])
        assert "criteria" not in request.context and len(history) == 1


def test_cohort_attempt_cap_blocks_before_transmission(monkeypatch):
    calls = []
    monkeypatch.setattr(driver.current.RecordedStreamingModel, "decide", lambda self, **kw: calls.append(kw))
    model = object.__new__(driver.capped_model_class(100))
    model.usage_ledger = {"used": 124}
    with pytest.raises(SupportFailure):
        model.decide()
    assert not calls and model.usage_ledger["used"] == 124


def test_injected_prefix_is_mock_with_zero_ledger_change_and_live_tail_cap(monkeypatch):
    transmissions = []
    monkeypatch.setattr(driver.current.RecordedStreamingModel, "decide",
                        lambda self, **kw: transmissions.append(kw))
    prefix = [{"kind": "TURN_UNDERSTANDING"}, {"kind": "RESPOND"}]
    model = driver.injected_model_class(100, prefix)(usage={"used": 100}, save=lambda _: None,
        provider="deepseek", model_id="deepseek-flash", endpoint="https://synthetic.invalid", api_key="test-only")
    kwargs = {"system": "test", "messages": [], "max_output_tokens": 128}
    replies = [model.decide(**kwargs), model.decide(**kwargs)]
    assert all(r.mode == "mock" and r.usage.total_tokens == 0 for r in replies)
    assert len(model.prefix_records) == 2 and prefix[0]["kind"] == "TURN_UNDERSTANDING"
    assert model.usage_ledger["used"] == 100 and not transmissions
    model.usage_ledger["used"] = 106
    with pytest.raises(SupportFailure):
        model.decide(**kwargs)
    assert not transmissions


def test_mixed_prefix_reaches_review_and_keeps_business_publication_checks(monkeypatch):
    from resolveflow.harness.model import ModelReply

    source = driver.read_json(driver.ROOT / "reports/customer-agent-close-v1/runtime-results.json")
    row = next(r for r in source["rows"] if (r["id"], r["turn"]) == ("M02", 2))
    req = driver.SupportInput.model_validate({**row["input"],
        "deadline_at": datetime.now(UTC) + timedelta(seconds=120)})
    prefix = deepcopy([m["decision"] for m in row["models"][:3]])
    prefix[-1]["handoff_reason"] = {"customer_quotes": ["新发现耳机外壳有损坏"]}
    tail = [{"kind": "REVIEW_GOAL", "task_id": "t2", "previous_goal": "PREPARE_REFUND",
             "goal": "MERCHANT_REVIEW", "operation_request": "能帮我整理一段给商家的摘要吗？先不要发出去。",
             "reason": "客户请求人工摘要"}, prefix[-1]]
    monkeypatch.setattr(driver.current.RecordedStreamingModel, "decide",
                        lambda self, **kw: ModelReply(decision=tail.pop(0), mode="live"))
    model = driver.injected_model_class(100, prefix)(usage={"used": 100}, save=lambda _: None,
        provider="deepseek", model_id="deepseek-flash", endpoint="https://synthetic.invalid", api_key="test-only")
    agent = driver.SupportAgent(req, model, driver.SavedSources(row["calls"]), architecture="orchestrated-v1",
                                provider_capacity=32768)
    result = agent.run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert len(agent.orchestration.goal_reviews) == 1 and not tail
    assert "新发现耳机外壳有损坏" in result["answer"]["handoff_summary"]
    assert "refund_summary" not in result["answer"] and len(model.prefix_records) == 3
