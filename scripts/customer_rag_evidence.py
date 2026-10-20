"""Frozen evidence assembly using original RRF and saved GPU rankings; no models or business writes."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from resolveflow.harness.token_counting import load_tokenizer  # noqa: E402
from resolveflow.policies.retrieval import bm25_scores  # noqa: E402
from scripts.customer_rag_rerank import digest, external_tasks, verify  # noqa: E402
from scripts.evaluation.customer_evidence import assemble  # noqa: E402
from scripts.policy_chunks import load_draft  # noqa: E402
from scripts.policy_codex_review import sufficiently_covered  # noqa: E402
from scripts.policy_context_packet_eval import catalog  # noqa: E402
from scripts.policy_query_eval import coverage, rank  # noqa: E402

MANIFEST = ROOT / "evals/customer-rag-v4/manifest.json"
OLD_MANIFEST = ROOT / "evals/customer-rag-v3/manifest-gpu-stdio.json"
RESULT = ROOT / "reports/customer-rag-v3/gpu-results.json"
CONFIG = {
    "variants": ["rrf-direct", "ce-direct", "rrf-parent", "ce-parent", "dual-parent"],
    "seed_k": [3, 5],
    "max_body_chars": 8000,
    "max_body_tokens": 4096,
    "timing_rounds": 2,
    "parent_binding": "EXISTING_SOURCE_CONTEXT_NOT_INFERRED_FROM_GOLD",
    "dual_order": "RRF_K_THEN_NON_DUPLICATE_CE_K",
    "production_adoption": False,
    "diagnostic_windows": [5, 10, 20],
    "new_model_calls": 0,
}
FILES = [
    "scripts/customer_rag_evidence.py",
    "scripts/evaluation/customer_evidence.py",
    "agent/tests/unit/test_customer_evidence.py",
    "docs/customer-rag-evidence-v1.md",
    "scripts/policy_context_packet_eval.py",
    "scripts/policy_representation_eval.py",
    "scripts/customer_rag_diagnostic.py",
    "scripts/policy_documents.py",
    "agent/src/resolveflow/harness/token_counting.py",
    "agent/src/resolveflow/assets/deepseek-v41/tokenizer.json.gz",
]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def freeze():
    if MANIFEST.exists():
        raise FileExistsError("freeze is immutable")
    old = read(OLD_MANIFEST)
    verify(old)
    inputs = dict(old["inputs"])
    inputs.update({p: digest(ROOT / p) for p in FILES})
    inputs.update(
        {
            str(p.relative_to(ROOT)).replace("\\", "/"): digest(p)
            for p in [OLD_MANIFEST, RESULT]
        }
    )
    payload = {
        "version": "customer-evidence-anchor-parent-v1",
        "config": CONFIG,
        "inputs": inputs,
        "model": old["model"],
        "not_holdout": True,
        "decision": "Run unchanged cases before interpreting results; no production promotion in this experiment.",
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def packet_chunks(packet):
    return [
        {"source_id": p["source_id"], "raw_sha256": p["raw_sha256"], "fragments": [p]}
        for p in packet["pieces"]
    ]


def packet_covered(task, packet):
    chunks = packet_chunks(packet)
    return sufficiently_covered(task["sets"], lambda atom: coverage(chunks, atom))


def assert_anchors(packet, hits):
    chunks = packet_chunks(packet)
    for child in hits:
        if child["id"] not in packet["admitted_child_ids"]:
            continue
        for fragment in child["fragments"]:
            atom = {
                **fragment,
                "source_id": child["source_id"],
                "raw_sha256": child["raw_sha256"],
                "table_row": fragment.get("table_row"),
            }
            if not coverage(chunks, atom):
                raise ValueError("assembly lost an admitted anchor span")


def summary(rows):
    result = []
    for cohort in ["external-original", "external-probe"]:
        for k in CONFIG["seed_k"]:
            for variant in CONFIG["variants"]:
                selected = [
                    r
                    for r in rows
                    if (r["cohort"], r["seed_k"], r["variant"]) == (cohort, k, variant)
                ]
                full = [r for r in selected if r["answerability"] == "ANSWERABLE"]
                base = {
                    r["id"]: r
                    for r in rows
                    if r["cohort"] == cohort
                    and r["seed_k"] == k
                    and r["variant"] == "rrf-direct"
                }
                result.append(
                    {
                        "cohort": cohort,
                        "seed_k": k,
                        "variant": variant,
                        "query_n": len(selected),
                        "answerable_n": len(full),
                        "packet_complete_n": sum(r["packet_complete"] for r in full),
                        "improved_vs_rrf": [
                            r["id"]
                            for r in full
                            if r["packet_complete"]
                            and not base[r["id"]]["packet_complete"]
                        ],
                        "regressed_vs_rrf": [
                            r["id"]
                            for r in full
                            if not r["packet_complete"]
                            and base[r["id"]]["packet_complete"]
                        ],
                        "median_body_tokens": statistics.median(
                            r["body_tokens"] for r in selected
                        ),
                        "median_serialized_tokens": statistics.median(
                            r["serialized_tokens"] for r in selected
                        ),
                        "median_assembly_ms": statistics.median(
                            r["elapsed_ms"] for r in selected
                        ),
                        "blocked_parent_query_n": sum(
                            bool(r["blocked_context_ids"]) for r in selected
                        ),
                        "blocked_child_query_n": sum(
                            bool(r["blocked_child_ids"]) for r in selected
                        ),
                    }
                )
    return result


def diagnose(tasks, bundle):
    """Scoring-only attribution: full-route ranks are never sent to the assembler."""
    cache = read(ROOT / "tmp/rag-structure-v1/vectors-v1.json")
    by_id = {
        q["id"]: (q, v) for q, v in zip(cache["queries"], cache["vectors"], strict=True)
    }
    output = []
    for task in tasks:
        if task["cohort"] != "external-probe" or task["id"] not in {"P03", "P06"}:
            continue
        case, vector = by_id[task["id"]]
        dense, body = rank(case, bundle, "dense", vector), rank(case, bundle, "bm25")
        chunks = [c for c, _ in dense]
        title_scores = bm25_scores(
            [" > ".join(c["section_path"]) for c in chunks], task["query"]
        )
        titles = sorted(
            zip(chunks, title_scores, strict=True), key=lambda p: (-p[1], p[0]["id"])
        )
        routes = {
            "dense": dense,
            "body_bm25": [(c, s) for c, s in body if s > 0],
            "title_bm25": [(c, s) for c, s in titles if s > 0],
        }
        windows = []
        for k in CONFIG["diagnostic_windows"]:
            candidates = {c["id"]: c for route in routes.values() for c, _ in route[:k]}
            windows.append(
                {
                    "per_route_k": k,
                    "union_n": len(candidates),
                    "complete": sufficiently_covered(
                        task["sets"], lambda a, candidates=candidates: coverage(list(candidates.values()), a)
                    ),
                }
            )
        atoms = []
        for atom in task["sets"][0]:
            atom_ranks = {}
            for name, route in routes.items():
                first = next(
                    (
                        i
                        for i in range(1, len(route) + 1)
                        if coverage([c for c, _ in route[:i]], atom)
                    ),
                    None,
                )
                atom_ranks[name] = first
            atoms.append(
                {
                    "source_id": atom["source_id"],
                    "block_id": atom["block_id"],
                    "table_row": atom["table_row"],
                    "text_range": atom["text_range"],
                    "first_complete_route_prefix": atom_ranks,
                }
            )
        output.append(
            {
                "id": task["id"],
                "query": task["query"],
                "windows": windows,
                "atoms": atoms,
            }
        )
    return output


def evaluate(output):
    if output.exists():
        raise FileExistsError("experiment output is immutable")
    manifest = read(MANIFEST)
    if manifest["config"] != CONFIG:
        raise ValueError("config differs from freeze")
    verify(manifest)
    previous = read(RESULT)
    if previous["manifest_sha256"] != digest(OLD_MANIFEST):
        raise ValueError("saved GPU result binding differs")
    bundle = read(ROOT / "tmp/policy-documents-v1/children-final.json")
    draft = load_draft(
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
        ROOT / "reports/policy-document-ingestion/draft-summary.json",
    )
    index = catalog(draft)
    for document in draft["documents"]:
        for block in document["blocks"]:
            index["blocks"][
                (document["source_id"], document["raw_sha256"], block["id"])
            ].update(kind=block["kind"], rows=block.get("rows", []))
    tokenizer = load_tokenizer()
    tasks = list(external_tasks())
    ranking = {(r["cohort"], r["id"], r["variant"]): r for r in previous["rows"]}
    rows = []
    for task in tasks:
        seeds = {}
        for name, variant in [("rrf", "fields-rrf"), ("ce", "union-ce")]:
            row = ranking[(task["cohort"], task["id"], variant)]
            if row["query"] != task["query"]:
                raise ValueError("saved query differs")
            seeds[name] = [task["by_id"][h["chunk_id"]] for h in row["ranking"]]
        case = {
            "subject": next(iter(task["by_id"].values()))["subject"],
            "scope": [
                {"source_id": c["source_id"], "raw_sha256": c["raw_sha256"]}
                for c in task["by_id"].values()
            ],
        }
        for k in CONFIG["seed_k"]:
            for variant in CONFIG["variants"]:
                hits = seeds["rrf" if variant.startswith("rrf") else "ce"][:k]
                if variant == "dual-parent":
                    hits = list(
                        {
                            c["id"]: c for c in seeds["rrf"][:k] + seeds["ce"][:k]
                        }.values()
                    )
                rounds, first = [], None
                for _ in range(CONFIG["timing_rounds"]):
                    started = time.perf_counter()
                    packet = assemble(
                        case,
                        hits,
                        bundle,
                        index,
                        tokenizer,
                        expand=variant.endswith("parent"),
                        max_chars=CONFIG["max_body_chars"],
                        max_tokens=CONFIG["max_body_tokens"],
                    )
                    rounds.append((time.perf_counter() - started) * 1000)
                    if first is not None and packet != first:
                        raise ValueError("repeated assembly differs")
                    first = packet
                assert_anchors(packet, hits)
                complete = packet_covered(task, packet)
                if variant.endswith("direct") and not packet["blocked_child_ids"]:
                    old = ranking[
                        (
                            task["cohort"],
                            task["id"],
                            "fields-rrf" if variant == "rrf-direct" else "union-ce",
                        )
                    ]
                    if complete != old[f"complete_at_{k}"]:
                        raise ValueError("direct evidence differs from original score")
                rows.append(
                    {
                        "id": task["id"],
                        "cohort": task["cohort"],
                        "query": task["query"],
                        "answerability": task["answerability"],
                        "variant": variant,
                        "seed_k": k,
                        "input_child_n": len(hits),
                        "packet_complete": complete,
                        **{
                            key: value
                            for key, value in packet.items()
                            if key not in {"body", "pieces"}
                        },
                        "pieces": [
                            {key: value for key, value in p.items() if key != "text"}
                            for p in packet["pieces"]
                        ],
                        "elapsed_ms": statistics.median(rounds),
                        "timing_rounds_ms": rounds,
                    }
                )
        print(task["cohort"], task["id"], flush=True)
    verify(manifest)
    result = {
        "version": manifest["version"],
        "manifest_sha256": digest(MANIFEST),
        "not_holdout": True,
        "new_model_calls": 0,
        "production_writes": 0,
        "config": CONFIG,
        "latency_scope": "Assembly and local tokenizer only; excludes retrieval/GPU rerank/answer.",
        "summary": summary(rows),
        "diagnostics": diagnose(tasks, bundle),
        "rows": rows,
        "mall_existing_complete_rules": [
            {
                key: row[key]
                for key in ["id", "cohort", "variant", "complete_at_3", "complete_at_5"]
            }
            for row in previous["rows"]
            if row["cohort"].startswith("mall")
            and row["variant"] in {"fields-rrf", "union-ce"}
        ],
        "mall_note": "Saved GPU results only; no new mall assembly or inference performed.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.output:
        evaluate(args.output)
    else:
        parser.error("choose --freeze or --output")
