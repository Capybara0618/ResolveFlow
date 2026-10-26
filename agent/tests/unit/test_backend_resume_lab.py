"""The backend lab must never fall back to shared resources or mutable baseline jars."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation import backend_lab as lab


@pytest.mark.parametrize("value", ["", "demo", "../shared", "ABC123", "a" * 33])
def test_invalid_identity_cannot_name_resources(value):
    with pytest.raises(ValueError, match="identity"):
        lab.Settings(value)


def test_same_port_or_adjacent_broker_vip_collision_is_rejected():
    settings = lab.Settings("a" * 32)
    ports = dict(zip(lab.PORT_ROLES, range(22000, 22000 + len(lab.PORT_ROLES)), strict=True))
    ports["broker"] = ports["mysql"] + 2
    with pytest.raises(ValueError, match="port"):
        settings.validate_ports(ports)


def test_container_label_mismatch_prevents_sql_and_stop(tmp_path, monkeypatch):
    settings = lab.Settings("a" * 32, root=tmp_path)
    monkeypatch.setattr(lab, "run", lambda *a, **k: "foreign-label")
    with pytest.raises(ValueError, match="ownership"):
        settings.assert_owned("mysql")


def test_existing_runtime_is_not_replaced(tmp_path):
    settings = lab.Settings("b" * 32, root=tmp_path)
    settings.folder.mkdir(parents=True)
    settings.state_path.write_text('{"preserve": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="exists"):
        settings.initialize({})
    assert json.loads(settings.state_path.read_text()) == {"preserve": True}


def test_running_command_excludes_second_writer_and_releases(tmp_path):
    settings = lab.Settings("d" * 32, root=tmp_path)
    with settings.operation_lock():
        with pytest.raises(ValueError, match="another"):
            with settings.operation_lock():
                pytest.fail("second writer entered")
    with settings.operation_lock():
        pass


def test_baseline_refuses_changed_jar_and_never_overwrites(tmp_path):
    jar = tmp_path / "source.jar"
    jar.write_bytes(b"baseline")
    target = tmp_path / "frozen.jar"
    digest = lab.freeze_file(jar, target)
    jar.write_bytes(b"modified")
    assert target.read_bytes() == b"baseline"
    assert lab.sha256(target) == digest
    with pytest.raises(FileExistsError):
        lab.freeze_file(jar, target)
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="baseline"):
        lab.verify_file(target, digest)


def test_sql_rejects_foreign_container_before_command(tmp_path, monkeypatch):
    settings = lab.Settings("c" * 32, root=tmp_path)
    monkeypatch.setattr(lab.Settings, "assert_owned", lambda *a: (_ for _ in ()).throw(ValueError("ownership")))
    with pytest.raises(ValueError, match="ownership"):
        settings.sql("SELECT 1")


def test_child_environment_does_not_inherit_live_model_keys(monkeypatch):
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("Deepseek_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("RESOLVEFLOW_AGENT_DB", "foreign-db")
    env = lab.child_env()
    assert "RESOLVEFLOW_MODEL_API_KEY" not in env
    assert "Deepseek_API_KEY" not in env
    assert "RESOLVEFLOW_AGENT_DB" not in env


def test_provider_replay_survives_restart_and_unknown_route_is_rejected(tmp_path):
    from http.client import HTTPConnection

    from evaluation.backend_provider import Provider

    def request(server, method, path, body=None):
        connection = HTTPConnection("127.0.0.1", server.server.server_port, timeout=3)
        try:
            connection.request(method, path, None if body is None else json.dumps(body),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    body = {"operation_id": "op-test", "line_id": "line-test", "amount_minor": 2599, "currency": "CNY"}
    first = Provider(tmp_path / "provider.sqlite3", 0)
    try:
        status, saved = request(first, "POST", "/provider/v1/refunds", body)
        assert status == 200 and saved["state"] == "SUCCEEDED"
        assert request(first, "POST", "/not-a-refund", {})[0] == 404
    finally:
        first.close()
    second = Provider(tmp_path / "provider.sqlite3", 0)
    try:
        assert request(second, "POST", "/provider/v1/refunds", body) == (200, saved)
        assert request(second, "GET", "/provider/v1/refunds/op-test") == (200, saved)
        assert second.stub.attempts("op-test") == 1
    finally:
        second.close()
