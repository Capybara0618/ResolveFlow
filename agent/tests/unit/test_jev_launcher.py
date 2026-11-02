import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import jev_check
import project_runtime


def test_paid_smoke_requires_explicit_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["jev_check.py", "--smoke"])
    monkeypatch.setattr(jev_check, "smoke", lambda *_: pytest.fail("unapproved paid call"))
    with pytest.raises(SystemExit) as error:
        jev_check.main()
    assert error.value.code == 2


def test_smoke_cannot_overwrite_previous_paid_results(tmp_path):
    path = tmp_path / "results.json"
    path.write_text('{"keep":"existing"}', encoding="utf-8")
    with pytest.raises(FileExistsError):
        jev_check.smoke(path, jev_check.JevConfig())
    assert json.loads(path.read_text(encoding="utf-8")) == {"keep": "existing"}


def test_normal_start_loads_jev_before_process_start_and_honors_explicit_disable(tmp_path, monkeypatch):
    monkeypatch.setattr(project_runtime.runtime, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=local-test\nRESOLVEFLOW_JEV_ENABLED=1\n", encoding="utf-8")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("RESOLVEFLOW_JEV_ENABLED", "0")
    monkeypatch.setattr(sys, "argv", ["project_runtime.py", "start", "--skip-build", "--no-browser"])
    calls = []
    monkeypatch.setattr(project_runtime, "settings", lambda: object())

    class Log:
        def __init__(self, *_):
            pass

        def flush(self, _):
            pass

    monkeypatch.setattr(project_runtime, "ProjectLog", Log)
    monkeypatch.setattr(project_runtime.runtime, "log_path", lambda *_: tmp_path / "log")

    def start(*_args, **_kwargs):
        calls.append(jev_check.JevConfig.from_environ())
        return 0

    monkeypatch.setattr(project_runtime, "start", start)
    assert project_runtime.main() == 0
    assert len(calls) == 1 and calls[0].api_key == "local-test" and not calls[0].enabled


def test_fixture_is_small_and_declares_expected_results_before_inference():
    cases = json.loads(jev_check.FIXTURE.read_bytes())
    assert len(cases) == 12 and len({c["id"] for c in cases}) == 12
    assert {c["expected"] for c in cases} == {"supported", "contradicted", "insufficient_evidence"}
