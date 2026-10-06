import copy

import pytest
from scripts.evaluation.semantic_review import message_of, validate_agent, validate_policy

PAYLOAD = {"documents": [{"source_id": "s", "blocks": [{"id": "b1"}]}]}
LABEL = {
    "answerability": "ANSWERABLE",
    "required": [{"source_id": "s", "block_id": "b1"}],
    "rationale": "Only provided scope applies.",
    "uncertain": False,
}


def test_semantic_labels_do_not_approve_human_gold():
    value = validate_policy(LABEL, PAYLOAD)
    assert "review" not in value and "official_quality" not in value


def test_real_sdk_message_is_validated_before_provider_accounting():
    from resolveflow.harness.live_model import LiveModelClient

    client = LiveModelClient(endpoint="https://example.org", model_id="deepseek-flash")
    body = client.prepare_request(system="JSON", messages=[message_of('{"query":"退款"}')], max_output_tokens=1024)
    assert body["messages"][1] == {"role": "user", "content": '{"query":"退款"}'}
    assert client.calls == 0 and not client.requests


def test_missing_auxiliary_uncertainty_is_unspecified_not_false_or_gold():
    value = {k: v for k, v in LABEL.items() if k != "uncertain"}
    parsed = validate_policy(value, PAYLOAD)
    assert parsed["uncertain"] is None and "review" not in parsed


@pytest.mark.parametrize("mutation", ["unknown", "duplicate", "empty", "bool", "category"])
def test_model_label_protocol_rejects_invalid_or_wrong_scope(mutation):
    value = copy.deepcopy(LABEL)
    if mutation == "unknown":
        value["required"][0]["source_id"] = "other"
    elif mutation == "duplicate":
        value["required"] *= 2
    elif mutation == "empty":
        value["required"] = []
    elif mutation == "bool":
        value["uncertain"] = "false"
    else:
        value["answerability"] = "APPROVED"
    with pytest.raises(ValueError):
        validate_policy(value, PAYLOAD)


def test_incomplete_candidate_must_not_receive_semantic_score():
    payload = {"candidates": [{"candidate": "X", "completed": True}, {"candidate": "Y", "completed": False}]}
    row = {
        "candidate": "X",
        "factual_support": True,
        "policy_application": True,
        "action_reason_alignment": True,
        "uncertain": False,
        "rationale": "Supported",
    }
    assert validate_agent({"evaluations": [row]}, payload)
    with pytest.raises(ValueError):
        validate_agent({"evaluations": [row, {**row, "candidate": "Y"}]}, payload)
