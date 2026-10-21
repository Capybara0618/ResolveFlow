"""Frozen paired multi-turn evaluation; live generation, scoped synthetic HTTP, retained readonly policies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from scripts import customer_agent_readiness as previous
from scripts.customer_rag_live_v2 import (
    DSN,
    MODEL_PATH,
    SECRET,
    MeasuredSources,
    RecordedModel,
    persist,
)
from scripts.evaluation.support_fixed_v2 import FixedSupportRuntime

DIRECTORY = ROOT / "evals/customer-agent-eval-v2"
PLAN = DIRECTORY / "manifest.json"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def load_cases():
    cases = read_json(DIRECTORY / "scenarios.json")["cases"]
    snapshots = {c["id"]: c for c in read_json(ROOT / "evals/customer-agent-live-v3/cases.json")["cases"]}
    old = read_json(ROOT / "evals/customer-agent-readiness-v1/scenarios.json")["cases"]
    if cases[:12] != old or len(cases) != 14 or sum(len(c["turns"]) for c in cases) != 44:
        raise ValueError("expected unchanged old inputs and two four-turn extensions")
    if len({c["id"] for c in cases}) != 14:
        raise ValueError("duplicate scenario identity")
    for c in cases:
        c["snapshot"] = deepcopy(snapshots[c["snapshot_id"]])
        for t in c["turns"]:
            if not t["text"].strip() or not t["criteria"]:
                raise ValueError("missing input or scoring conditions")
    return cases


def prepare_turn(case, turn_index, completed, variant):
    if variant not in {"agent", "fixed"}:
        raise ValueError("unknown evaluation variant")
    scoped = {**case, "id": "customer-agent-eval-v2:" + variant + ":" + case["id"]}
    req, archive = previous.prepare_turn(scoped, turn_index, completed)
    for result in reversed(completed):
        if result["status"] != "SUCCEEDED":
            continue
        memory = result["answer"].get("customer_memory")
        if memory is not None:
            if any(memory.get(k) != getattr(req, k) for k in [
                "conversation_id", "merchant_id", "customer_id", "line_id"
            ]) or memory.get("input_version") != result["input_version"]:
                raise ValueError("completed customer memory scope mismatch")
            req.context["previous_customer_memory"] = deepcopy(memory)
        break
    return req, archive


def freeze(path=PLAN):
    load_cases()
    inherited = read_json(ROOT / "evals/customer-agent-readiness-v1/manifest.json")
    files = set(inherited["files"])
    files.update(str(p.relative_to(ROOT)).replace("\\", "/")
                 for p in (ROOT / "agent/src/resolveflow/support").glob("*.py"))
    files.update([
        "scripts/customer_agent_eval_v2.py", "scripts/evaluation/support_fixed_v2.py",
        "scripts/customer_agent_readiness.py", "scripts/customer_rag_live_v2.py",
        "scripts/customer_rag_diagnostic.py", "scripts/agent_eval.py", "scripts/evaluation/models.py",
        "agent/src/resolveflow/harness/live_model.py", "agent/src/resolveflow/harness/model.py",
        "agent/src/resolveflow/harness/sdk_adapter.py", "agent/src/resolveflow/harness/budget.py",
        "agent/src/resolveflow/api/app.py", "agent/src/resolveflow/policies/retrieval.py",
        "agent/src/resolveflow/policies/index.py", "agent/src/resolveflow/policies/child_index.py",
        "agent/src/resolveflow/assets/deepseek-v41/tokenizer.json.gz",
        "agent/tests/unit/test_customer_agent_eval_v2.py", "agent/tests/integration/test_support_dialogue_api.py",
        "agent/tests/integration/test_customer_agent_eval_v2.py",
        "docs/customer-agent-eval-v2.md", "evals/customer-agent-eval-v2/scenarios.json",
        "evals/customer-agent-readiness-v1/manifest.json", "evals/customer-rag-v5/manifest.json",
        "reports/customer-rag-v5/README.md",
    ])
    write_new(path, {"version": "customer-agent-eval-v2", "groups": ["agent", "fixed"],
                     "conversations_per_group": 14, "turns_per_group": 44, "synthetic": True,
                     "not_independent_holdout": True, "semantic_reviewer": "CODEX_SOURCE_REVIEW",
                     "files": {p: digest(ROOT / p) for p in sorted(files)},
                     "embedding_files": read_json(ROOT / "evals/customer-rag-v5/manifest.json")["embedding_files"]})


def load_plan(path=PLAN):
    plan = read_json(path)
    for p, h in plan["files"].items():
        if digest(ROOT / p) != h:
            raise ValueError("frozen source changed: " + p)
    for p, h in plan["embedding_files"].items():
        if digest(Path(MODEL_PATH) / p) != h:
            raise ValueError("frozen local embedding changed: " + p)
    return plan, load_cases()


def upstream_for(case, request, archive, paths):
    prefix = "/internal/v1/support/turns/" + request.run_id

    def transport(call):
        import httpx

        paths.append(call.url.path)
        if call.url.host != "frozen-case.local":
            return httpx.Response(403)
        if call.url.path == prefix + "/current":
            return httpx.Response(200, json={"conversation_id": request.conversation_id,
                                             "input_version": request.input_version})
        if call.url.path == prefix + "/facts/history":
            before = int(call.url.params.get("before_sequence", str(request.input_version + 1)))
            limit = int(call.url.params.get("limit", "5"))
            messages = [m for m in archive if m["sequence"] < before][-limit:]
            return httpx.Response(200, json={"version": request.input_version, "messages": messages})
        for suffix, tool in {"order": "get_order_context", "shipment": "get_shipment_trace"}.items():
            if call.url.path == prefix + "/facts/" + suffix:
                return httpx.Response(case["http_status"].get(tool, 404), json=case["facts"].get(tool, {}))
        return httpx.Response(403)
    return transport


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
              "synthetic_facts": True, "real_generation": True, "rows": []}
    write_new(output, report)
    schema = "t_support_eval_v2_" + uuid.uuid4().hex[:12]
    private = ROOT / "tmp/customer-agent-eval-v2" / schema
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
            for case_index, case in enumerate(cases):
                for variant in (["agent", "fixed"] if case_index % 2 == 0 else ["fixed", "agent"]):
                    completed = []
                    for turn_index in range(len(case["turns"])):
                        request, archive = prepare_turn(case, turn_index, completed, variant)
                        row = {"id": case["id"], "variant": variant, "turn": turn_index + 1, "state": "STARTED",
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
                            app.state.support_runtime = runtime if variant == "agent" else FixedSupportRuntime(
                                db, runtime, sources, report["plan_sha256"])
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
                        print(json.dumps({"id": row["id"], "group": variant, "turn": row["turn"],
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
        result = {"version": plan["version"], "cases_per_group": len(cases), "turns_per_group": 44, "new_models": 0}
        if args.database:
            result["database"] = previous.check_database(cases, DSN)
        if args.output:
            write_new(args.output, result)
        print(json.dumps({k: v for k, v in result.items() if k != "database"}))
    elif args.output is None:
        parser.error("--output required")
    else:
        evaluate(args.output, args.live_usage)


if __name__ == "__main__":
    main()
