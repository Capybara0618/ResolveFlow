"""Finite autonomous experience diagnostic; real previous results, no fixed group or resume metrics."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from scripts import customer_agent_eval_v2 as baseline

DIRECTORY = ROOT / "evals/customer-agent-experience-v1"
PLAN = DIRECTORY / "manifest.json"
SELECTION = [("U01", "D01", 1), ("U02", "D02", 1), ("U03", "D06", 1), ("U04", "D07", 1), ("U05", "D13", 4)]
DSN, MODEL_PATH, SECRET = baseline.DSN, baseline.MODEL_PATH, baseline.SECRET
RecordedModel, MeasuredSources = baseline.RecordedModel, baseline.MeasuredSources
read_json, digest, write_new, persist = baseline.read_json, baseline.digest, baseline.write_new, baseline.persist
upstream_for = baseline.upstream_for


def load_cases():
    originals = {c["id"]: c for c in baseline.load_cases()}
    cases = read_json(DIRECTORY / "scenarios.json")["cases"]
    if len(cases) != len(SELECTION):
        raise ValueError("expected exactly five conversations/eight turns")
    for case, (name, source, count) in zip(cases, SELECTION, strict=True):
        old = originals[source]
        if (case["id"] != name or case["source_case"] != source or case["snapshot_id"] != old["snapshot_id"]
                or case["turns"] != old["turns"][:count]):
            raise ValueError("original questions/facts/conditions changed")
        case["snapshot"] = deepcopy(old["snapshot"])
    return cases


def prepare_turn(case, turn_index, completed):
    return baseline.prepare_turn({**case, "id": "experience-v1:" + case["id"]}, turn_index, completed, "agent")


def freeze(path=PLAN):
    load_cases()
    prior = read_json(ROOT / "evals/customer-agent-read-first-v1/manifest.json")
    files = set(prior["files"]) | {
        "evals/customer-agent-read-first-v1/manifest.json", "reports/customer-agent-read-first-v1/runtime-results.json",
        "scripts/customer_agent_experience_v1.py", "evals/customer-agent-experience-v1/scenarios.json",
        "agent/tests/unit/test_customer_agent_experience_v1.py", "agent/tests/integration/test_customer_agent_experience_v1.py",
        "agent/tests/unit/test_support_response_contract.py", "agent/tests/unit/test_support_publication_feedback.py",
        "docs/customer-agent-experience-v1.md",
    }
    write_new(path, {"version": "customer-agent-experience-v1", "conversations": 5, "turns": 8,
                     "not_resume_metrics": True, "synthetic_facts": True, "not_holdout": True,
                     "files": {p: digest(ROOT / p) for p in sorted(files)},
                     "embedding_files": prior["embedding_files"]})


def load_plan(path=PLAN):
    plan = read_json(path)
    for name, fingerprint in plan["files"].items():
        if digest(ROOT / name) != fingerprint:
            raise ValueError("frozen source changed: " + name)
    for name, fingerprint in plan["embedding_files"].items():
        if digest(Path(MODEL_PATH) / name) != fingerprint:
            raise ValueError("embedding changed: " + name)
    return plan, load_cases()


def evaluate(output, usage_path):
    import httpx
    from fastapi.testclient import TestClient
    from resolveflow.api.app import create_app
    from resolveflow.api.identity import mint_service_token
    from resolveflow.policies.index import PolicyIndex
    from resolveflow.runtime.db import Database, create_schema, drop_schema
    from resolveflow.runtime.factory import DeploymentConfig
    from resolveflow.support.service import SupportRuntime

    from scripts.agent_eval import allowance
    from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot
    from scripts.evaluation.models import live_guard

    plan, cases = load_plan()
    if output.exists():
        raise FileExistsError("evaluation already started; inspect saved attempts instead of rerunning")
    key = (os.getenv("RESOLVEFLOW_MODEL_API_KEY") or os.getenv("Deepseek_API_KEY") or "").strip()
    if not key:
        raise ValueError("missing model key")
    report = {"version": plan["version"], "plan_sha256": digest(PLAN), "state": "PREPARING",
              "synthetic_facts": True, "real_generation": True, "not_resume_metrics": True, "rows": []}
    write_new(output, report)
    schema = "t_support_experience_v1_" + uuid.uuid4().hex[:12]
    private = ROOT / "tmp/customer-agent-experience-v1" / schema
    private.mkdir(parents=True, exist_ok=False)
    write_new(private / "ownership.json", {"schema": schema, "report": str(output.resolve())})
    retained, db = ReadOnlyDatabase(DSN), Database(DSN, schema=schema)
    created, exported = False, False
    try:
        report["public_before"] = snapshot(retained)
        create_schema(DSN, schema)
        created = True
        db.migrations()
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", RESOLVEFLOW_POLICY_INDEX="1",
                          RESOLVEFLOW_EMBEDDING_PATH=MODEL_PATH, RESOLVEFLOW_SUPPORT_PREWARM="1")
        app = create_app(provider_db=private / "provider.sqlite3", delivery_loop=False,
                         worker_loop=False, migrate=False, jwt_secret=SECRET)
        with live_guard(usage_path), TestClient(app) as api:
            usage = allowance(usage_path)
            report.update(state="RUNNING", usage_before=usage["used"], warmup=dict(app.state.support_warmup))
            index = PolicyIndex(retained)
            for case in cases:
                completed = []
                for turn_index in range(len(case["turns"])):
                    request, archive = prepare_turn(case, turn_index, completed)
                    row = {"id": case["id"], "variant": "agent", "turn": turn_index + 1, "state": "STARTED",
                           "input": request.model_dump(mode="json"), "models": [], "tools": [], "paths": []}
                    report["rows"].append(row)
                    persist(output, report)

                    def save(records, current=row):
                        current["models"] = records
                        persist(output, report)

                    config = DeploymentConfig(mode="live", provider="deepseek", model_id="deepseek-flash",
                                              endpoint="https://api.deepseek.com/chat/completions", api_key=key,
                                              policy_index=True, embedding_path=MODEL_PATH)
                    runtime = SupportRuntime(db, config, embeddings=app.state.support_embeddings)
                    model = RecordedModel(runtime._model(), usage, save)
                    runtime.model_factory = lambda current=model: current
                    with httpx.Client(transport=httpx.MockTransport(
                        upstream_for(case["snapshot"], request, archive, row["paths"])
                    )) as upstream:

                        def sources(bound, token, journal, selected=case, client=upstream, current=row):
                            journal.pin_generations(selected["snapshot"]["pinned_generations"])
                            return MeasuredSources(bound, case_url="http://frozen-case.local", token=token,
                                                   index=index, embedder=app.state.support_embeddings.get(MODEL_PATH),
                                                   journal=journal, client=client, records=current["tools"])

                        runtime.sources_factory = sources
                        app.state.support_runtime = runtime
                        token = mint_service_token("case-service", SECRET, scope="support:run",
                                                   merchant_id=request.merchant_id, customer_id=request.customer_id)
                        started = time.perf_counter()
                        response = api.post("/internal/v1/support-runs", headers={"Authorization": "Bearer " + token},
                                            json={**request.model_dump(mode="json"), "tool_token": "frozen-read-token"})
                        row.update(state="FINISHED", http_status=response.status_code,
                                   elapsed_ms=(time.perf_counter() - started) * 1000, result=response.json())
                    if response.status_code != 200:
                        raise ValueError("unexpected API rejection; preserve started cohort")
                    completed.append(row["result"])
                    with db.connection() as c:
                        row["run"] = c.execute("SELECT * FROM support_agent_run WHERE run_id=%s",
                                               (request.run_id,)).fetchone()
                        row["calls"] = c.execute("SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY kind,position",
                                                 (request.run_id,)).fetchall()
                    persist(output, report)
                    print(json.dumps({"id": row["id"], "group": "agent", "turn": row["turn"],
                                      "status": row["result"]["status"], "reason": row["result"].get("reason"),
                                      "models": len(row["models"]), "ms": round(row["elapsed_ms"])}), flush=True)
            report["usage_after"] = usage["used"]
        report["public_after"] = snapshot(retained)
        if report["public_before"] != report["public_after"]:
            raise ValueError("retained public data changed")
        report["state"] = "FINISHED"
    except Exception as error:
        report.update(state="ERROR", error_type=type(error).__name__)
        raise
    finally:
        # Export even the started/error attempts before removing this run's owned schema.
        try:
            if created:
                with db.connection() as c:
                    report["all_runs"] = c.execute("SELECT * FROM support_agent_run ORDER BY run_id").fetchall()
                    report["all_calls"] = c.execute("SELECT * FROM support_agent_call ORDER BY run_id,kind,position").fetchall()
            persist(output, report)
            exported = True
        finally:
            db.close()
            if created and exported:
                drop_schema(DSN, schema)
            retained.close()
        report["isolated_schema_dropped"] = created and exported
        persist(output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live-usage", type=Path, default=ROOT / "tmp/evaluation-live-budget.json")
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.check:
        plan, cases = load_plan()
        result = {"version": plan["version"], "conversations": len(cases),
                  "turns": sum(len(c["turns"]) for c in cases), "new_models": 0, "not_resume_metrics": True}
        if args.database:
            result["database"] = baseline.previous.check_database(cases, DSN)
        if args.output:
            write_new(args.output, result)
        print(json.dumps({k: v for k, v in result.items() if k != "database"}))
    elif args.output is None:
        parser.error("--output required")
    else:
        evaluate(args.output, args.live_usage)


if __name__ == "__main__":
    main()
