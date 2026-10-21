"""A separate frozen two-turn confirmation cannot mutate or rerun the old cohort."""

import pytest
from scripts import customer_agent_annotation_check_v1 as check


def test_two_original_inputs_are_frozen_separately_and_detect_tampering(tmp_path):
    cases = check.load_cases()
    assert len(cases) == 2 and cases[0]["source_case"] == "D01" and cases[1]["source_case"] == "D02"
    assert cases[0]["input_without_deadline"]["run_id"] != cases[1]["input_without_deadline"]["run_id"]
    original = check.prior.PLAN.read_bytes()
    path = tmp_path / "manifest.json"
    check.freeze(path)
    plan = check.load_plan(path)
    assert plan["autonomous_turns"] == 2
    plan["files"]["agent/src/resolveflow/support/engine.py"] = "0" * 64
    changed = tmp_path / "changed.json"
    check.preparation.write_new(changed, plan)
    with pytest.raises(ValueError, match="frozen source changed"):
        check.load_plan(changed)
    assert check.prior.PLAN.read_bytes() == original


def test_scoped_loader_is_restored_after_single_turn_driver_error(monkeypatch, tmp_path):
    original, loader = check.driver.PLAN, check.driver.load_plan

    def reject(output, usage):
        assert check.driver.PLAN == check.PLAN and check.driver.load_plan is check.load_plan
        raise ValueError("synthetic before model")

    monkeypatch.setattr(check.driver, "evaluate", reject)
    with pytest.raises(ValueError, match="synthetic before model"):
        check.execute(tmp_path / "unused.json", tmp_path / "usage.json")
    assert check.driver.PLAN == original and check.driver.load_plan is loader
    assert not list(tmp_path.iterdir())
