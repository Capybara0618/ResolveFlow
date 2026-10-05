from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from agentscope.message import Msg, TextBlock
from resolveflow.harness.model import ModelReply, ModelUsage

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.agent_eval import allowance, main, persist, rescore  # noqa: E402
from scripts.evaluation.models import CaptureModel, live_guard  # noqa: E402
from scripts.evaluation.reporting import compare_reports, describe  # noqa: E402


def test_report_replace_retries_local_sharing_violation_without_rewriting_payload(tmp_path):
    output = tmp_path / "result.json"
    replace = Path.replace
    attempts = []

    def transient(source, target):
        attempts.append(source.read_bytes())
        if len(attempts) < 3:
            raise PermissionError("sharing violation")
        return replace(source, target)

    with patch.object(Path, "replace", transient), patch("scripts.agent_eval.time.sleep") as sleep:
        persist(output, {"status": "saved"})
    assert json.loads(output.read_text()) == {"status": "saved"}
    assert len(set(attempts)) == 1 and len(attempts) == 3
    assert sleep.call_count == 2


def test_report_replace_permanent_denial_is_explicit_and_keeps_partial(tmp_path):
    output = tmp_path / "result.json"
    with patch.object(Path, "replace", side_effect=PermissionError("denied")) as replace, \
            patch("scripts.agent_eval.time.sleep"), pytest.raises(PermissionError):
        persist(output, {"status": "saved"})
    assert replace.call_count == 4 and not output.exists()
    assert json.loads(output.with_suffix(".partial").read_text()) == {"status": "saved"}


@pytest.mark.parametrize("profile,expected,count", [("resolveflow-replay-context-v4", 6, 0),
    ("resolveflow-replay-context-v4", 6, 5), ("resolveflow-replay-investigation-v5", 7, 0),
    ("resolveflow-replay-investigation-v5", 7, 6), ("resolveflow-replay-usage-v6", 7, 0),
    ("resolveflow-replay-usage-v6", 7, 6)])
def test_current_replay_profile_cannot_pass_with_missing_trajectories(tmp_path, profile, expected, count):
    root = tmp_path / "replay"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"profile_version": profile}),
                                        encoding="utf-8")
    for index in range(count):
        directory = root / str(index)
        directory.mkdir()
        (directory / "pack.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "report.json"
    with pytest.raises(ValueError, match=f"Expected {expected} replay packs"):
        main(["replay", "--replay-dir", str(root), "--output", str(output)])
    assert not output.exists()


def test_old_total_cap_no_longer_prevents_transmission(tmp_path):
    path = tmp_path / "usage.json"
    persist(path, {"used": 96, "limit": 96, "reserved_usd": 0.50})
    client = SimpleNamespace(decide=lambda **_: ModelReply(
        decision={"kind": "ESCALATE"}, usage=ModelUsage(7, 3), mode="mock"))
    model = CaptureModel(client, allowance(path))
    model.decide(
        system="system",
        messages=[Msg(name="user", content=[TextBlock(type="text", text="request")], role="user")],
        max_output_tokens=1024,
    )
    saved = json.loads(path.read_text())
    assert saved["used"] == 97 and saved["limit"] is None
    assert saved["historical_limit"] == 96 and saved["reserved_usd"] == 0.50
    assert model.records[0]["usage"]["output_tokens"] == 3


def test_parallel_live_process_cannot_share_an_unlocked_budget(tmp_path):
    path = tmp_path / "cap.json"
    with live_guard(path), pytest.raises(ValueError, match="locked"):
        with live_guard(path):
            pytest.fail("Concurrent process acquired the same budget")
    assert not path.with_name("cap.json.lock").exists()


def test_budget_and_failed_attempt_are_persisted_before_unknown_response(tmp_path):
    path = tmp_path / "cap.json"
    cap = allowance(path)
    events = []

    def failed(**_):
        assert allowance(path)["used"] == 1
        assert events[-1][-1]["messages"][0]["content"] == "synthetic request"
        raise TimeoutError("unknown outcome")

    model = CaptureModel(SimpleNamespace(decide=failed), cap, lambda r: events.append(deepcopy(r)))
    with pytest.raises(TimeoutError):
        model.decide(
            system="synthetic",
            messages=[Msg(name="user", content=[TextBlock(type="text", text="synthetic request")], role="user")],
            max_output_tokens=1024,
        )
    assert allowance(path)["used"] == 1
    assert events[-1][-1]["error"] == "TimeoutError: unknown outcome"


def test_capture_records_usage_without_client_credentials():
    client = SimpleNamespace(
        api_key="synthetic-key-not-for-network",
        decide=lambda **_: ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(7, 3), mode="mock"),
    )
    model = CaptureModel(client)
    model.decide(
        system="system",
        messages=[Msg(name="user", content=[TextBlock(type="text", text="request")], role="user")],
        max_output_tokens=10,
    )
    assert model.records[0]["usage"]["input_tokens"] == 7
    assert client.api_key not in str(model.records)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_output_tokens", 1025),
        ("messages", [Msg(name="user", content=[TextBlock(type="text", text="x" * 11001)], role="user")]),
    ],
)
def test_capture_has_no_monetary_input_or_output_bounds(field, value):
    model = CaptureModel(SimpleNamespace(decide=lambda **_: ModelReply(
        decision={"kind": "ESCALATE"}, usage=ModelUsage(7, 3), mode="mock")), {"used": 0, "limit": 96})
    kwargs = {
        "system": "system",
        "messages": [Msg(name="user", content=[TextBlock(type="text", text="short")], role="user")],
        "max_output_tokens": 1024,
    }
    kwargs[field] = value
    model.decide(**kwargs)
    assert model.allowance["used"] == 1 and len(model.records) == 1


def test_usage_ledger_preserves_history_above_old_limits(tmp_path):
    path = tmp_path / "cap.json"
    persist(path, {"used": 120, "limit": 96, "reserved_usd": 1.50, "note": "history"})
    ledger = allowance(path)
    ledger["save"]()
    again = allowance(path)
    assert again["used"] == 120 and again["reserved_usd"] == 1.50
    assert again["limit"] is None and again["historical_limit"] == 96
    assert again["note"] == "history"


@pytest.mark.parametrize("used,reserved", [(-1, 0), (False, 0), (0, -0.1), (0, float("nan"))])
def test_invalid_persisted_allowance_refused(tmp_path, used, reserved):
    path = tmp_path / "cap.json"
    persist(path, {"used": used, "limit": 96, "reserved_usd": reserved})
    with pytest.raises(ValueError, match="Invalid persisted"):
        allowance(path)


def report():
    return {
        "mode": "mock",
        "manifest_hash": "frozen",
        "dataset_version": "test",
        "code_commit": "test",
        "code_hashes": {"scripts/evaluation/scoring.py": "one", "scripts/evaluation/dataset.py": "two"},
        "results": [{"id": "A01A", "split": "dev", "pair_id": "A01", "joint_correct": False}],
    }


@pytest.mark.parametrize(
    "change",
    [
        "mode",
        "manifest_hash",
        "scorer",
        "selection",
        "provider",
        "split",
        "duplicate",
        "embedding",
        "backend_profile",
        "alias",
    ],
)
def test_incomparable_reports_refused(change):
    before, after = report(), report()
    if change in {"mode", "manifest_hash", "provider", "embedding", "backend_profile"}:
        after[change] = "changed"
    elif change == "scorer":
        after["code_hashes"]["scripts/evaluation/scoring.py"] = "changed"
    elif change == "split":
        after["results"][0]["split"] = "test"
    elif change == "duplicate":
        after["results"].append(deepcopy(after["results"][0]))
    elif change == "alias":
        after["results"][0]["requests"] = [{"model_alias": "different-model"}]
    else:
        after["results"][0]["id"] = "different"
    with pytest.raises(ValueError):
        compare_reports(before, after)


def test_paired_compare_keeps_denominator_and_failure():
    before, after = report(), report()
    after["results"][0]["joint_correct"] = True
    scored = compare_reports(before, after)
    assert scored["n"] == 1 and scored["before"] == 0 and scored["after"] == 1
    assert scored["improved"] == ["A01A"] and not scored["regressed"]
    assert "单成员不计配对分" in describe(before)


def test_live_default_refused_before_environment_or_key_access():
    with pytest.raises(SystemExit) as error:
        main(["live"])
    assert error.value.code == 2


def test_existing_report_is_not_overwritten(tmp_path):
    target = tmp_path / "existing.json"
    target.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="immutable"):
        main(["harness", "--output", str(target)])
    assert target.read_text() == "preserve"


def test_rescore_keeps_execution_provenance_and_calls_no_model(tmp_path):
    source = load_live_fixture()
    target = tmp_path / "saved.json"
    persist(target, source)
    before_hashes = deepcopy(source["code_hashes"])
    updated = rescore(source, target)
    assert updated["new_model_requests"] == 0
    assert updated["code_hashes"] == before_hashes
    assert updated["summary"]["n"] == 8 and updated["summary"]["joint_correct"] == 0


def load_live_fixture():
    import json

    return json.loads((ROOT / "reports/current-evaluation/live-baseline.json").read_text(encoding="utf-8"))


def test_unfinished_comparison_is_not_completion():
    before, after = report(), report()
    after["state"] = "RUNNING"
    with pytest.raises(ValueError, match="Unfinished"):
        compare_reports(before, after)
