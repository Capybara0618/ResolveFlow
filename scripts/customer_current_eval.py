"""One frozen current-version cohort; real streaming model, synthetic scoped facts, readonly policies."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

import httpx
from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.support.progress import ProgressReporter
from resolveflow.support.sources import BoundSources

from scripts import customer_agent_readiness as previous
from scripts.agent_eval import allowance
from scripts.customer_agent_eval_v2 import (
    digest,
    load_cases,
    read_json,
    upstream_for,
    write_new,
)
from scripts.customer_rag_live_v2 import DSN, MODEL_PATH, persist
from scripts.evaluation.models import live_guard

VERSION = "customer-current-evaluation-v1"
PLAN = ROOT / "evals" / VERSION / "manifest.json"
DIRECTORY = ROOT / "reports" / VERSION


def prepare_turn(case, turn_index, completed):
    """Match Java's latest accepted state, including failed accepted plans; no invented answer."""
    scoped = {**case, "id": VERSION + ":" + case["id"]}
    request, archive = previous.prepare_turn(scoped, turn_index, completed)
    request.context["previous_tasks"] = None
    for result in reversed(completed):
        update = result.get("conversation_update")
        accepted = update if update and update.get("version") == "support-state-v1" else None
        if result["status"] != "SUCCEEDED" and accepted is None:
            continue
        state = accepted or result["answer"]
        if accepted is not None and any(accepted.get(k) != result.get(k) for k in (
            "run_id", "conversation_id", "input_version"
        )):
            raise ValueError("accepted update identity mismatch")
        task_state = state.get("task_state") or {}
        tasks = task_state.get("tasks")
        if (task_state.get("origin") == "MODEL" and isinstance(tasks, list) and 0 < len(tasks) <= 8
                and len(json.dumps(task_state, ensure_ascii=False, separators=(",", ":"))) <= 12000):
            request.context["previous_tasks"] = {
                "origin": "MODEL_PREVIOUS_TURN", "input_version": result["input_version"],
                "tasks": deepcopy(tasks),
            }
        memory = state.get("customer_memory")
        if memory is not None:
            if any(memory.get(k) != getattr(request, k) for k in (
                "conversation_id", "merchant_id", "customer_id", "line_id"
            )) or memory.get("input_version") != result["input_version"]:
                raise ValueError("accepted memory scope mismatch")
            request.context["previous_customer_memory"] = deepcopy(memory)
        break
    return request, archive


class RecordedStreamingModel(StreamingLiveModelClient):
    def __init__(self, *, usage, save, **kwargs):
        super().__init__(**kwargs)
        self.usage_ledger, self.save, self.records = usage, save, []

    def decide(self, **kwargs):
        record = {"body": self.prepare_request(system=kwargs["system"], messages=kwargs["messages"],
                                                max_output_tokens=kwargs["max_output_tokens"]), "state": "STARTED"}
        self.usage_ledger["used"] += 1
        self.usage_ledger["save"]()
        self.records.append(record)
        self.save(self.records)
        started = time.perf_counter()
        try:
            reply = super().decide(**kwargs)
            record.update(state="COMPLETE", decision=reply.decision, usage=asdict(reply.usage),
                          mode=reply.mode, served_model=reply.model_alias)
            return reply
        except Exception as error:
            record.update(state="ERROR", error_type=type(error).__name__)
            raise
        finally:
            record.update(elapsed_ms=(time.perf_counter() - started) * 1000, stream=self.last_stream)
            self.save(self.records)


class MeasuredSources(BoundSources):
    def __init__(self, *args, records, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = records

    def read(self, name, arguments):
        started = time.perf_counter()
        value = super().read(name, arguments)
        self.records.append({"name": name, "arguments": arguments,
                             "elapsed_ms": (time.perf_counter() - started) * 1000, "result": value})
        return value

    def search(self, query, top_k, *, sub_queries=None):
        started = time.perf_counter()
        value = super().search(query, top_k, sub_queries=sub_queries)
        self.records.append({"name": "search_policy", "query": query, "top_k": top_k, "sub_queries": sub_queries,
                             "elapsed_ms": (time.perf_counter() - started) * 1000, "result": value})
        return value


def stream_times(events, succeeded):
    deltas = [e for e in events if e["kind"] == "answer.delta" and e["payload"].get("text")]
    last_reset = max((i for i, e in enumerate(events) if e["kind"] == "answer.reset"), default=-1)
    surviving = [e for e in events[last_reset + 1:] if e["kind"] == "answer.delta" and e["payload"].get("text")]
    return {"first_provisional_ms": deltas[0]["elapsed_ms"] if deltas else None,
            "first_retained_ms": surviving[0]["elapsed_ms"] if succeeded and surviving else None,
            "resets": sum(e["kind"] == "answer.reset" for e in events)}


def freeze(path=PLAN):
    load_cases()
    files = {
        "docs/customer-current-evaluation-v1.md", "scripts/customer_current_eval.py",
        "scripts/customer_current_rag.py", "scripts/customer_agent_eval_v2.py",
        "scripts/customer_agent_readiness.py", "scripts/customer_rag_live_v2.py",
        "scripts/customer_rag_diagnostic.py", "scripts/customer_rag_external.py",
        "scripts/agent_eval.py", "scripts/evaluation/models.py", "agent/uv.lock",
        "agent/tests/unit/test_customer_current_eval.py", "agent/tests/integration/test_customer_current_eval.py",
        "evals/customer-agent-eval-v2/scenarios.json", "evals/customer-agent-live-v3/cases.json",
        "evals/customer-agent-readiness-v1/scenarios.json", "evals/customer-rag-v1/queries.json",
        "reports/customer-agent-live-v1/runtime-results.json",
        "evals/policy-query-v1/manifest.json", "evals/policy-query-v1/queries.json",
        "evals/policy-query-v1/evidence.json", "evals/rag-codex-review-v1/labels.json",
        "tmp/policy-documents-v1/children-final.json", "tmp/policy-documents-v1/drafts-audited.json",
        "tmp/rag-structure-v1/vectors-v1.json", "reports/policy-document-ingestion/draft-summary.json",
    }
    for directory in ["support", "harness", "policies", "runtime"]:
        files.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "agent/src/resolveflow" / directory).glob("*.py"))
    files.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "agent/src/resolveflow/assets").glob("support-guide-*.json"))
    files.update("scripts/" + p for p in ["policy_chunks.py", "policy_codex_review.py",
                                        "policy_context_packet_eval.py", "policy_query_eval.py"])
    embedding = read_json(ROOT / "evals/customer-rag-v5/manifest.json")["embedding_files"]
    write_new(path, {"version": VERSION, "architecture": "orchestrated-v1", "conversations": 14, "turns": 44,
                     "source_visible_regression": True, "independent_holdout": False,
                     "files": {p: digest(ROOT / p) for p in sorted(files)},
                     "embedding_files": {p: digest(Path(MODEL_PATH) / p) for p in embedding}})


def load_plan(path=PLAN):
    plan = read_json(path)
    for p, h in plan["files"].items():
        if digest(ROOT / p) != h:
            raise ValueError("frozen source changed: " + p)
    for p, h in plan["embedding_files"].items():
        if digest(Path(MODEL_PATH) / p) != h:
            raise ValueError("frozen embedding changed: " + p)
    return plan, load_cases()


def evaluate(output, usage_path):
    from resolveflow.policies.index import PolicyIndex
    from resolveflow.runtime.db import Database, create_schema, drop_schema
    from resolveflow.runtime.factory import DeploymentConfig
    from resolveflow.support.embeddings import SupportEmbeddings
    from resolveflow.support.service import SupportRuntime

    from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot

    plan, cases = load_plan()
    key = (os.getenv("RESOLVEFLOW_MODEL_API_KEY") or os.getenv("Deepseek_API_KEY") or "").strip()
    if not key:
        raise ValueError("missing model key")
    report = {"version": VERSION, "plan_sha256": digest(PLAN), "state": "PREPARING", "rows": [],
              "real_generation": True, "synthetic_http_facts": True, "business_end_to_end": False}
    write_new(output, report)
    schema = "t_support_current_v1_" + uuid.uuid4().hex[:12]
    private = ROOT / "tmp" / VERSION / schema
    write_new(private / "ownership.json", {"schema": schema, "output": str(output.resolve())})
    retained, db = ReadOnlyDatabase(DSN), Database(DSN, schema=schema)
    created = exported = False
    try:
        report["public_before"] = snapshot(retained)
        create_schema(DSN, schema)
        created = True
        db.migrations()
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        import torch

        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        pool = SupportEmbeddings()
        report["prewarm_ms"] = pool.prewarm(MODEL_PATH)
        index = PolicyIndex(retained)
        with live_guard(usage_path):
            usage = allowance(usage_path)
            report.update(state="RUNNING", usage_before=usage["used"])
            for case in cases:
                completed = []
                for turn_index in range(len(case["turns"])):
                    request, archive = prepare_turn(case, turn_index, completed)
                    row = {"id": case["id"], "family": case["scenario"], "turn": turn_index + 1, "state": "STARTED",
                           "input": request.model_dump(mode="json"), "models": [], "tools": [], "paths": [], "events": []}
                    report["rows"].append(row)
                    persist(output, report)

                    checkpoint = private / f"{case['id']}-{turn_index + 1}.json"

                    def save(records, current=row, checkpoint=checkpoint):
                        current["models"] = records
                        persist(checkpoint, current)

                    model = RecordedStreamingModel(usage=usage, save=save, provider="deepseek",
                        model_id="deepseek-flash", endpoint="https://api.deepseek.com/chat/completions", api_key=key,
                        timeout_seconds=30, parameters={"thinking": {"type": "disabled"},
                        "response_format": {"type": "json_object"}, "temperature": 0})
                    config = DeploymentConfig(mode="live", provider="deepseek", model_id="deepseek-flash",
                        endpoint=model.endpoint, api_key=key, policy_index=True, embedding_path=MODEL_PATH,
                        context_window_tokens=32768, case_base_url="http://frozen-case.local")
                    runtime = SupportRuntime(db, config, model_factory=lambda current=model: current,
                                             embeddings=pool, architecture=plan["architecture"])
                    with httpx.Client(transport=httpx.MockTransport(
                        upstream_for(case["snapshot"], request, archive, row["paths"])
                    )) as client:

                        def sources(bound, token, journal, selected=case, client=client, current=row, config=config):
                            journal.pin_generations(selected["snapshot"]["pinned_generations"])
                            return MeasuredSources(bound, case_url=config.case_base_url, token=token, index=index,
                                embedder=pool.get(MODEL_PATH), journal=journal, client=client, records=current["tools"])

                        runtime.sources_factory = sources
                        started = time.perf_counter()

                        def receive(call, current=row, run=request.run_id, start=started):
                            if call.url.host != "frozen-case.local" or call.url.path != (
                                "/internal/v1/support/turns/" + run + "/stream-events"
                            ) or call.method != "POST":
                                return httpx.Response(403)
                            body = json.loads(call.content)
                            current["events"].extend({**event, "batch_sequence": body["batch_sequence"],
                                "elapsed_ms": (time.perf_counter() - start) * 1000} for event in body["events"])
                            return httpx.Response(200, json={})

                        reporters = []

                        def progress(url, run, token, reporters=reporters):
                            reporter = ProgressReporter(url, run, token, transport=httpx.MockTransport(receive))
                            reporters.append(reporter)
                            return reporter

                        with patch("resolveflow.support.service.ProgressReporter", progress):
                            result = runtime.run(request, "frozen-read-token", progress_token="frozen-progress-token")
                        row.update(state="FINISHED", elapsed_ms=(time.perf_counter() - started) * 1000,
                                   result=result, progress_failure=reporters[0].failure if reporters else None)
                    row["stream_times"] = stream_times(row["events"], result["status"] == "SUCCEEDED")
                    completed.append(result)
                    with db.connection() as connection:
                        row["run"] = connection.execute("SELECT * FROM support_agent_run WHERE run_id=%s",
                                                       (request.run_id,)).fetchone()
                        row["calls"] = connection.execute(
                            "SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY kind,position", (request.run_id,)
                        ).fetchall()
                    persist(output, report)
                    print(json.dumps({"id": row["id"], "turn": row["turn"], "status": result["status"],
                                      "reason": result.get("reason"), "models": len(model.records),
                                      "ms": round(row["elapsed_ms"])}), flush=True)
            report["usage_after"] = usage["used"]
        report["public_after"] = snapshot(retained)
        if report["public_before"] != report["public_after"]:
            raise ValueError("retained public data changed")
        load_plan()
        report["state"] = "FINISHED"
    except Exception as error:
        report.update(state="ERROR", error_type=type(error).__name__)
        raise
    finally:
        try:
            if created:
                with db.connection() as connection:
                    report["all_runs"] = connection.execute("SELECT * FROM support_agent_run ORDER BY run_id").fetchall()
                    report["all_calls"] = connection.execute(
                        "SELECT * FROM support_agent_call ORDER BY run_id,kind,position"
                    ).fetchall()
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
    parser.add_argument("mode", choices=["freeze", "check", "execute"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze()
    elif args.mode == "check":
        plan, cases = load_plan()
        result = {"version": VERSION, "conversations": len(cases), "turns": plan["turns"], "new_model_calls": 0,
                  "database": previous.check_database(cases, DSN)}
        if args.output:
            write_new(args.output, result)
        print(json.dumps({k: v for k, v in result.items() if k != "database"}))
    else:
        evaluate(args.output or DIRECTORY / "agent-runtime.json", ROOT / "tmp/evaluation-live-budget.json")


if __name__ == "__main__":
    main()
