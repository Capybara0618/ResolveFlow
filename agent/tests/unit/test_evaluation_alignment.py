"""Calibration must follow the business contract and cannot weaken evidence checks."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from resolveflow.contracts.reviewer_input import ReviewerInput  # noqa: E402
from resolveflow.harness.context import ContextBuilder, OverflowRefusedError  # noqa: E402
from resolveflow.harness.facts import FactsView  # noqa: E402
from scripts.evaluation.dataset import check_input, digest, export_case, read, validate  # noqa: E402
from scripts.evaluation.scoring import score_agent  # noqa: E402

ALIGNED = ROOT / "evals/aligned-v2"


def test_aligned_inputs_are_revision_snapshots_and_reference_only_reads():
    assert validate(ALIGNED)["agent_cases"] == 32
    case = export_case("A13A", ALIGNED)
    snapshot = ReviewerInput.model_validate(case["review_context"])
    wire = case["backend"]["evidence"]
    assert set(wire) == {"case_id", "input_revision", "evidence"}
    assert {m.evidence_id for m in snapshot.materials} == {r["observation_id"] for r in wire["evidence"]}
    assert all(set(r) == {"observation_id", "source_ref", "source_version", "content_hash"} for r in wire["evidence"])


def test_overflow_has_size_diagnostics_without_material_text():
    with pytest.raises(OverflowRefusedError) as caught:
        ContextBuilder(system_prompt="rules", provider_capacity=500).build(
            run_id="r",
            case_id="c",
            step=1,
            input_revision=1,
            line_id="l",
            description="private material" * 100,
            manifest_id="m",
            view=FactsView(),
            observations=[],
            tool_schema={},
        )
    details = caught.value.diagnostics
    assert details["mandatory_tokens"] > details["cap"]
    assert details["layer_bytes"]["P1"] > details["layer_bytes"]["P0"]
    assert details["token_count_mode"] == "ESTIMATED_UTF8_BYTES"  # noqa: S105
    assert "private material" not in str(details)


def _result(fields):
    obs = SimpleNamespace(
        observation_id="o",
        tool_name="get_order_context",
        error=None,
        source_ref="line:l",
        source_version="1",
        content_hash="a" * 64,
        result=fields,
    )
    ref = SimpleNamespace(
        **{k: getattr(obs, k) for k in ("observation_id", "source_ref", "source_version", "content_hash")}
    )
    return SimpleNamespace(
        completed=True,
        decision=SimpleNamespace(kind="PROPOSE", recommended_action="REFUND", evidence_refs=[ref], policy_refs=[]),
        observations=[obs],
    )


GOLD = {
    "allowed_actions": ["REFUND"],
    "forbidden_actions": [],
    "must_tools": ["get_order_context"],
    "must_rules": [],
    "support_requirements": [
        {
            "id": "delivered",
            "any_of": [
                {"tool": "get_order_context", "fields": {"fulfillment_status": "DELIVERED"}},
                {"tool": "get_shipment_trace", "fields": {"status": "DELIVERED"}},
            ],
        }
    ],
}


def test_equivalent_delivered_fact_does_not_require_redundant_carrier_read():
    assert score_agent(_result({"fulfillment_status": "DELIVERED"}), GOLD)["joint_correct"]


@pytest.mark.parametrize("fields", [{}, {"fulfillment_status": "UNKNOWN"}, {"fulfillment_status": "IN_TRANSIT"}])
def test_reading_a_tool_without_required_fact_is_not_support(fields):
    score = score_agent(_result(fields), GOLD)
    assert score["missing_support"] == ["delivered"] and not score["joint_correct"]


def test_equivalent_source_still_needs_valid_citation():
    result = _result({"fulfillment_status": "DELIVERED"})
    result.decision.evidence_refs[0].content_hash = "b" * 64
    assert not score_agent(result, GOLD)["joint_correct"]


def test_support_gold_cannot_leak_into_model_inputs():
    with pytest.raises(ValueError, match="Gold-only"):
        check_input({"review_context": {"support_requirements": []}})


def test_frozen_v1_actions_and_policy_gold_are_preserved():
    old = read("gold/agent.json")
    new = read("gold/agent.json", ALIGNED)
    for key in old:
        for field in ("allowed_actions", "forbidden_actions", "must_rules"):
            assert old[key][field] == new[key][field]
    for name in ("policies/bundles.json", "rag/queries.json", "gold/rag.json"):
        assert digest(ROOT / "evals/current" / name) == digest(ALIGNED / name)


@pytest.mark.parametrize("change", ["wrong_hash", "refuted", "unregistered", "wrong_revision", "latest_refuted"])
def test_human_verification_requires_current_registered_source(change):
    case = export_case("A13A", ALIGNED)
    payload = deepcopy(case["backend"]["evidence"])
    result = _result({})
    source = result.observations[0]
    source.tool_name = "get_case_evidence"
    source.result = payload
    gold = {
        "allowed_actions": ["REFUND"],
        "forbidden_actions": [],
        "must_tools": ["get_case_evidence"],
        "must_rules": [],
        "support_requirements": [
            {"id": "human", "any_of": [{"tool": "get_case_evidence", "verification": "CONFIRMED"}]}
        ],
    }
    assert score_agent(result, gold, case=case)["joint_correct"]
    if change == "wrong_hash":
        payload["evidence"][-1]["content_hash"] = "0" * 64
    elif change == "refuted":
        case["review_context"]["materials"][-1]["verification_result"] = "REFUTED"
    elif change == "unregistered":
        payload["evidence"] = []
    elif change == "wrong_revision":
        payload["input_revision"] += 1
    else:
        later = deepcopy(case["review_context"]["materials"][-1])
        later.update(input_revision=3, evidence_id="later", verification_result="REFUTED")
        case["review_context"]["materials"].insert(0, later)
        case["input_revision"] = payload["input_revision"] = 3
    assert not score_agent(result, gold, case=case)["joint_correct"]


@pytest.mark.parametrize("change", ["future", "references", "body_hash"])
def test_calibration_rejects_invalid_dispatch_even_with_updated_file_hash(tmp_path, change):
    import json
    import shutil

    directory = tmp_path / "aligned"
    shutil.copytree(ALIGNED, directory)
    cases = read("agent/cases.json", directory)
    case = cases[0]
    if change == "future":
        case["review_context"]["materials"][0]["input_revision"] = 99
    elif change == "references":
        case["backend"]["evidence"]["evidence"][0]["content_hash"] = "0" * 64
    else:
        case["review_context"]["materials"][0]["content"] = "modified without source hash update"
    path = directory / "agent/cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    manifest = read("manifest.json", directory)
    manifest["files"]["agent/cases.json"] = digest(path)
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    replay = read("replay/manifest.json", directory)
    replay["dataset_manifest_sha256"] = digest(directory / "manifest.json")
    (directory / "replay/manifest.json").write_text(json.dumps(replay), encoding="utf-8")
    with pytest.raises(ValueError, match="Future revision|Evidence references|content hash mismatch"):
        validate(directory)
