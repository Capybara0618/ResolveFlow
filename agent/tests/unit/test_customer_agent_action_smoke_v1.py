"""New smoke uses unchanged questions, fresh identities and only a scoped evaluation adapter."""

from copy import deepcopy

import pytest
from scripts import customer_agent_action_smoke_v1 as smoke
from scripts import customer_agent_eval_v2 as original


def test_three_conversations_preserve_six_original_turns_and_use_fresh_identities():
    cases = smoke.load_cases()
    assert len(cases) == 3 and sum(len(c["turns"]) for c in cases) == 6
    old = {c["id"]: c for c in original.load_cases()}
    for case in cases:
        current, _ = original.prepare_turn(case, 0, [], "agent")
        historical, _ = original.prepare_turn(old[case["source_case"]], 0, [], "agent")
        assert current.run_id != historical.run_id and current.conversation_id != historical.conversation_id
        assert current.context["current_request"] == historical.context["current_request"]
        assert "criteria" not in str(current.model_dump())


def test_new_freeze_detects_source_changes_and_does_not_overwrite_old_manifest(tmp_path):
    before = original.PLAN.read_bytes()
    path = tmp_path / "manifest.json"
    smoke.freeze(path)
    plan, cases = smoke.load_plan(path)
    assert len(cases) == 3 and plan["turns_per_group"] == 6
    wrong = deepcopy(plan)
    wrong["files"]["agent/src/resolveflow/support/engine.py"] = "0" * 64
    other = tmp_path / "invalid.json"
    original.write_new(other, wrong)
    with pytest.raises(ValueError, match="frozen source changed"):
        smoke.load_plan(other)
    with pytest.raises(FileExistsError):
        smoke.freeze(path)
    assert original.PLAN.read_bytes() == before


def test_evaluation_adapter_restores_driver_globals_even_on_error(monkeypatch, tmp_path):
    old_plan, old_loader = original.PLAN, original.load_plan
    called = []

    def fake_evaluate(output, usage):
        assert original.PLAN == smoke.PLAN and original.load_plan is smoke.load_plan
        called.append((output, usage))
        raise ValueError("synthetic driver failure before any model")

    monkeypatch.setattr(original, "evaluate", fake_evaluate)
    with pytest.raises(ValueError, match="synthetic driver failure"):
        smoke.execute(tmp_path / "unused.json", tmp_path / "unused-usage.json")
    assert len(called) == 1 and original.PLAN == old_plan and original.load_plan is old_loader
    assert not list(tmp_path.iterdir())
