"""Coverage against model-assisted source judgments; never official human recall."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.policy_documents import digest


def score(judgments: dict, cache: dict) -> dict:
    labels = {r["id"]: r for r in judgments["results"]}
    rows = []
    for packet in cache["results"]:
        label = labels[packet["query_id"]]
        judgment = label.get("judgment")
        full = packet["ledger"]["full_packet"]
        sources = {s["ref"]: s["source_id"] for s in full["sources"]}
        retrieved = {(sources[b["source_ref"]], b["block_id"]) for b in full["blocks"]}
        required = {(r["source_id"], r["block_id"]) for r in judgment["required"]} if judgment else set()
        covered = len(required & retrieved)
        rows.append({
            "query_id": packet["query_id"], "method": packet["method"], "k": packet["k"],
            "label_status": label["status"], "answerability": judgment["answerability"] if judgment else None,
            "uncertain": judgment.get("uncertain") if judgment else None,
            "required_blocks": len(required), "covered_blocks": covered,
            "all_required_covered": (covered == len(required)) if required else None,
            "missing": [{"source_id": s, "block_id": b} for s, b in sorted(required - retrieved)],
            "retrieved_blocks": len(retrieved), "selection_sha256": packet["selection_sha256"],
        })
    summaries = []
    for method in ("dense", "bm25"):
        for k in (2, 5):
            selected = [r for r in rows if r["method"] == method and r["k"] == k]
            evidence = [r for r in selected if r["required_blocks"]]
            summaries.append({
                "method": method, "k": k, "all_queries": len(selected),
                "validated_model_labels": sum(r["label_status"] == "VALIDATED_MODEL_JUDGMENT" for r in selected),
                "unassessed_protocol_errors": sum(r["label_status"] == "ERROR" for r in selected),
                "model_evidence_denominator": len(evidence),
                "all_required_covered": sum(r["all_required_covered"] for r in evidence),
                "covered_blocks": sum(r["covered_blocks"] for r in evidence),
                "required_blocks": sum(r["required_blocks"] for r in evidence),
            })
    return {
        "origin": "LLM_ASSISTED_NOT_HUMAN_GOLD", "official_human_recall": None, "human_review_count": 0,
        "new_chat_api_calls": 0,
        "answerability_counts": dict(Counter(r["judgment"]["answerability"] for r in labels.values() if r["judgment"])),
        "summaries": summaries, "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("scores are immutable")
    report = score(
        json.loads(args.judgments.read_text(encoding="utf-8")), json.loads(args.cache.read_text(encoding="utf-8"))
    )
    report.update(
        judgments_sha256=digest(args.judgments.read_bytes()), cache_sha256=digest(args.cache.read_bytes()),
        runner_sha256=digest(Path(__file__).read_bytes()),
    )
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["summaries"]))


if __name__ == "__main__":
    main()
