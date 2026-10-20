"""Read-only local retrieval diagnostic; never calls a generative model or rebuilds an index."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from resolveflow.policies.index import PolicyIndex
from resolveflow.policies.retrieval import embedder
from resolveflow.runtime.db import Database

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "evals/customer-rag-v1/queries.json"


class ReadOnlyDatabase(Database):
    @contextmanager
    def connection(self):
        with super().connection() as connection:
            connection.execute("SET default_transaction_read_only = on")
            assert (
                connection.execute("SHOW default_transaction_read_only").fetchone()["default_transaction_read_only"]
                == "on"
            )
            yield connection


def snapshot(database):
    """Witness all retained public rows, not only the selected policies."""
    with database.connection() as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ).fetchall()
        result = {}
        from psycopg import sql

        for row in tables:
            name = row["tablename"]
            records = connection.execute(
                sql.SQL("SELECT to_jsonb(t)::text AS value FROM {} t").format(sql.Identifier(name))
            ).fetchall()
            values = sorted(record["value"] for record in records)
            result[name] = {"rows": len(values), "sha256": hashlib.sha256("\n".join(values).encode()).hexdigest()}
        return result


def summarize(rows):
    summaries = {}
    for group in sorted({(r["kind"], r["variant"], r["path"]) for r in rows}):
        selected = [r for r in rows if (r["kind"], r["variant"], r["path"]) == group]
        summaries["/".join(group)] = {
            "n": len(selected),
            "all_required_at_3": sum(r["all_required_at_3"] for r in selected),
            "all_required_at_5": sum(r["all_required_at_5"] for r in selected),
            "mrr_at_5": statistics.mean(r["reciprocal_rank_at_5"] for r in selected),
            "median_total_ms": statistics.median(r["elapsed_ms"] for r in selected),
        }
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["per-query", "shared"], required=True)
    parser.add_argument("--port", type=int, default=55433)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("refusing to replace an existing diagnostic result")
    source = ROOT / "reports/customer-agent-live-v1/runtime-results.json"
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if hashlib.sha256(source.read_bytes()).hexdigest() != plan["source_sha256"]:
        raise SystemExit("saved live evidence changed")
    saved = json.loads(source.read_text(encoding="utf-8"))
    runs = {r["case"]: r for r in saved["runs"]}
    model_path = str(ROOT / "tmp/c071-probe/models/BAAI--bge-small-zh-v1.5")
    database = ReadOnlyDatabase(f"postgresql://agent:agent@127.0.0.1:{args.port}/agent_db")
    index = PolicyIndex(database)
    rows = []
    shared = embedder(model_path) if args.mode == "shared" else None
    try:
        before = snapshot(database)
        for case in plan["cases"]:
            run = runs[case["source_case"]]
            original = [
                c["request_json"]["arguments"]["query"]
                for c in run["calls"]
                if c["request_json"].get("name") == "search_policy"
            ]
            variants = {"original": original[0]} if case["kind"] == "saved-live" else {"probe": case["query"]}
            if "reference_query" in case:
                variants["human-reference"] = case["reference_query"]
            manifest = run["run"]["input_json"]["context"]["policy_manifest"]
            generations = run["run"]["generations_json"]
            for variant, query in variants.items():
                encoder = shared if shared is not None else embedder(model_path)
                for path in ["dense", "bm25"]:
                    started = time.perf_counter()
                    hits = index.search(
                        merchant_id=manifest["merchant_id"],
                        bundle_ids=manifest["bundle_ids"],
                        manifest_hash=manifest["manifest_hash"],
                        generation_ids=generations,
                        query=query,
                        path=path,
                        top_k=5,
                        embedder=encoder if path == "dense" else None,
                    )
                    elapsed = (time.perf_counter() - started) * 1000
                    ids = [h.rule_id for h in hits]
                    expected = set(case["required_rules"])
                    first = next((i for i, key in enumerate(ids, 1) if key in expected), None)
                    rows.append(
                        {
                            "id": case["id"],
                            "kind": case["kind"],
                            "variant": variant,
                            "path": path,
                            "query": query,
                            "manifest": manifest,
                            "generations": generations,
                            "required_rules": sorted(expected),
                            "rules": ids,
                            "scores": [h.score for h in hits],
                            "all_required_at_3": expected <= set(ids[:3]),
                            "all_required_at_5": expected <= set(ids),
                            "reciprocal_rank_at_5": 1 / first if first else 0,
                            "elapsed_ms": elapsed,
                        }
                    )
                    print(case["id"], variant, path, round(elapsed, 2), ids, flush=True)
        after = snapshot(database)
        if before != after:
            raise RuntimeError("retained database witness differs")
        report = {
            "mode": args.mode,
            "source_sha256": plan["source_sha256"],
            "plan_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
            "code_head": subprocess.check_output(  # noqa: S603 - resolved git, fixed read-only arguments
                [shutil.which("git") or "git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "synthetic_business_data": True,
            "not_holdout": True,
            "new_llm_calls": 0,
            "note": (
                "Human reference queries are diagnostic annotations, not Agent output. "
                "Timings are local observations, not an end-to-end SLA."
            ),
            "preservation": {"read_only_session": True, "before": before, "after": after, "equal": before == after},
            "summary": summarize(rows),
            "rows": rows,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    finally:
        database.close()


if __name__ == "__main__":
    main()
