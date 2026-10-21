"""The live diagnostic must preserve attempts/failures and bind upstream snapshots without sending a model call."""

import datetime as dt
from pathlib import Path

import httpx
import pytest
from resolveflow.harness.model import ModelReply, ModelUsage
from resolveflow.support.protocol import SupportInput
from scripts.customer_rag_live_v2 import (
    PLAN,
    RecordedModel,
    digest,
    evaluate,
    load_plan,
    persist,
    remaining_cases,
    upstream_for,
)


def test_frozen_cases_have_bound_fact_snapshots_and_distinct_criteria():
    plan = load_plan()
    assert len(plan["cases"]) == 12 and plan["not_holdout"] and plan["synthetic"]
    for case in plan["cases"]:
        request = SupportInput.model_validate(
            {
                **case["input_without_deadline"],
                "deadline_at": dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120),
            }
        )
        assert request.context["policy_manifest"]["merchant_id"] == request.merchant_id
        assert len(case["criteria"]) == 3
        assert set(case["pinned_generations"]) == set(request.context["policy_manifest"]["bundle_ids"])


def test_recorded_model_saves_before_actual_call_and_keeps_unknown_attempt():
    class Fails:
        def prepare_request(self, **kwargs):
            return {"messages": [], "max_tokens": kwargs["max_output_tokens"]}

        def decide(self, **kwargs):
            assert order == ["usage", "STARTED"]
            raise TimeoutError("do not put provider messages in the public record")

    order = []
    usage = {"used": 7, "save": lambda: order.append("usage")}
    model = RecordedModel(Fails(), usage, lambda rows: order.append(rows[-1]["state"]))
    with pytest.raises(TimeoutError):
        model.decide(system="", messages=[], max_output_tokens=1024)
    assert usage["used"] == 8 and order == ["usage", "STARTED", "ERROR"]
    assert model.records[0]["error_type"] == "TimeoutError"
    assert "do not put" not in str(model.records)


def test_recorded_model_delegates_preparation_and_keeps_actual_reply():
    class Client:
        provider = "deepseek"

        def prepare_request(self, **kwargs):
            return {"model": "test", "max_tokens": kwargs["max_output_tokens"]}

        def decide(self, **kwargs):
            return ModelReply({"kind": "ANSWER", "text": "answer"}, ModelUsage(10, 2), "mock")

    model = RecordedModel(Client(), {"used": 0, "save": lambda: None}, lambda rows: None)
    assert model.provider == "deepseek"
    assert model.prepare_request(system="", messages=[], max_output_tokens=12)["max_tokens"] == 12
    model.decide(system="", messages=[], max_output_tokens=12)
    assert model.records[0]["usage"]["input_tokens"] == 10
    assert model.records[0]["decision"]["text"] == "answer"


def test_upstream_failure_and_foreign_identity_do_not_turn_into_normal_facts():
    case = next(c for c in load_plan()["cases"] if c["id"] == "F02")
    request = SupportInput.model_validate(
        {
            **case["input_without_deadline"],
            "deadline_at": dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120),
        }
    )
    base = f"http://frozen-case.local/internal/v1/support/turns/{request.run_id}"
    with httpx.Client(transport=httpx.MockTransport(upstream_for(case, request, []))) as client:
        assert client.get(base + "/facts/shipment").status_code == 503
        assert client.get(base.replace(request.run_id, "foreign") + "/facts/shipment").status_code == 403
        assert client.get(base.replace("frozen-case.local", "foreign.local") + "/current").status_code == 403
        assert client.get(base + "/current").json()["input_version"] == 1


def test_existing_report_is_refused_before_any_model_configuration(tmp_path):
    report = tmp_path / "result.json"
    report.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        evaluate(report, tmp_path / "usage.json")
    assert report.read_text() == "existing"


def test_atomic_report_keeps_old_value_during_transient_windows_replace_error(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    path.write_text("old", encoding="utf-8")
    original = Path.replace
    seen = []

    def replace(source, target):
        seen.append(path.read_text())
        if len(seen) == 1:
            raise OSError(22, "transient Windows file sharing")
        return original(source, target)

    monkeypatch.setattr(Path, "replace", replace)
    persist(path, {"new": True})
    assert seen == ["old", "old"] and '"new": true' in path.read_text()
    assert not list(tmp_path.glob("*.pending"))


def test_continuation_only_selects_never_started_cases_including_no_retry_of_failure():
    plan = load_plan()
    prior = {
        "plan_sha256": digest(PLAN),
        "isolated_schema_dropped": True,
        "rows": [{"id": c["id"], "state": "ERROR"} for c in plan["cases"][:9]],
    }
    assert [c["id"] for c in remaining_cases(plan, prior)] == ["F01", "F02", "M01"]
    prior["isolated_schema_dropped"] = False
    with pytest.raises(ValueError, match="cleaned"):
        remaining_cases(plan, prior)
