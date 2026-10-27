"""The actual failed summary stays in the journal; only a grounded draft can publish and recover."""

import hashlib
import json
from pathlib import Path

from tests.recorded_sources import SavedSources

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.protocol import SupportInput
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import request


def test_q01_quote_draft_and_fact_manifest_survive_real_pg_recovery(agent_db):
    root = Path(__file__).resolve().parents[3]
    row = json.loads((root / "agent/tests/fixtures/regressions/customer-agent-goal-confirm-v1/runtime-results.json").read_text(
        encoding="utf-8"))["rows"][0]
    req = SupportInput.model_validate({**row["input"], "deadline_at": request().deadline_at})
    saved = [m["decision"] for m in row["models"]]
    final = {**saved[-1], "handoff_reason": {"customer_quotes": ["耳机外壳有裂痕"]}}
    script = [*saved, final]
    models, sources = [TokenizedScript(mode="live", script=script)], SavedSources(row["calls"])
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), architecture="orchestrated-v1",
                             model_factory=lambda: models[0], sources_factory=lambda *_: sources)
    result = runtime.run(req, "test-bound")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert "耳机外壳有裂痕" in result["answer"]["handoff_summary"]
    assert "已付款" not in result["answer"]["handoff_summary"]
    assert result["spend"]["model_calls"] == 3 and result["spend"]["local_reads"] == 1
    assert len(result["answer"]["dialogue_state"]["events"]) == len(saved[0]["dialogue_events"])
    with agent_db.connection() as c:
        calls = c.execute("SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY kind,position",
                          (req.run_id,)).fetchall()
        assert [r["response_json"]["decision"] for r in calls if r["kind"] == "model"] == script
        assert len(calls) == 4
        manifest = c.execute("SELECT manifest_json FROM support_agent_run WHERE run_id=%s",
                             (req.run_id,)).fetchone()["manifest_json"]
        assert manifest["code"]["grounding.py"] == hashlib.sha256(
            (root / "agent/src/resolveflow/support/grounding.py").read_bytes()).hexdigest()
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    models[0] = TokenizedScript(mode="live", script=script)
    before = list(sources.calls)
    assert runtime.run(req, "new-test-bound") == result
    assert models[0].calls == 0 and sources.calls == before
