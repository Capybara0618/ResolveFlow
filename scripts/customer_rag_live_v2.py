"""Finite live Agent/RAG diagnostic with frozen synthetic HTTP facts and read-only retained policies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from resolveflow.api.app import create_app  # noqa: E402
from resolveflow.api.identity import mint_service_token  # noqa: E402
from resolveflow.policies.index import PolicyIndex  # noqa: E402
from resolveflow.runtime.db import Database, create_schema, drop_schema  # noqa: E402
from resolveflow.runtime.factory import DeploymentConfig  # noqa: E402
from resolveflow.support.protocol import SupportInput  # noqa: E402
from resolveflow.support.service import SupportRuntime  # noqa: E402
from resolveflow.support.sources import BoundSources  # noqa: E402
from scripts.agent_eval import allowance  # noqa: E402
from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot  # noqa: E402
from scripts.evaluation.models import live_guard  # noqa: E402

PLAN = ROOT / "evals/customer-rag-live-v2/cases.json"
DSN = "postgresql://agent:agent@127.0.0.1:55433/agent_db"
MODEL_PATH = str(ROOT / "tmp/c071-probe/models/BAAI--bge-small-zh-v1.5")
SECRET = "support-diagnostic-local-only-secret"  # noqa: S105 - local test identity, no production credential


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def persist(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".pending", delete=False) as file:
        file.write(payload)
        pending = Path(file.name)
    for attempt in range(20):
        try:
            pending.replace(path)
            return
        except OSError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def load_plan():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if digest(ROOT / plan["source"]["path"]) != plan["source"]["sha256"]:
        raise ValueError("historical snapshot changed")
    if digest(ROOT / "agent/src/resolveflow/assets/support-guide-v1.json") != plan["guide_asset_sha256"]:
        raise ValueError("frozen guide changed")
    if len(plan["cases"]) != 12 or len({c["id"] for c in plan["cases"]}) != 12:
        raise ValueError("expected twelve distinct cases")
    return plan


class RecordedModel:
    """Record before transmission, including failed/unknown attempts; delegate production request preparation."""

    def __init__(self, client, usage, save):
        self.client, self.usage, self.save = client, usage, save
        self.records = []

    def __getattr__(self, name):
        return getattr(self.client, name)

    def decide(self, **kwargs):
        record = {
            "body": self.client.prepare_request(
                system=kwargs["system"], messages=kwargs["messages"], max_output_tokens=kwargs["max_output_tokens"]
            ),
            "state": "STARTED",
        }
        self.usage["used"] += 1
        self.usage["save"]()
        self.records.append(record)
        self.save(self.records)
        started = time.perf_counter()
        try:
            reply = self.client.decide(**kwargs)
            record.update(
                state="COMPLETE",
                decision=reply.decision,
                usage=asdict(reply.usage),
                mode=reply.mode,
                served_model=reply.model_alias,
            )
            return reply
        except Exception as error:
            # Exception text/provider body can contain sensitive content; the journal retains no headers.
            record.update(state="ERROR", error_type=type(error).__name__)
            raise
        finally:
            record["elapsed_ms"] = (time.perf_counter() - started) * 1000
            self.save(self.records)


def upstream_for(case, request, paths):
    """Synthetic snapshots are bound to one run URL; arbitrary routes or identities cannot leak across cases."""
    prefix = "/internal/v1/support/turns/" + request.run_id

    def transport(call):
        paths.append(call.url.path)
        if call.url.host != "frozen-case.local" or call.url.path == prefix:
            return httpx.Response(403)
        if call.url.path == prefix + "/current":
            return httpx.Response(
                200,
                json={
                    "conversation_id": request.conversation_id,
                    "input_version": request.input_version,
                },
            )
        routes = {"order": "get_order_context", "shipment": "get_shipment_trace", "history": "read_history"}
        for suffix, tool in routes.items():
            if call.url.path == prefix + "/facts/" + suffix:
                if tool == "read_history":
                    return httpx.Response(200, json={"version": 1, "messages": []})
                return httpx.Response(case["http_status"].get(tool, 404), json=case["facts"].get(tool, {}))
        return httpx.Response(403)

    return transport


class MeasuredSources(BoundSources):
    def __init__(self, *args, records, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = records

    def read(self, name, arguments):
        started = time.perf_counter()
        value = super().read(name, arguments)
        self.records.append({"name": name, "elapsed_ms": (time.perf_counter() - started) * 1000, "result": value})
        return value

    def search(self, query, top_k):
        started = time.perf_counter()
        value = super().search(query, top_k)
        self.records.append(
            {
                "name": "search_policy",
                "query": query,
                "top_k": top_k,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
                "result": value,
            }
        )
        return value


def remaining_cases(plan, previous):
    if previous["plan_sha256"] != digest(PLAN) or not previous.get("isolated_schema_dropped"):
        raise ValueError("continuation requires the unchanged plan and cleaned prior schema")
    started = {row["id"] for row in previous["rows"]}
    expected = {case["id"] for case in plan["cases"]}
    if not started <= expected or len(started) != len(previous["rows"]):
        raise ValueError("prior cohort contains unknown or duplicate cases")
    remaining = [case for case in plan["cases"] if case["id"] not in started]
    if not remaining:
        raise ValueError("no unstarted cases remain")
    return remaining


def evaluate(output, usage_path, continue_from=None):
    if output.exists():
        raise FileExistsError("live report already exists; never rerun paid cases under a new identity")
    plan = load_plan()
    key = (os.environ.get("RESOLVEFLOW_MODEL_API_KEY") or os.environ.get("Deepseek_API_KEY") or "").strip()
    if not key:
        raise ValueError("missing model key in environment")
    paths = [
        "agent/src/resolveflow/support/engine.py",
        "agent/src/resolveflow/support/sources.py",
        "agent/src/resolveflow/support/service.py",
        "agent/src/resolveflow/support/protocol.py",
        "agent/src/resolveflow/support/store.py",
        "agent/src/resolveflow/support/guide.py",
        "agent/src/resolveflow/support/embeddings.py",
        "agent/src/resolveflow/support/retrieval.py",
        "agent/src/resolveflow/harness/live_model.py",
        "agent/src/resolveflow/harness/sdk_adapter.py",
        "agent/src/resolveflow/api/app.py",
        "agent/uv.lock",
        "scripts/customer_rag_live_v2.py",
    ]
    report = {
        "version": "customer-rag-live-v2",
        "state": "PREPARING",
        "synthetic": True,
        "not_holdout": True,
        "scope": plan["factual_scope"],
        "plan_sha256": digest(PLAN),
        "fingerprints": {p: digest(ROOT / p) for p in paths},
        "rows": [],
    }
    if continue_from is not None:
        previous = json.loads(continue_from.read_text(encoding="utf-8"))
        plan["cases"] = remaining_cases(plan, previous)
        if any(
            report["fingerprints"][p] != h
            for p, h in previous["fingerprints"].items()
            if p != "scripts/customer_rag_live_v2.py"
        ):
            raise ValueError("production source changed between cohorts")
        report["continued_from"] = {"path": str(continue_from), "sha256": digest(continue_from)}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    schema = "t_support_live_v2_" + uuid.uuid4().hex[:12]
    private = ROOT / "tmp/customer-rag-live-v2" / schema
    private.mkdir(parents=True, exist_ok=False)
    persist(private / "ownership.json", {"schema": schema, "report": str(output.resolve())})
    retained = ReadOnlyDatabase(DSN)
    journal_db = Database(DSN, schema=schema)
    created = False
    try:
        before = snapshot(retained)
        report["preservation_before"] = before
        persist(output, report)
        create_schema(DSN, schema)
        created = True
        journal_db.migrations()
        os.environ.update(
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            RESOLVEFLOW_POLICY_INDEX="1",
            RESOLVEFLOW_EMBEDDING_PATH=MODEL_PATH,
            RESOLVEFLOW_SUPPORT_PREWARM="1",
        )
        app = create_app(
            provider_db=private / "provider.sqlite3",
            delivery_loop=False,
            worker_loop=False,
            migrate=False,
            jwt_secret=SECRET,
        )
        with live_guard(usage_path), TestClient(app) as api:
            usage = allowance(usage_path)
            report.update(state="RUNNING", usage_before=usage["used"], warmup=dict(app.state.support_warmup))
            persist(output, report)
            index = PolicyIndex(retained)
            for case in plan["cases"]:
                request = SupportInput.model_validate(
                    {
                        **case["input_without_deadline"],
                        "deadline_at": (datetime.now(UTC) + timedelta(seconds=120)).isoformat(),
                    }
                )
                row = {"id": case["id"], "group": case["group"], "state": "STARTED", "models": [], "tools": []}
                report["rows"].append(row)
                persist(output, report)

                def save(records, current=row):
                    current["models"] = records
                    persist(output, report)

                config = DeploymentConfig(
                    mode="live",
                    provider="deepseek",
                    model_id="deepseek-flash",
                    endpoint="https://api.deepseek.com/chat/completions",
                    api_key=key,
                    policy_index=True,
                    embedding_path=MODEL_PATH,
                )
                runtime = SupportRuntime(journal_db, config, embeddings=app.state.support_embeddings)
                model = RecordedModel(runtime._model(), usage, save)
                runtime.model_factory = lambda current=model: current
                row["upstream_paths"] = []
                frozen_transport = httpx.MockTransport(upstream_for(case, request, row["upstream_paths"]))
                with httpx.Client(transport=frozen_transport) as http:

                    def sources(bound, token, journal, selected=case, client=http, current=row):
                        journal.pin_generations(selected["pinned_generations"])
                        return MeasuredSources(
                            bound,
                            case_url="http://frozen-case.local",
                            token=token,
                            index=index,
                            embedder=app.state.support_embeddings.get(MODEL_PATH),
                            journal=journal,
                            client=client,
                            records=current["tools"],
                        )

                    runtime.sources_factory = sources
                    app.state.support_runtime = runtime
                    token = mint_service_token(
                        "case-service",
                        SECRET,
                        scope="support:run",
                        merchant_id=request.merchant_id,
                        customer_id=request.customer_id,
                    )
                    started = time.perf_counter()
                    response = api.post(
                        "/internal/v1/support-runs",
                        headers={"Authorization": "Bearer " + token},
                        json={**request.model_dump(mode="json"), "tool_token": "frozen-read-token"},
                    )
                    row.update(
                        state="FINISHED",
                        http_status=response.status_code,
                        elapsed_ms=(time.perf_counter() - started) * 1000,
                        result=response.json(),
                    )
                with journal_db.connection() as connection:
                    row["run"] = connection.execute(
                        "SELECT * FROM support_agent_run WHERE run_id=%s", (request.run_id,)
                    ).fetchone()
                    row["calls"] = connection.execute(
                        "SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY kind,position", (request.run_id,)
                    ).fetchall()
                persist(output, report)
                print(
                    json.dumps(
                        {
                            "id": case["id"],
                            "http": row["http_status"],
                            "status": row["result"].get("status"),
                            "calls": len(row["models"]),
                            "elapsed_ms": round(row["elapsed_ms"], 1),
                        }
                    ),
                    flush=True,
                )
            report["usage_after"] = usage["used"]
        after = snapshot(retained)
        report["preservation"] = {"before": before, "after": after, "equal": before == after}
        if before != after:
            raise ValueError("retained public data changed")
        report["state"] = "FINISHED"
    except Exception as error:
        report.update(state="ERROR", error_type=type(error).__name__)
        raise
    finally:
        journal_db.close()
        if created:
            # Exact schema was generated here, recorded before creation, and never public.
            drop_schema(DSN, schema)
        retained.close()
        report["isolated_schema_dropped"] = created
        persist(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-usage", type=Path, default=ROOT / "tmp/evaluation-live-budget.json")
    parser.add_argument("--continue-from", type=Path)
    args = parser.parse_args()
    if not args.execute:
        parser.error("explicit --execute is required for live calls")
    evaluate(args.output, args.live_usage, args.continue_from)
