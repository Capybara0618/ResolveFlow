"""Readiness only: never instantiate a paid model or run a quality evaluation."""

import datetime as dt
from copy import deepcopy

import pytest
from scripts import customer_agent_readiness as runner


def test_frozen_scenarios_preflight_without_model_or_database():
    plan, cases = runner.load_plan()
    assert plan["formal_evaluation_executed"] is False
    assert len(cases) == 12 and sum(len(c["turns"]) for c in cases) == 36
    for case in cases:
        req, archive = runner.prepare_turn(case, 0, [])
        assert req.context["current_request"] == case["turns"][0]["text"]
        assert "criteria" not in str(req.model_dump())
        assert req.context["policy_manifest"]["merchant_id"] == req.merchant_id
        assert archive[-1]["text"] == req.context["current_request"]


def test_next_turn_uses_actual_answer_and_rejects_foreign_or_skipped_results():
    _, cases = runner.load_plan()
    case = cases[0]
    req, _ = runner.prepare_turn(case, 0, [])
    result = {"run_id": req.run_id, "conversation_id": req.conversation_id, "input_version": req.input_version,
              "status": "SUCCEEDED", "answer": {"text": "实际生成的回答，不来自金标。", "task_state": {
                  "origin": "MODEL", "tasks": []}}}
    second, archive = runner.prepare_turn(case, 1, [result])
    assert second.conversation_id == req.conversation_id and second.run_id != req.run_id
    assert any(m["text"] == result["answer"]["text"] for m in archive)
    assert second.context["previous_tasks"]["input_version"] == req.input_version
    foreign = {**result, "conversation_id": "00000000-0000-4000-8000-000000000099"}
    with pytest.raises(ValueError, match="completed turn identity"):
        runner.prepare_turn(case, 1, [foreign])
    with pytest.raises(ValueError, match="completed turns"):
        runner.prepare_turn(case, 2, [result])
    assert second.deadline_at > dt.datetime.now(dt.UTC)


def test_long_history_keeps_original_archive_and_exposes_pagination():
    _, cases = runner.load_plan()
    case = next(c for c in cases if c["id"] == "D09")
    req, archive = runner.prepare_turn(case, 0, [])
    assert len(archive) > 20 and len(req.context["history"]) == 20
    assert req.context["history_before"] == req.context["history"][0]["sequence"]
    assert any("纠正" in m["text"] for m in archive)


def test_changed_source_or_case_is_rejected_by_frozen_manifest(tmp_path):
    plan, _ = runner.load_plan()
    changed = deepcopy(plan)
    changed["files"]["agent/src/resolveflow/support/engine.py"] = "0" * 64
    path = tmp_path / "manifest.json"
    path.write_text(runner.json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen source changed"):
        runner.load_plan(path)
