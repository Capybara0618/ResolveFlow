import json

import pytest
from scripts import customer_agent_live_v3 as runner


def test_regression_keeps_original_business_inputs_and_criteria():
    plan = runner.verify_plan()
    assert plan["version"] == "customer-agent-live-v3" and len(plan["cases"]) == 12
    assert all("conversation_state" not in c["input_without_deadline"]["context"] for c in plan["cases"])


def test_changed_business_fact_is_rejected_before_new_model_calls(tmp_path, monkeypatch):
    plan = runner.verify_plan()
    plan["cases"][0]["input_without_deadline"]["context"]["current_request"] = "changed after freezing"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(runner, "PLAN", path)
    with pytest.raises(ValueError, match="business inputs"):
        runner.verify_plan()
