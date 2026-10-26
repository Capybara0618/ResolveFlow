"""Authorization metrics must follow observed actions, not historical totals."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_authorization import inspect_record, scenario_manifest


def valid_record():
    return {"scenario": "V3", "trial": 0, "old_authorization_status": "REVOKED",
            "old_command_count": 0, "old_outbox_count": 0, "control_command_count": 1, "control_outbox_count": 1,
            "control_status": "CONSUMED", "old_revision": 1, "final_revision": 2,
            "attempt_records": [{"action": "CONSUME", "dispatched": False, "reason": "REVOKED"}]}


def test_count_rejections_from_observed_action_and_reject_dispatch():
    assert inspect_record(valid_record())["consume_rejections"] == 1
    bad = valid_record()
    bad["attempt_records"][0]["dispatched"] = True
    with pytest.raises(AssertionError):
        inspect_record(bad)


def test_no_command_must_also_mean_no_refund_outbox():
    for key, value in (("old_outbox_count", 1), ("control_outbox_count", 0), ("final_revision", 1)):
        with pytest.raises(AssertionError):
            inspect_record({**valid_record(), key: value})


def test_each_scenario_spec_has_its_actual_distinct_actions():
    specs = scenario_manifest()
    assert len(specs) == 9
    assert specs["V7"]["callback"] == "STALE"
    assert specs["V8"]["old_attempts"] == 2
    assert specs["consume-wins"]["rejected_actions"] == ["UPDATE_INPUT", "CANCEL"]
