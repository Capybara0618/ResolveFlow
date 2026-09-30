import pytest

from resolveflow.harness.actions import ActionRefusedError, validate_decision


def test_large_refused_proposal_gets_a_bounded_field_specific_notice_without_echoing_its_input():
    with pytest.raises(ActionRefusedError) as caught:
        validate_decision({"summary": "PRIVATE-MODEL-PAYLOAD" * 500})
    message = str(caught.value)
    assert "kind: Field required" in message
    assert "summary:" in message
    assert "PRIVATE-MODEL-PAYLOAD" not in message
    assert len(message) < 750
