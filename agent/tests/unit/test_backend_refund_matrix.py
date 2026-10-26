"""Reject false refund claims even when every HTTP response looked successful."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_refund_matrix import validate_final, validate_ledger, validate_unknown


def test_ledger_checks_nonnegative_and_refunded_plus_reserved():
    validate_ledger({"paid": 100, "refunded": 0, "reserved": 100})
    for wrong in ({"paid": 100, "refunded": 1, "reserved": 100},
                  {"paid": 100, "refunded": -1, "reserved": 0}):
        with pytest.raises(AssertionError):
            validate_ledger(wrong)


def test_unknown_requires_original_reservation_and_no_settlement():
    good = {"paid": 100, "refunded": 0, "reserved": 100,
            "operations": [{"state": "UNKNOWN", "provider_key": "a", "operation_id": "a"}]}
    validate_unknown(good, 100)
    with pytest.raises(AssertionError):
        validate_unknown({**good, "reserved": 0}, 100)
    with pytest.raises(AssertionError):
        validate_unknown({**good, "operations": [{**good["operations"][0], "provider_key": "new"}]}, 100)


def test_final_requires_one_success_per_line_and_one_case_close():
    good = {"paid": 100, "refunded": 100, "reserved": 0, "operation_count": 1,
            "provider_successes": [1], "provider_attempts": [1], "closed_events": [1],
            "operation_states": ["SUCCEEDED"], "line_states": ["CONSUMED"], "case_states": ["CLOSED_SUCCESS"]}
    validate_final(good, 1, 100)
    for field, value in (("provider_successes", [2]), ("closed_events", [2]), ("operation_count", 2),
                         ("provider_attempts", [2]), ("line_states", ["FREE"])):
        with pytest.raises(AssertionError):
            validate_final({**good, field: value}, 1, 100)


def test_each_repeated_f05_starts_with_delivery_disabled(tmp_path, monkeypatch):
    import json

    from evaluation import backend_refund_matrix as matrix

    state = {"pids": {"provider": 1}, "ports": {"provider": 2}}
    class Lab:
        identity = "a" * 32
        folder = tmp_path
        def load(self):
            return state
        def freeze(self):
            return {"jars": {}}
        def stop_children(self, _):
            pass
        def start_child(self, *_):
            pass
    class FakeProvider:
        def __init__(self, *_args, **_kwargs):
            pass
        def close(self):
            pass
    delivery = {"commerce": True}
    monkeypatch.setattr(matrix, "Provider", FakeProvider)
    monkeypatch.setattr(matrix, "login", lambda *_: "demo")
    monkeypatch.setattr(matrix, "healthy", lambda *_: True)
    def restart(_settings, role, enabled):
        delivery[role] = enabled
    monkeypatch.setattr(matrix, "restart", restart)
    def fault(settings, provider, buyer, admin, scenario, output):
        assert delivery["commerce"] is False, "next F05 inherited delivery enabled from previous recovery"
        restart(settings, "commerce", True)
        return {"scenario": scenario, "status": "PASSED"}
    monkeypatch.setattr(matrix, "round_fault", fault)
    (tmp_path / "manifest.json").write_text(json.dumps({"run_id": Lab.identity, "profile": "wiring", "jars": {},
        "sources": {}, "plan": [{"id": "F05-r01", "scenario": "F05"}, {"id": "F05-r02", "scenario": "F05"}]}))
    matrix.execute(Lab(), tmp_path)
    assert json.loads((tmp_path / "summary.json").read_text())["passed"] == 2


def test_continuation_keeps_failed_and_completed_parent_rounds(tmp_path, monkeypatch):
    import json

    from evaluation import backend_refund_matrix as matrix

    parent = tmp_path / "original"
    parent.mkdir()
    rows = [{"id": f"F05-r0{i}", "scenario": "F05"} for i in (1, 2, 3)]
    (parent / "manifest.json").write_text(json.dumps({"profile": "formal", "run_id": "a" * 32,
                                                    "jars": {}, "plan": rows}))
    for number, name in ((1, "outcome"), (2, "failure")):
        directory = parent / "rounds" / f"F05-r0{number}"
        directory.mkdir(parents=True)
        (directory / (name + ".json")).write_text('{}')
    class Lab:
        identity = "a" * 32
        def freeze(self):
            return {"jars": {}}
    monkeypatch.setattr(matrix, "SOURCES", [])
    matrix.freeze(Lab(), tmp_path / "continuation", "formal", parent="original")
    manifest = json.loads((tmp_path / "continuation/manifest.json").read_text())
    assert manifest["plan"] == rows[2:]
    assert "rounds/F05-r02/failure.json" in {p.replace("\\", "/") for p in manifest["lineage"]["preserved_files"]}
    (parent / "rounds/F05-r03").mkdir()
    with pytest.raises(ValueError, match="unknown partial"):
        matrix.freeze(Lab(), tmp_path / "must-not-exist", "formal", parent="original")
    assert not (tmp_path / "must-not-exist").exists()


def test_broker_readiness_retries_admin_timeout_without_claiming_ready(monkeypatch):
    import subprocess

    from evaluation import backend_refund_matrix as matrix

    class Lab:
        def assert_owned(self, role):
            assert role == "broker"
        def container(self, role):
            return "owned-" + role
        def load(self):
            return {"ports": {"broker": 53951}}
    probes = []
    def run(args, **kwargs):
        if args[1] == "start":
            return "started"
        probes.append(args)
        if len(probes) == 1:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return "update topic success"
    def wait(label, predicate):
        assert predicate() is False
        assert predicate() is True
    monkeypatch.setattr(matrix, "run", run)
    monkeypatch.setattr(matrix, "wait", wait)
    matrix.broker_up(Lab())
    assert len(probes) == 2
