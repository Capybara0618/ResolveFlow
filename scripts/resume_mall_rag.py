"""Business policy supplement: dense versus the external experiment's selected pipeline."""

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from scripts.agent_eval import metadata, persist
from scripts.evaluation.dataset import read
from scripts.evaluation.environment import environment
from scripts.evaluation.resume_retrieval import ExperimentalPolicyIndex
from scripts.resume_rag_benchmark import percentile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["A", "C", "D", "E"], required=True)
    parser.add_argument("--reranker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("immutable report")
    import torch
    from sentence_transformers import CrossEncoder

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    reranker = CrossEncoder(str(args.reranker), device="cpu", max_length=512)
    data = ROOT / "evals/calibrated-v3"
    queries, gold = read("rag/queries.json", data), read("gold/rag.json", data)
    report = metadata("local-retrieval", data)
    report.update(state="RUNNING", rows=[], timings=[], selected_external=args.variant)
    with environment(dataset=data) as (database, index, encoder, pins):
        indexes = {
            "B": index,
            args.variant: ExperimentalPolicyIndex(database, args.variant, reranker),
        }

        def retrieve(q, variant):
            return indexes[variant].search(
                **{
                    k: pins[q["bundle_id"]][k]
                    for k in ("merchant_id", "bundle_ids", "manifest_hash")
                },
                query=q["query"],
                path="dense",
                top_k=5,
                embedder=encoder,
            )

        for variant in indexes:
            for q in queries[:5]:
                retrieve(q, variant)
        for repetition in range(3):
            for variant in list(indexes)[:: (-1 if repetition % 2 else 1)]:
                for q in queries:
                    started = time.perf_counter()
                    hits = retrieve(q, variant)
                    report["timings"].append(
                        {
                            "id": q["id"],
                            "variant": variant,
                            "repeat": repetition,
                            "elapsed_ms": (time.perf_counter() - started) * 1000,
                        }
                    )
                    if repetition == 0:
                        required = set(gold[q["id"]]["must_rules"])
                        row = {
                            "id": q["id"],
                            "variant": variant,
                            "required": sorted(required),
                            "ranked": [h.rule_id for h in hits],
                        }
                        for k in (3, 5):
                            found = set(row["ranked"][:k]) & required
                            row[f"recall_at_{k}"] = (
                                len(found) / len(required) if required else None
                            )
                            row[f"complete_at_{k}"] = (
                                required <= found if required else None
                            )
                        report["rows"].append(row)
                persist(args.output, report)
                print(f"mall round={repetition + 1} variant={variant}", flush=True)
    summaries = {}
    for variant in indexes:
        rows = [r for r in report["rows"] if r["variant"] == variant and r["required"]]
        ms = [r["elapsed_ms"] for r in report["timings"] if r["variant"] == variant]
        summaries[variant] = {
            "positive_n": len(rows),
            "query_n": len(queries),
            "timing_n": len(ms),
            "mean_ms": statistics.mean(ms),
            "p95_ms": percentile(ms, 0.95),
            "recall_at_3": statistics.mean(r["recall_at_3"] for r in rows),
            "complete_at_3_n": sum(r["complete_at_3"] for r in rows),
            "complete_at_5_n": sum(r["complete_at_5"] for r in rows),
        }
    winner = max(
        summaries,
        key=lambda v: (
            summaries[v]["complete_at_3_n"],
            summaries[v]["recall_at_3"],
            -summaries[v]["mean_ms"],
        ),
    )
    report.update(state="COMPLETED", summaries=summaries, selected_business=winner)
    persist(args.output, report)
    print(summaries, "business winner", winner, flush=True)


if __name__ == "__main__":
    main()
