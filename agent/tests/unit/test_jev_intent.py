import json

import httpx
import pytest

from resolveflow.support.jev import JevClient, JevConfig, JevError
from resolveflow.support.jev_intent import OPTIONS, IntentPolicy, build_intent_request, intent_decision


def packet():
    return {"current_request": "退款先不要了，帮我写商家核查摘要，先别发送。", "recent_messages": [],
            "orchestration": {"phase": "CHECK_REQUEST", "request_check": {"tasks": [
                {"task_id": "t1", "quote": "退款先不要了"},
                {"task_id": "t2", "quote": "帮我写商家核查摘要，先别发送。"}]}},
            "proposed_goal": "should-not-anchor", "observations": [{"status": "LOST"}], "expected": "never-send"}


def answer(choice, confidence=.95):
    return {"type": "choice", "choice": choice, "confidence": confidence,
            "probabilities": {key: float(key == choice) for key in OPTIONS}}


def result(**updates):
    return {"model": "jev-1.14.0", "answers": {"purpose_0": answer("DECLINED"),
                                               "purpose_1": answer("MERCHANT_REVIEW")},
            "usage": {"input_tokens": 400, "output_tokens": 60}, **updates}


def test_choice_batch_validates_all_siblings_and_preserves_usage():
    body = build_intent_request(JevConfig(), packet())
    client = JevClient(JevConfig(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=result())))
    response = client.evaluate_choices(body)
    decision = intent_decision(packet(), response, IntentPolicy())
    assert [x["purpose"] for x in decision["assessments"]] == ["DECLINED", "MERCHANT_REVIEW"]
    assert [x["quote"] for x in decision["assessments"]] == [t["quote"] for t in packet()["orchestration"][
        "request_check"]["tasks"]]
    assert response["usage"]["input_tokens"] == 400


def test_request_contains_no_proposed_goal_business_fact_or_gold():
    body = build_intent_request(JevConfig(), packet())
    text = json.dumps(body, ensure_ascii=False)
    assert "should-not-anchor" not in text and "LOST" not in text and "never-send" not in text
    assert len(body["questions"]) == 2 and set(body["questions"]["purpose_0"]["criteria"]) == set(OPTIONS)


@pytest.mark.parametrize("confidence,choice", [(.69, "MERCHANT_REVIEW"), (.99, "UNCLEAR")])
def test_low_confidence_or_unclear_falls_back_for_the_whole_batch(confidence, choice):
    response = result()
    response["answers"]["purpose_1"] = answer(choice, confidence)
    assert intent_decision(packet(), response, IntentPolicy()) is None


@pytest.mark.parametrize("change", ["missing", "extra", "bad-option", "invalid-probability"])
def test_invalid_provider_choice_never_becomes_an_operation(change):
    response = result()
    if change == "missing":
        response["answers"].pop("purpose_1")
    elif change == "extra":
        response["answers"]["unexpected"] = answer("PREPARE_REFUND")
    elif change == "bad-option":
        response["answers"]["purpose_1"]["choice"] = "SUBMIT_REFUND"
    else:
        response["answers"]["purpose_1"]["probabilities"]["MERCHANT_REVIEW"] = 2
    client = JevClient(JevConfig(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    with pytest.raises((JevError, ValueError)):
        client.evaluate_choices(build_intent_request(JevConfig(), packet()))


def test_quote_provenance_and_duplicate_tasks_checked_before_transmission():
    value = packet()
    value["orchestration"]["request_check"]["tasks"][1]["quote"] = "虚构用户同意退款"
    with pytest.raises(ValueError):
        build_intent_request(JevConfig(), value)
    value = packet()
    value["orchestration"]["request_check"]["tasks"][1]["task_id"] = "t1"
    with pytest.raises(ValueError):
        build_intent_request(JevConfig(), value)


def test_frozen_fixture_has_balanced_splits_and_separate_multi_task_labels():
    from pathlib import Path

    fixture = json.loads((Path(__file__).parents[1] / "fixtures/jev-intent-v1.json").read_bytes())
    assert len(fixture["cases"]) == 30
    assert sum(c["split"] == "dev" for c in fixture["cases"]) == 10
    assert sum(len(c["expected"]) for c in fixture["cases"]) == 32
    for case in fixture["cases"]:
        body = build_intent_request(JevConfig(), case["packet"])
        assert "expected" not in body["state"] and len(body["questions"]) == len(case["expected"])
