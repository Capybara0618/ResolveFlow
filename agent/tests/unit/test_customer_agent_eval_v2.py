"""New frozen evaluation: actual preceding answers only, shared bounds and fixed scheduling."""

from copy import deepcopy

import pytest
from scripts import customer_agent_eval_v2 as runner
from scripts.evaluation.support_fixed_v2 import FixedSupportAgent

from resolveflow.harness.model import MockModelClient
from tests.unit.test_support_agent import Reads, answer, request


def completed(req, text="实际回答"):
    return {"run_id": req.run_id, "conversation_id": req.conversation_id,
            "input_version": req.input_version, "status": "SUCCEEDED", "answer": {
                "text": text, "task_state": {"origin": "MODEL", "tasks": []},
                "customer_memory": {"version": "support-claims-v1", "origin": "GROUNDED_CUSTOMER_CLAIMS",
                                    **{k: getattr(req, k) for k in ["conversation_id", "merchant_id", "customer_id",
                                                                  "line_id", "input_version"]}, "entries": []}}}


def test_dataset_retains_old_conditions_and_adds_pause_resume_conversations():
    cases = runner.load_cases()
    old = runner.read_json(runner.ROOT / "evals/customer-agent-readiness-v1/scenarios.json")["cases"]
    assert [{k: v for k, v in c.items() if k != "snapshot"} for c in cases[:12]] == old
    assert len(cases) == 14 and sum(len(c["turns"]) for c in cases) == 44
    assert all(len(c["turns"]) == 4 for c in cases[12:])


def test_actual_prior_answer_memory_and_scope_are_carried_without_gold():
    case = runner.load_cases()[12]
    first, _ = runner.prepare_turn(case, 0, [], "agent")
    actual = completed(first)
    second, archive = runner.prepare_turn(case, 1, [actual], "agent")
    assert second.context["previous_customer_memory"] == actual["answer"]["customer_memory"]
    assert any(m["text"] == "实际回答" for m in archive)
    assert "criteria" not in str(second.model_dump()) and "partition" not in str(second.model_dump())
    fixed, _ = runner.prepare_turn(case, 0, [], "fixed")
    assert fixed.conversation_id != first.conversation_id and fixed.run_id != first.run_id
    with pytest.raises(ValueError, match="identity"):
        runner.prepare_turn(case, 1, [actual], "fixed")


def test_failed_turn_keeps_last_success_memory_without_fabricating_answer():
    case = runner.load_cases()[12]
    one, _ = runner.prepare_turn(case, 0, [], "agent")
    actual = completed(one)
    two, _ = runner.prepare_turn(case, 1, [actual], "agent")
    failed = {**completed(two), "status": "FAILED", "answer": None, "reason": "INVALID_DECISION"}
    three, archive = runner.prepare_turn(case, 2, [actual, failed], "agent")
    assert three.context["previous_customer_memory"] == actual["answer"]["customer_memory"]
    assert len([m for m in archive if m["author"] == "ASSISTANT"]) == 1


def test_foreign_memory_is_not_imported_from_a_completed_envelope():
    case = runner.load_cases()[12]
    one, _ = runner.prepare_turn(case, 0, [], "agent")
    actual = completed(one)
    actual["answer"]["customer_memory"]["line_id"] = "foreign"
    with pytest.raises(ValueError, match="memory scope"):
        runner.prepare_turn(case, 1, [actual], "agent")


def test_fixed_schedule_uses_same_context_and_real_model_only_for_query_and_answer():
    model = MockModelClient(script=[{"kind": "SEARCH_POLICY", "query": "丢失处理", "top_k": 3},
                                   answer(citations=["O1", "P1"])])
    reads = Reads()
    result = FixedSupportAgent(request(), model, reads).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 2
    assert reads.calls == [("get_order_context", {}), ("get_shipment_trace", {}), ("get_support_guide", {}),
                           ("search_policy", {"query": "丢失处理", "top_k": 3})]
    assert model.packets[0]["fixed_stage"] == "QUERY" and model.packets[1]["fixed_stage"] == "ANSWER"


def test_fixed_stage_cannot_accept_unplanned_model_reads_or_publish_early_answer():
    model = MockModelClient(script=[answer(citations=[])])
    result = FixedSupportAgent(request(), model, Reads()).run()
    assert result["status"] == "FAILED" and result["reason"] == "FIXED_QUERY_REQUIRED"
    assert result["answer"] is None and model.calls == 1


def test_freeze_checks_code_changes_and_never_replaces_prior_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    runner.freeze(path)
    plan, cases = runner.load_plan(path)
    assert len(cases) == 14 and plan["groups"] == ["agent", "fixed"]
    with pytest.raises(FileExistsError):
        runner.freeze(path)
    wrong = deepcopy(plan)
    wrong["files"]["scripts/customer_agent_eval_v2.py"] = "0" * 64
    other = tmp_path / "wrong.json"
    runner.write_new(other, wrong)
    with pytest.raises(ValueError, match="frozen source changed"):
        runner.load_plan(other)
