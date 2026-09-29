"""The reviewer demonstration driver refuses anything that would reach outside its own stack.

The driver (`scripts/reviewer_demo.py`) seeds order lines directly and starts real services, so the
failures worth testing are the ones that would look like success: a demo port that is really the
shared stack's, a process file belonging to another environment, a second `prepare` that mints a
duplicate sample, and a stop that kills a process this driver never started. None of these need
Docker, a database or a port: they are all decisions the driver makes from data it is handed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import reviewer_demo as demo  # noqa: E402


def settings_for(tmp_path: Path, **overrides) -> demo.Settings:
    base = dict(
        environment=demo.ENVIRONMENT,
        project=demo.PROJECT,
        dataset="reviewer-demo-2026-09-test",
        ports=dict(demo.DEFAULT_PORTS),
        manifest_path=tmp_path / "samples.json",
        runtime_root=tmp_path / "runtime",
    )
    base.update(overrides)
    return demo.Settings(**base)


# --------------------------------------------------------------------------- isolation


def test_a_demo_port_that_is_a_shared_port_is_refused(tmp_path: Path) -> None:
    ports = dict(demo.DEFAULT_PORTS)
    ports["gateway"] = 8080
    with pytest.raises(demo.DemoRefused) as refusal:
        demo.guard(settings_for(tmp_path, ports=ports))
    assert "8080" in str(refusal.value)


def test_the_default_ports_do_not_collide_with_the_shared_environment(tmp_path: Path) -> None:
    assert not (set(demo.DEFAULT_PORTS.values()) & demo.SHARED_PORTS)
    demo.guard(settings_for(tmp_path))


def test_a_foreign_project_or_environment_is_refused(tmp_path: Path) -> None:
    with pytest.raises(demo.DemoRefused):
        demo.guard(settings_for(tmp_path, project="resolveflow"))
    with pytest.raises(demo.DemoRefused):
        demo.guard(settings_for(tmp_path, environment="reviewer-demo-somebody-else"))


def test_a_dataset_that_is_not_this_demonstrations_is_refused(tmp_path: Path) -> None:
    with pytest.raises(demo.DemoRefused):
        demo.guard(settings_for(tmp_path, dataset="production"))


def test_two_roles_may_not_share_one_port(tmp_path: Path) -> None:
    ports = dict(demo.DEFAULT_PORTS)
    ports["agent"] = ports["case"]
    with pytest.raises(demo.DemoRefused) as refusal:
        demo.guard(settings_for(tmp_path, ports=ports))
    assert "distinct" in str(refusal.value)


def test_the_browser_experience_has_an_isolated_desktop_url(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    assert settings.frontend_url == "http://127.0.0.1:5174"
    assert settings.ports["frontend"] not in demo.SHARED_PORTS


def test_the_demo_compose_project_is_isolated_on_paper() -> None:
    """What the compose file promises, read from the file rather than from a report."""
    text = (demo.COMPOSE_FILE).read_text(encoding="utf-8")
    assert "name: resolveflow-review-demo" in text
    assert "demo-mysql-data" in text and "demo-postgres-data" in text
    assert "redis" not in text, "the demo must not borrow the shared Redis"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('- "127.0.0.1:'):
            published = int(stripped.split(":")[2].split("}")[0].split(":-")[-1].split(":")[0])
            assert published not in demo.SHARED_PORTS, f"{published} is a shared port"


# --------------------------------------------------------------------------- process ownership


def test_a_process_file_from_another_environment_is_refused(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    path = demo.processes_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"project": "resolveflow", "environment": "other", "processes": [{"name": "x"}]}),
        encoding="utf-8",
    )
    with pytest.raises(demo.DemoRefused):
        demo.read_owned(settings)


def test_a_process_that_does_not_own_its_port_is_left_alone(tmp_path: Path, monkeypatch) -> None:
    settings = settings_for(tmp_path)
    demo.write_owned(
        settings,
        [{"name": "agent", "pid": 4242, "port": 8182, "owner_pid": 4242, "started_at": "x", "log": "y"}],
    )
    killed: list[str] = []
    monkeypatch.setattr(demo, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(demo, "pids_on_port", lambda port: ["9999"])
    monkeypatch.setattr(
        demo.subprocess, "run", lambda args, **kwargs: killed.append(" ".join(str(a) for a in args))
    )
    assert demo.stop_owned(settings, "agent") == []
    assert killed == [], "an unrelated listener must never be killed"
    assert [entry["pid"] for entry in demo.read_owned(settings)] == [4242], "and it stays on the record"


def test_a_process_that_does_own_its_port_is_stopped_as_a_tree(tmp_path: Path, monkeypatch) -> None:
    settings = settings_for(tmp_path)
    demo.write_owned(
        settings,
        [{"name": "agent", "pid": 4242, "port": 8182, "owner_pid": 5151, "started_at": "x", "log": "y"}],
    )
    calls: list[list[str]] = []
    owners = {"8182": ["5151"]}

    def fake_run(args, **kwargs):
        calls.append([str(a) for a in args])
        owners["8182"] = []
        return None

    monkeypatch.setattr(demo, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(demo, "pids_on_port", lambda port: list(owners["8182"]))
    monkeypatch.setattr(demo.subprocess, "run", fake_run)
    monkeypatch.setattr(demo.time, "sleep", lambda seconds: None)
    stopped = demo.stop_owned(settings, "agent")
    assert stopped == ["agent(pid 4242, port 8182)"]
    assert any("/T" in call for call in calls), "the launcher's child holds the socket, so the tree is killed"
    assert demo.read_owned(settings) == []


def test_readonly_agent_cannot_consume_runs_or_inherit_live_model_settings(tmp_path: Path, monkeypatch) -> None:
    settings = settings_for(tmp_path)
    captured: dict = {}
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("RESOLVEFLOW_MODEL_ENDPOINT", "https://paid.invalid")
    monkeypatch.setattr(demo, "owns_port", lambda *args: False)
    monkeypatch.setattr(demo, "stop_owned", lambda *args, **kwargs: [])
    monkeypatch.setattr(demo, "refuse_if_port_held", lambda *args: None)
    monkeypatch.setattr(demo, "child_env", lambda **extra: {**dict(demo.os.environ), **extra})
    monkeypatch.setattr(
        demo,
        "start_process",
        lambda _settings, name, args, env, port: captured.update(name=name, args=args, env=env, port=port),
    )
    monkeypatch.setattr(demo, "wait_for", lambda *args, **kwargs: True)
    monkeypatch.setattr(demo, "record_port_owner", lambda *args: "42")

    demo.start_readonly_agent(settings, demo.Log())

    assert captured["name"] == "agent-readonly"
    assert captured["env"]["RESOLVEFLOW_INVESTIGATION_ENABLED"] == "0"
    assert "RESOLVEFLOW_MODEL_API_KEY" not in captured["env"]
    assert "RESOLVEFLOW_MODEL_ENDPOINT" not in captured["env"]
    assert "RESOLVEFLOW_MOCK_SCRIPT" not in captured["env"]


def test_frontend_is_bound_to_the_demo_gateway_and_fixed_port(tmp_path: Path, monkeypatch) -> None:
    settings = settings_for(tmp_path)
    captured: dict = {}
    fake_root = tmp_path / "repo"
    (fake_root / "web" / "node_modules").mkdir(parents=True)
    monkeypatch.setattr(demo, "ROOT", fake_root)
    monkeypatch.setattr(demo, "owns_port", lambda *args: False)
    monkeypatch.setattr(demo, "stop_owned", lambda *args, **kwargs: [])
    monkeypatch.setattr(demo, "refuse_if_port_held", lambda *args: None)
    monkeypatch.setattr(demo.shutil, "which", lambda name: r"C:\tools\pnpm.cmd" if name == "pnpm.cmd" else None)
    monkeypatch.setattr(demo, "child_env", lambda **extra: extra)
    monkeypatch.setattr(
        demo,
        "start_process",
        lambda _settings, name, args, env, port: captured.update(name=name, args=args, env=env, port=port),
    )
    monkeypatch.setattr(demo, "wait_for", lambda *args, **kwargs: True)
    monkeypatch.setattr(demo, "record_port_owner", lambda *args: "43")

    demo.start_frontend(settings, demo.Log())

    assert captured["name"] == "frontend"
    assert captured["port"] == 5174
    assert captured["env"] == {"VITE_API_PROXY": "http://127.0.0.1:8180", "VITE_PORT": "5174"}
    assert captured["args"][-2:] == ["--host", "127.0.0.1"]


def test_status_is_useful_while_the_demo_is_stopped(tmp_path: Path, monkeypatch) -> None:
    settings = settings_for(tmp_path)
    document = demo.load_manifest(settings)
    document["samples"] = [
        {
            "scenario": "lost-review",
            "dataset_id": settings.dataset,
            "case_id": "case-offline",
            "line_id": "line-offline",
            "status": "PENDING_REVIEW",
        }
    ]
    demo.save_manifest(settings, document)
    monkeypatch.setattr(demo, "container_health", lambda *args: "")
    monkeypatch.setattr(demo, "case_state", lambda *args: pytest.fail("offline status must not query MySQL"))
    monkeypatch.setattr(demo, "read_owned", lambda *args: [])
    log = demo.Log()

    assert demo.command_status(settings, log) == 0
    assert any("live=offline" in line for line in log.lines)


# --------------------------------------------------------------------------- manifest discipline


def test_recording_a_sample_replaces_it_rather_than_duplicating_it(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    document = demo.load_manifest(settings)
    first = {"scenario": "lost-review", "dataset_id": settings.dataset, "case_id": "a", "status": "PENDING_REVIEW"}
    demo.record_sample(settings, document, dict(first))
    second = {**first, "case_id": "b"}
    demo.record_sample(settings, document, dict(second))
    stored = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    assert [sample["case_id"] for sample in stored["samples"]] == ["b"]
    assert demo.sample_of(stored, settings.dataset, "lost-review")["case_id"] == "b"


def test_a_retired_attempt_is_moved_aside_and_never_deleted(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    document = demo.load_manifest(settings)
    sample = {
        "scenario": "damage-review",
        "dataset_id": settings.dataset,
        "case_id": "c-1",
        "line_id": "9001",
        "status": "ANALYZING",
    }
    demo.record_sample(settings, document, dict(sample))
    demo.retire_sample(settings, document, sample, reason="the run failed before a proposal existed")
    stored = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    assert stored["samples"] == []
    assert len(stored["retired"]) == 1
    assert stored["retired"][0]["case_id"] == "c-1"
    assert stored["retired"][0]["retired_reason"] == "the run failed before a proposal existed"


def test_a_manifest_from_another_environment_is_refused(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    settings.manifest_path.write_text(
        json.dumps({"environment": "someone-else", "project": "resolveflow", "samples": []}), encoding="utf-8"
    )
    with pytest.raises(demo.DemoRefused):
        demo.load_manifest(settings)


def test_a_sample_that_a_person_moved_on_is_not_the_expected_state() -> None:
    scenario = demo.SCENARIOS["waiting-info"]
    settled = {
        "exists": True,
        "status": "WAITING_CUSTOMER",
        "question_id": "q-1",
        "question_answered": False,
        "authorization": None,
    }
    assert demo.unchanged_from_expected(settled, scenario)
    answered = {**settled, "question_answered": True}
    assert not demo.unchanged_from_expected(answered, scenario), "an answered question is no longer waiting"
    moved_on = {**settled, "status": "PENDING_REVIEW"}
    assert not demo.unchanged_from_expected(moved_on, scenario)


def test_an_approving_sample_is_unchanged_only_with_its_authorization() -> None:
    scenario = demo.SCENARIOS["success-refund"]
    base = {"exists": True, "status": "CLOSED_SUCCESS", "question_id": None, "question_answered": False}
    assert not demo.unchanged_from_expected({**base, "authorization": None}, scenario)
    assert demo.unchanged_from_expected(
        {**base, "authorization": {"status": "CONSUMED"}}, scenario
    )


# --------------------------------------------------------------------------- the mock is bound to one run


def test_every_scenario_has_a_script_builder_and_a_settled_expectation() -> None:
    assert set(demo.SCENARIOS) >= set(demo.DISPLAY_SCENARIOS)
    for name, scenario in demo.SCENARIOS.items():
        assert scenario.name == name
        assert scenario.expected_status in {"PENDING_REVIEW", "WAITING_CUSTOMER", "RECONCILING", "CLOSED_SUCCESS"}
        assert scenario.amount_minor > 0
        assert scenario.shipment_events, "every sample needs a real shipment story to cite"


def test_the_script_a_scenario_builds_cites_only_its_own_run(capsys: pytest.CaptureFixture) -> None:
    """A script's citations come from the preflight, and a missing one must fail loudly."""
    scenario = demo.SCENARIOS["lost-review"]
    citations = {
        demo.TOOL_GET_SHIPMENT: {
            "observation_id": "obs-1",
            "source_ref": "commerce:/internal/v1/order-lines/1/shipment",
            "source_version": "2",
            "content_hash": "a" * 64,
        }
    }
    policies = {
        "R-LOST-001": {
            "bundle_id": "policy-logistics-2026.09",
            "version": "2026.09",
            "rule_id": "R-LOST-001",
            "chunk_id": "c-01",
            "content_hash": "b" * 64,
        }
    }
    script = demo.build_script(scenario, citations=citations, policies=policies)
    kinds = [entry["kind"] for entry in script]
    assert kinds == ["READ_TOOL", "SEARCH_POLICY", "PROPOSE"]
    assert script[-1]["evidence_refs"] == [citations[demo.TOOL_GET_SHIPMENT]]
    assert script[-1]["policy_refs"] == [policies["R-LOST-001"]]
    assert script[-1]["review_findings"][0]["observation_ids"] == ["obs-1"]

    with pytest.raises(KeyError):
        demo.build_script(scenario, citations={}, policies=policies)
