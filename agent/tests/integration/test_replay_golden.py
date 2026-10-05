"""Five independently persisted synthetic outcomes, replayed through the production SDK."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from resolveflow.harness.live_model import _decision_of
from resolveflow.harness.model import MockModelClient
from resolveflow.replay.export import export_run
from resolveflow.replay.pack import ReplayMiss, UnsupportedRecord, read_pack, write_pack
from resolveflow.replay.strict import ReplayMismatch, strict_replay
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.runs import RunStore
from resolveflow.runtime.worker import RunWorker

from tests.integration.test_run_worker import CASE_DISPATCHER, RUN_ID, a_run
from tests.unit.test_harness_loop import StubTools, failed_observation, observation, propose, read

LOST_SOURCE = observation("get_shipment_trace", carrier_conclusion="LOST", status="LOST")
LOST_REFS = [{k: getattr(LOST_SOURCE, k) for k in
              ("observation_id", "source_ref", "source_version", "content_hash")}]

CASES: dict[str, tuple[list[dict[str, Any]], tuple[Any, ...], str]] = {
    "manual_review": ([propose("MANUAL_REVIEW", summary="synthetic review")], (), "PROPOSAL"),
    "question": ([{"kind": "ASK_CUSTOMER", "questions": [
        {"question_id": "q1", "field": "shipment_photo", "prompt": "Please provide a photo"}],
        "reason_codes": ["NEEDS_EVIDENCE"]}], (), "QUESTION"),
    "escalation": ([{"kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN"],
                     "summary": "Synthetic manual escalation"}], (), "FAILED"),
    "read_then_review": ([read("get_order_context"), propose("MANUAL_REVIEW", summary="read line")],
                         (observation(),), "PROPOSAL"),
    "read_then_question": ([read("get_order_context"), {"kind": "ASK_CUSTOMER", "questions": [
        {"question_id": "q1", "field": "package_photo", "prompt": "Please send the package photo"}],
        "reason_codes": ["NEEDS_EVIDENCE"]}], (observation(),), "QUESTION"),
    "bound_question_repair": ([{"kind": "ASK_CUSTOMER", "questions": [
        {"question_id": "q1", "field": "order_id", "prompt": "Please provide order id"}],
        "reason_codes": ["NEEDS_EVIDENCE"]}, read("get_order_context"), propose("MANUAL_REVIEW")],
        (observation(),), "PROPOSAL"),
    "non_json_repair": ([_decision_of("SYNTHETIC non-JSON answer"), propose("MANUAL_REVIEW")], (), "PROPOSAL"),
    "non_json_exhausted": ([_decision_of("SYNTHETIC non-JSON answer")] * 2, (), "FAILED"),
    "transient_tool_repair": ([read("get_order_context")] * 2 + [propose("MANUAL_REVIEW")],
                              (TimeoutError("synthetic timeout"), observation()), "PROPOSAL"),
    "transient_tool_exhausted": ([read("get_order_context")] * 3,
                                 (TimeoutError("synthetic timeout"), TimeoutError("synthetic timeout")), "FAILED"),
    "claim_repair": ([read("get_shipment_trace"),
                      propose("MANUAL_REVIEW", summary="承运商已确认正常签收。", evidence_refs=LOST_REFS),
                      propose("MANUAL_REVIEW", summary="承运商确认丢失，建议人工核查。", evidence_refs=LOST_REFS)],
                     (LOST_SOURCE,), "PROPOSAL"),
    "malformed_tool_handover": ([read("get_order_context"),
                                propose("MANUAL_REVIEW", summary="订单数据异常，请人工检查。")],
                               (failed_observation(code="TOOL_RESULT_INVALID"),), "PROPOSAL"),
}


@pytest.mark.parametrize("name", CASES)
def test_committed_golden_pack(name: str) -> None:
    root = Path(__file__).resolve().parents[3]
    directory = root / "evals" / "replay" / "calibration-v9" / name
    assert strict_replay(directory)["status"] == "MATCH"


@pytest.mark.parametrize("name", CASES)
def test_golden_trajectory(agent_db: Database, tmp_path: Path, name: str) -> None:
    script, observations, terminal = CASES[name]
    RunStore(agent_db).queue(a_run(description=f"SYNTHETIC_REPLAY: {name}"), caller=CASE_DISPATCHER)
    investigate = build_investigation(
        database=agent_db, config=DeploymentConfig(mode="mock"),
        model=MockModelClient(script=script), tools=StubTools(*observations),
    )
    outcome = RunWorker(agent_db, investigate, recoverable=True).run_once()
    assert outcome is not None and outcome.callback_kind == terminal
    with agent_db.connection() as connection:
        saved = connection.execute("SELECT budget_spent FROM agent_run WHERE run_id=%s", (RUN_ID,)).fetchone()
    assert saved["budget_spent"] == outcome.result.spend.as_dict()
    output_root = os.environ.get("RESOLVEFLOW_REPLAY_GOLDEN_DIR")
    directory = Path(output_root) / name if output_root else tmp_path / name
    export_run(agent_db, RUN_ID, directory)
    replay = strict_replay(directory)
    assert replay["status"] == "MATCH"
    assert replay["callback_kind"] == terminal
    if name == "read_then_review":
        document = read_pack(directory)
        assert document["tool_calls"][0]["request_body"] == {"name": "get_order_context", "arguments": {}}
        document["tool_calls"] = []
        write_pack(tmp_path / "missing-tool", document)
        with pytest.raises(ReplayMiss, match="tool-0"):
            strict_replay(tmp_path / "missing-tool")
        document = read_pack(directory)
        document["model_calls"][0]["request_hash"] = "0" * 64
        write_pack(tmp_path / "different-request", document)
        with pytest.raises(ReplayMismatch, match="model-0"):
            strict_replay(tmp_path / "different-request")
        document = read_pack(directory)
        document["model_calls"][0]["response"]["mode"] = "live"
        write_pack(tmp_path / "unsupported", document)
        with pytest.raises(UnsupportedRecord):
            strict_replay(tmp_path / "unsupported")
