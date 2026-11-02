import copy
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import jev_intent_fifty as study

from resolveflow.support.jev import JevConfig
from resolveflow.support.jev_intent import build_intent_request


def test_all_original_fifty_turns_and_customer_history_are_preserved():
    fixture = study.load_fixture()
    assert len(fixture["cases"]) == 50
    assert sum(len(c["expected"]) for c in fixture["cases"]) == 62
    assert [c["id"] for c in fixture["cases"] if c["boundary_case"]] == ["Q23-T1"]
    case = next(c for c in fixture["cases"] if c["id"] == "Q14-T3")
    assert len(case["packet"]["recent_messages"]) == 2


def test_transmissions_have_same_evidence_and_never_gold_or_artifact_labels():
    for case in study.load_fixture()["cases"]:
        body = build_intent_request(JevConfig(), case["packet"])
        assert "expected" not in body["state"] and "label_reasons" not in body["state"]
        assert "expected_artifact" not in json.dumps(body)
        assert all(m["author"] == "CUSTOMER" for m in body["state"]["recent_messages"])


def test_manifest_tamper_stops_before_loading_credentials(tmp_path, monkeypatch):
    study.freeze(tmp_path / "cohort")
    path = tmp_path / "cohort" / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["files"]["agent/tests/fixtures/jev-intent-fifty-v1.json"] = "wrong"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(study, "load_local_env", lambda *_: pytest.fail("credentials read before integrity check"))
    with pytest.raises(ValueError, match="frozen source changed"):
        study.execute(tmp_path / "cohort")


def test_paid_cohort_cannot_be_overwritten(tmp_path):
    study.freeze(tmp_path / "cohort")
    (tmp_path / "cohort" / "attempt-001.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be repeated"):
        study.execute(tmp_path / "cohort")


def test_request_cap_is_one_hundred_and_fifty_per_provider(tmp_path):
    budget = study.CappedAllowance(tmp_path)
    for _ in range(50):
        budget.reserve("jev", {})
    with pytest.raises(ValueError, match="request cap"):
        budget.reserve("jev", {})
    assert budget.calls == 50
    for _ in range(50):
        budget.reserve("intent-baseline", {})
    with pytest.raises(ValueError, match="request cap"):
        budget.reserve("intent-baseline", {})
    assert budget.calls == 100


def test_exact_match_requires_every_task_and_consultation_false_actions_count():
    expected = {"t1": "DECLINED", "t2": "INFORMATION"}
    values = {"t1": "DECLINED", "t2": "PREPARE_REFUND"}
    result = study.score(expected, values)
    assert result == {"correct": False, "task_correct": 1, "false_operation": 1}
    assert not study.score(expected, {"t1": "DECLINED"})["correct"]


def test_cost_estimate_never_turns_unknown_usage_into_zero():
    assert study.estimated_cost(None, "jev") is None
    assert study.estimated_cost({"input_tokens": 1000, "output_tokens": 10}, "jev") == pytest.approx(.000042)
    assert study.sum_known([.1, None]) is None


def test_fallback_uses_the_paired_baseline_without_an_extra_call():
    row = {"baseline": {"t1": "INFORMATION"}, "jev": {"t1": "UNCLEAR"}, "fallback": True}
    assert study.selected(row) == row["baseline"]
    other = copy.deepcopy(row)
    other["fallback"] = False
    assert study.selected(other) == other["jev"]


def test_one_pass_executes_exactly_one_hundred_attempts_and_recalculates_summary(tmp_path, monkeypatch):
    directory = tmp_path / "cohort"
    study.freeze(directory)
    monkeypatch.setattr(study, "load_local_env", lambda *_: None)
    monkeypatch.setenv("TYPESAFE_API_KEY", "unit-only")
    monkeypatch.setenv("RESOLVEFLOW_JEV_ENABLED", "0")
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "unit-only")
    counts = {"jev": 0, "baseline": 0}

    def baseline(packet, _key, budget):
        counts["baseline"] += 1
        path, record = budget.reserve("intent-baseline", packet)
        decision = {"kind": "CHECK_REQUEST", "assessments": [{**t, "purpose": "INFORMATION", "reason": "scripted"}
            for t in packet["orchestration"]["request_check"]["tasks"]]}
        record.update(status="COMPLETE", decision=decision, usage={"input_tokens": 100, "output_tokens": 10},
                      elapsed_ms=1)
        study.write(path, record)
        return {"decision": decision, "call": record}

    def transport(req):
        counts["jev"] += 1
        body = json.loads(req.content)
        return httpx.Response(200, json={"model": "jev-1.14.0", "usage": {"input_tokens": 100, "output_tokens": 10},
            "answers": {k: {"type": "choice", "choice": "UNCLEAR", "confidence": .9,
                "probabilities": {c: float(c == "UNCLEAR") for c in study.OPTIONS}} for k in body["questions"]}})

    original = study.RecordedChoices

    def choices(config, budget):
        result = original(config, budget)
        result.transport = httpx.MockTransport(transport)
        return result

    monkeypatch.setattr(study, "classify", baseline)
    monkeypatch.setattr(study, "RecordedChoices", choices)
    study.execute(directory)
    report = study.summary(directory)
    assert counts == {"jev": 50, "baseline": 50}
    assert report["total_attempts"] == 100 and report["splits"]["all"]["fallbacks"] == 50
    assert report["metrics"]["baseline"] == report["metrics"]["hybrid"]
    assert report["cost_estimate_peak_cache_miss_usd"]["hybrid"] == pytest.approx(.00231)
    assert report["cost_unknown_calls"] == {"baseline": 0, "jev_raw": 0, "hybrid": 0}
