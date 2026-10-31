"""Recording stage selects independent storage, never resets the acceptance data."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import project_runtime as project
import recording_stage as recording
import reviewer_demo as runtime


def test_project_uses_explicit_recording_marker(tmp_path, monkeypatch):
    active = tmp_path / "active.json"
    active.write_text('{"stage":"recording-stage-v1"}', encoding="utf-8")
    monkeypatch.setattr(recording, "ACTIVE", active)
    expected = object()
    selected = Mock(return_value=expected)
    monkeypatch.setattr(recording, "activate", selected)
    assert project.settings() is expected
    selected.assert_called_once()


def test_wrong_marker_never_retargets_runtime(tmp_path, monkeypatch):
    active = tmp_path / "active.json"
    active.write_text('{"stage":"other"}', encoding="utf-8")
    monkeypatch.setattr(recording, "ACTIVE", active)
    before = runtime.PROJECT
    with pytest.raises(runtime.DemoRefused, match="不匹配"):
        recording.activate()
    assert runtime.PROJECT == before


def test_partial_import_never_selects_runtime(tmp_path, monkeypatch):
    active = tmp_path / "active.json"
    active.write_text('{"stage":"recording-stage-v1"}', encoding="utf-8")
    monkeypatch.setattr(recording, "ACTIVE", active)
    monkeypatch.setattr(recording, "STAGE", tmp_path / "incomplete")
    before = runtime.PROJECT
    with pytest.raises(runtime.DemoRefused, match="尚未完成导入"):
        recording.activate()
    assert runtime.PROJECT == before


def test_existing_stage_never_stops_or_reseeds(tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "ACTIVE", tmp_path / "absent.json")
    monkeypatch.setattr(recording, "STAGE", tmp_path)
    stop = Mock()
    monkeypatch.setattr(runtime, "stop_owned", stop)
    with pytest.raises(runtime.DemoRefused, match="保留现场"):
        recording.prepare()
    stop.assert_not_called()


def test_import_refuses_nonempty_target_before_writes(monkeypatch):
    monkeypatch.setattr(runtime, "mysql_scalar", lambda *_: "1")
    write = Mock()
    monkeypatch.setattr(recording, "checked", write)
    with pytest.raises(runtime.DemoRefused, match="拒绝覆盖"):
        recording.import_stage(runtime.Settings())
    write.assert_not_called()


def test_copy_list_excludes_transactions_and_runs():
    assert {"policy_bundle", "identity_account", "buyer_address"} <= set(recording.CASE_TABLES)
    assert not {"aftersale_case", "support_message", "event_outbox", "account_notification_read"} & set(
        recording.CASE_TABLES
    )
    assert not {"orders", "payment_ledger", "product_review", "shopping_cart"} & set(recording.COMMERCE_TABLES)
    assert all(t.startswith("policy_index_") for t in recording.POLICY_TABLES)


def test_recording_compose_has_own_project_and_no_external_volumes():
    import yaml

    value = yaml.safe_load(recording.COMPOSE.read_text(encoding="utf-8"))
    assert value["name"] == recording.PROJECT != runtime.PROJECT
    assert set(value["services"]) == set(runtime.DEMO_SERVICES.values())
    assert not any(v and (v.get("external") or v.get("name")) for v in value["volumes"].values())


def test_recording_start_skips_legacy_scenario_witness(tmp_path, monkeypatch):
    (tmp_path / "foundation.json").write_text(
        json.dumps({"profile": "foundation-v1", "role_profile": "merchant-single-v1"}), encoding="utf-8"
    )
    current = runtime.Settings(environment=recording.ENVIRONMENT, runtime_root=tmp_path)
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(runtime, "stage_ready", lambda *_: False)
    historical, fresh = Mock(), Mock()
    monkeypatch.setattr(runtime, "command_prepare", historical)
    monkeypatch.setattr(runtime, "start_stage", fresh)
    monkeypatch.setattr(project, "policies_ready", lambda *_: True)
    monkeypatch.setattr(runtime, "start_readonly_agent", Mock())
    monkeypatch.setattr(runtime, "start_frontend", Mock())
    monkeypatch.setattr(runtime, "owns_port", lambda *_: True)
    monkeypatch.setattr(runtime, "agent_health", lambda *_, **__: True)
    monkeypatch.setattr(project, "status", lambda *_: 0)
    assert project.start(current, Mock(), build=False, open_browser=False) == 0
    fresh.assert_called_once()
    historical.assert_not_called()


def test_review_preparation_refuses_original_environment(monkeypatch):
    import recording_reviews

    monkeypatch.setattr(project, "settings", lambda: runtime.Settings())
    with pytest.raises(runtime.DemoRefused, match="独立拍摄"):
        recording_reviews.require_stage()


def test_logistics_follows_selected_runtime(monkeypatch):
    import logistics_simulator

    selected = runtime.Settings(project=recording.PROJECT)
    monkeypatch.setattr(project, "settings", lambda: selected)
    guard, locate = Mock(), Mock(return_value="recording-mysql")
    monkeypatch.setattr(runtime, "guard", guard)
    monkeypatch.setattr(runtime, "live_container", locate)
    assert logistics_simulator.LocalMysql().container == "recording-mysql"
    guard.assert_called_once_with(selected)
    locate.assert_called_once_with("mysql", selected)


def test_switch_failure_keeps_active_marker(tmp_path, monkeypatch):
    active = tmp_path / "active.json"
    active.write_text('{"stage":"recording-stage-v1"}', encoding="utf-8")
    monkeypatch.setattr(recording, "ACTIVE", active)
    monkeypatch.setattr(recording, "activate", lambda: runtime.Settings())
    monkeypatch.setattr(runtime, "command_stop", lambda *_: 1)
    original = Mock()
    monkeypatch.setattr(recording, "original_settings", original)
    with pytest.raises(runtime.DemoRefused, match="保持原选择"):
        recording.select_original()
    assert active.is_file()
    original.assert_not_called()
