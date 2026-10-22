"""Full application lifecycle cannot silently omit investigation or replace existing data."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import project_runtime as project
import reviewer_demo as runtime


def application(tmp_path):
    (tmp_path / "foundation.json").write_text(
        json.dumps(
            {
                "profile": "foundation-v1",
                "role_profile": "merchant-single-v1",
                "bundles": ["policy-v1"],
            }
        ),
        encoding="utf-8",
    )
    return runtime.Settings(runtime_root=tmp_path)


def test_missing_key_never_replaces_existing_processes(tmp_path, monkeypatch):
    monkeypatch.delenv("RESOLVEFLOW_MODEL_API_KEY", raising=False)
    monkeypatch.setattr(runtime, "stage_ready", lambda *_: pytest.fail("must fail before touching infrastructure"))
    with pytest.raises(runtime.DemoRefused, match="Deepseek_API_KEY"):
        project.start(application(tmp_path), Mock(), build=True, open_browser=True)


def test_uninitialized_or_old_data_is_not_silently_reseeded(tmp_path, monkeypatch):
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "synthetic-test-key")
    prepare = Mock()
    monkeypatch.setattr(runtime, "command_prepare", prepare)
    with pytest.raises(runtime.DemoRefused, match="初始化"):
        project.start(runtime.Settings(runtime_root=tmp_path), Mock(), build=True, open_browser=False)
    application(tmp_path)
    (tmp_path / "foundation.json").write_text('{"profile":"foundation-v1"}', encoding="utf-8")
    with pytest.raises(runtime.DemoRefused, match="升级"):
        project.start(runtime.Settings(runtime_root=tmp_path), Mock(), build=True, open_browser=False)
    prepare.assert_not_called()


@pytest.mark.parametrize("ready", [True, False])
def test_start_includes_live_agent_and_frontend_even_when_backend_is_already_running(tmp_path, monkeypatch, ready):
    current = application(tmp_path)
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(runtime, "stage_ready", lambda *_: ready)
    monkeypatch.setattr(runtime, "tcp_open", lambda *_: True)
    monkeypatch.setattr(project, "status", lambda *_: 0)
    monkeypatch.setattr(project, "policies_ready", lambda *_: True)
    prepare, agent, frontend, browser = Mock(), Mock(), Mock(), Mock(return_value=True)
    monkeypatch.setattr(runtime, "command_prepare", prepare)
    monkeypatch.setattr(runtime, "start_readonly_agent", agent)
    monkeypatch.setattr(runtime, "start_frontend", frontend)
    monkeypatch.setattr(runtime, "owns_port", lambda _, name, port: name == "agent-live")
    monkeypatch.setattr(runtime, "agent_health", lambda *_, **__: True)
    monkeypatch.setattr(project.webbrowser, "open", browser)
    log = Mock()
    assert project.start(current, log, build=True, open_browser=True) == 0
    agent.assert_called_once_with(current, log, live=True, architecture="staged-v1")
    frontend.assert_called_once_with(current, log)
    browser.assert_called_once_with(current.frontend_url + "/#/shop", new=2)
    assert prepare.call_count == (0 if ready else 1)


def test_wrong_policy_hash_is_not_reported_as_ready(tmp_path, monkeypatch):
    current = application(tmp_path)
    monkeypatch.setattr(runtime, "mysql_rows", lambda *_: [["policy-v1", "a" * 64]])
    monkeypatch.setattr(runtime, "postgres_scalar", lambda *_: "0")
    assert project.policies_ready(current) is False
    monkeypatch.setattr(runtime, "postgres_scalar", lambda *_: "1")
    assert project.policies_ready(current) is True


def test_missing_policy_blocks_start_before_live_queue_consumption(tmp_path, monkeypatch):
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(runtime, "stage_ready", lambda *_: True)
    monkeypatch.setattr(runtime, "tcp_open", lambda *_: True)
    monkeypatch.setattr(project, "policies_ready", lambda *_: False)
    agent = Mock()
    monkeypatch.setattr(runtime, "start_readonly_agent", agent)
    with pytest.raises(runtime.DemoRefused, match="索引尚未就绪"):
        project.start(application(tmp_path), Mock(), build=True, open_browser=False)
    agent.assert_not_called()


def test_readonly_agent_does_not_count_as_complete_start(tmp_path, monkeypatch):
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(runtime, "stage_ready", lambda *_: True)
    monkeypatch.setattr(runtime, "tcp_open", lambda *_: True)
    monkeypatch.setattr(project, "policies_ready", lambda *_: True)
    monkeypatch.setattr(runtime, "start_readonly_agent", Mock())
    monkeypatch.setattr(runtime, "start_frontend", Mock())
    monkeypatch.setattr(runtime, "owns_port", lambda *_: False)
    with pytest.raises(runtime.DemoRefused, match="真实调查服务尚未就绪"):
        project.start(application(tmp_path), Mock(), build=True, open_browser=False)


def test_start_never_reports_completion_or_opens_browser_when_component_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(runtime, "stage_ready", lambda *_: True)
    monkeypatch.setattr(runtime, "tcp_open", lambda *_: True)
    monkeypatch.setattr(project, "policies_ready", lambda *_: True)
    monkeypatch.setattr(runtime, "start_readonly_agent", Mock())
    monkeypatch.setattr(runtime, "start_frontend", Mock())
    monkeypatch.setattr(runtime, "owns_port", lambda *_: True)
    monkeypatch.setattr(runtime, "agent_health", lambda *_, **__: True)
    monkeypatch.setattr(project, "status", lambda *_: 1)
    browser = Mock()
    monkeypatch.setattr(project.webbrowser, "open", browser)
    with pytest.raises(runtime.DemoRefused, match="仍有组件未就绪"):
        project.start(application(tmp_path), Mock(), build=True, open_browser=True)
    browser.assert_not_called()


def test_shared_ports_are_rejected_before_starting(monkeypatch):
    monkeypatch.setattr(
        runtime, "settings_from_environ", lambda: runtime.Settings(ports={**runtime.DEFAULT_PORTS, "mysql": 3306})
    )
    guard = Mock()
    monkeypatch.setattr(runtime, "guard", guard)
    with pytest.raises(runtime.DemoRefused, match="共享环境"):
        project.settings()
    guard.assert_not_called()


def test_shutdown_failure_is_nonzero_without_requiring_model_key(monkeypatch, tmp_path):
    monkeypatch.delenv("RESOLVEFLOW_MODEL_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["project_runtime.py", "stop"])
    monkeypatch.setattr(project, "settings", lambda: application(tmp_path))

    def failed_stop(_, log):
        log.step("container stop failed", False)
        return 0

    monkeypatch.setattr(runtime, "command_stop", failed_stop)
    assert project.main() == 1


def test_stopped_status_reports_every_component_without_querying_databases(tmp_path, monkeypatch):
    monkeypatch.delenv("RESOLVEFLOW_MODEL_API_KEY", raising=False)
    monkeypatch.setattr(runtime, "container_health", lambda *_: "exited")
    monkeypatch.setattr(runtime, "tcp_open", lambda *_: False)
    monkeypatch.setattr(runtime, "healthy_and_owned", lambda *_: False)
    monkeypatch.setattr(runtime, "owns_port", lambda *_: False)
    policies = Mock(side_effect=AssertionError("stopped database must not be queried"))
    monkeypatch.setattr(project, "policies_ready", policies)
    log = Mock()
    assert project.status(application(tmp_path), log) == 1
    assert log.step.call_count == 10
    assert any(call.args[0] == "Redis" for call in log.step.call_args_list)
    assert all(call.args[1] is False for call in log.step.call_args_list)
    policies.assert_not_called()


def test_error_does_not_print_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "synthetic-secret-test-only")
    monkeypatch.setattr(sys, "argv", ["project_runtime.py", "start"])
    monkeypatch.setattr(project, "settings", lambda: application(tmp_path))

    def fail(*_args, **_kwargs):
        raise RuntimeError("failed: synthetic-secret-test-only")

    monkeypatch.setattr(project, "start", fail)
    assert project.main() == 1
    output = capsys.readouterr().out
    assert "synthetic-secret-test-only" not in output
    assert "[redacted]" in output
