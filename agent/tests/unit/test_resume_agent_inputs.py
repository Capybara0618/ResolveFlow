from scripts.resume_agent_inputs import corrected_cases


def case(events):
    return {
        "id": "synthetic",
        "backend": {
            "order": {"fulfillment_status": "NOT_SHIPPED"},
            "shipment": {"status": "IN_TRANSIT", "carrier_conclusion": "IN_TRANSIT", "events": events},
        },
    }


def test_empty_synthetic_default_is_corrected_without_mutating_parent():
    original = case([])
    result, changed = corrected_cases([original])
    assert changed == ["synthetic"]
    assert result[0]["backend"]["shipment"]["status"] == "NOT_SHIPPED"
    assert result[0]["backend"]["shipment"]["carrier_conclusion"] == "UNKNOWN"
    assert original["backend"]["shipment"]["status"] == "IN_TRANSIT"


def test_actual_conflicting_events_are_preserved():
    original = case([{"code": "CARRIER_IN_TRANSIT"}])
    result, changed = corrected_cases([original])
    assert changed == []
    assert result == [original]
