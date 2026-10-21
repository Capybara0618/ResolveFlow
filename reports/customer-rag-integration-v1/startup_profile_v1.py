"""Application prewarm versus lazy startup, using retained read-only PG and the real local encoder."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from fastapi.testclient import TestClient  # noqa: E402

from resolveflow.api.app import create_app  # noqa: E402
from resolveflow.policies.index import PolicyIndex  # noqa: E402
from resolveflow.support.retrieval import retrieve_policy  # noqa: E402
from scripts.customer_rag_benchmark import percentile, write_new  # noqa: E402
from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot  # noqa: E402
from scripts.customer_rag_rerank import digest  # noqa: E402


def evaluate(output: Path, *, prewarm: bool) -> None:
    if output.exists():
        raise FileExistsError("startup profile output is immutable")
    model_path = str(ROOT / "tmp/c071-probe/models/BAAI--bge-small-zh-v1.5")
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        RESOLVEFLOW_POLICY_INDEX="1",
        RESOLVEFLOW_EMBEDDING_PATH=model_path,
        RESOLVEFLOW_SUPPORT_PREWARM="1" if prewarm else "0",
    )
    plan = json.loads((ROOT / "evals/customer-rag-v1/queries.json").read_text(encoding="utf-8"))
    source = ROOT / "reports/customer-agent-live-v1/runtime-results.json"
    if digest(source) != plan["source_sha256"]:
        raise ValueError("saved query source changed")
    runs = {r["case"]: r for r in json.loads(source.read_text(encoding="utf-8"))["runs"]}
    database = ReadOnlyDatabase("postgresql://agent:agent@127.0.0.1:55433/agent_db")
    index = PolicyIndex(database)
    work = ROOT / "tmp/customer-rag-integration-v1" / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=False)
    app = create_app(provider_db=work / "provider.sqlite3", delivery_loop=False, worker_loop=False, migrate=False)
    try:
        before = snapshot(database)
        startup = time.perf_counter()
        with TestClient(app) as client:
            startup_ms = (time.perf_counter() - startup) * 1000
            if client.get("/health").status_code != 200:
                raise ValueError("application did not become ready")
            warmup = dict(app.state.support_warmup)
            encoder = app.state.support_embeddings.get(model_path)
            rows = []
            for round_index in range(3):
                for case in plan["cases"]:
                    run = runs[case["source_case"]]
                    manifest = run["run"]["input_json"]["context"]["policy_manifest"]
                    query = case.get("query") or next(
                        c["request_json"]["arguments"]["query"]
                        for c in run["calls"]
                        if c["request_json"].get("name") == "search_policy"
                    )
                    timings = {}
                    started = time.perf_counter()
                    hits = retrieve_policy(
                        index,
                        merchant_id=manifest["merchant_id"],
                        bundle_ids=manifest["bundle_ids"],
                        manifest_hash=manifest["manifest_hash"],
                        generation_ids=run["run"]["generations_json"],
                        query=query,
                        top_k=5,
                        embedder=encoder,
                        timings=timings,
                    )
                    elapsed = (time.perf_counter() - started) * 1000
                    rows.append({
                        "id": case["id"], "round": round_index,
                        "elapsed_ms": elapsed, "stages": timings,
                        "rule_ids": [hit.rule_id for hit in hits],
                        "complete_at_3": set(case["required_rules"]) <= {h.rule_id for h in hits[:3]},
                        "complete_at_5": set(case["required_rules"]) <= {h.rule_id for h in hits},
                    })
            reused = app.state.support_embeddings.get(model_path) is encoder
            after = snapshot(database)
            if before != after:
                raise ValueError("retained public data changed")
        import torch

        write_new(output, {
            "version": "support-startup-profile-v1", "prewarm_enabled": prewarm,
            "runner_sha256": digest(Path(__file__)),
            "source_sha256": digest(source),
            "scope": "Fresh process, real app lifespan/shared weights + retrieve_policy/read-only PG; no HTTP business workers or generative model.",
            "thread_configuration": {"intra": torch.get_num_threads(), "interop": torch.get_num_interop_threads(),
                                     "changed_by_probe": False},
            "model": {"name": encoder.model, "revision": encoder.revision, "dimension": encoder.dimension},
            "startup_ms": startup_ms, "warmup": warmup,
            "same_application_encoder": reused,
            "first_query_ms": rows[0]["elapsed_ms"],
            "queries_n": len(rows),
            "all_query_p50_ms": percentile([r["elapsed_ms"] for r in rows], 0.5),
            "all_query_p95_ms": percentile([r["elapsed_ms"] for r in rows], 0.95),
            "later_query_p50_ms": percentile([r["elapsed_ms"] for r in rows[1:]], 0.5),
            "later_query_p95_ms": percentile([r["elapsed_ms"] for r in rows[1:]], 0.95),
            "preservation": {"before": before, "after": after, "equal": True},
            "rows": rows,
        })
    finally:
        database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prewarm", choices=["0", "1"], required=True)
    args = parser.parse_args()
    evaluate(args.output, prewarm=args.prewarm == "1")
