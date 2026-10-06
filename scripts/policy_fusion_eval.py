"""Second generic comparison: keep complete authority evidence and deduplicate exact source blocks."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.harness.token_counting import load_tokenizer  # noqa: E402
from scripts.policy_chunks import load_draft, representations  # noqa: E402
from scripts.policy_codex_review import resolve_atom, sufficiently_covered, validate_labels  # noqa: E402
from scripts.policy_context_packet_eval import catalog, select_contexts  # noqa: E402
from scripts.policy_documents import digest  # noqa: E402
from scripts.policy_query_eval import coverage, load_inputs, rank  # noqa: E402
from scripts.policy_structure_candidates import rrf  # noqa: E402
from scripts.policy_structure_eval import inherited_probes, metrics, read, verify_freeze  # noqa: E402


def union_packet(selection, index: dict) -> dict:
    """Same admitted complete evidence set; no new admission, text rewrite or semantic filtering."""
    keys = list(selection.block_keys)
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate source block identity")
    for key in keys:
        block = index["blocks"][key]
        if digest(block["text"].encode()) != block["text_sha256"]:
            raise ValueError("union source original text/hash differs")
    text = "\n\n".join(index["blocks"][key]["text"] for key in keys)
    return {
        "block_keys": keys,
        "text": text,
        "text_sha256": digest(text.encode()),
        "exported_chars": len(text),
        "same_admitted_evidence_set": True,
        "complete_policy_guaranteed": False,
    }


def evaluate(manifest: dict, vectors: dict) -> dict:
    verify_freeze(manifest)
    _, cases, _, body = load_inputs(
        ROOT / "evals/policy-query-v1",
        ROOT / "tmp/policy-documents-v1/children-final.json",
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
    )
    draft = load_draft(
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
        ROOT / "reports/policy-document-ingestion/draft-summary.json",
    )
    index = catalog(draft)
    index["representations"] = {
        (d["source_id"], d["raw_sha256"], b["id"]): representations(b) for d in draft["documents"] for b in d["blocks"]
    }
    labels = validate_labels(read(ROOT / "evals/rag-codex-review-v1/labels.json"), cases, index)
    cases += inherited_probes(cases, read(ROOT / "evals/rag-structure-v1/probes.json"))
    if vectors["queries"] != [{k: q[k] for k in ("id", "query", "subject", "scope")} for q in cases]:
        raise ValueError("fixed query vector inputs differ")
    path = read(ROOT / "tmp/policy-documents-v1/representation-v1.json")["variants"]["title_path"]
    tokenizer, rows = load_tokenizer(), []
    for case, vector in zip(cases, vectors["vectors"], strict=True):
        label = labels[case.get("based_on", case["id"])]
        sets = [[resolve_atom(ref, case, index) for ref in group] for group in label["evidence_sets"]]
        started = time.perf_counter()
        dense, lexical = rank(case, body, "dense", vector), rank(case, body, "bm25")
        ranked_path = rank(case, path, "dense", vector)
        rankings = {
            "body-dense-union": (dense, body),
            "path-dense-union": (ranked_path, path),
            "body-rrf-union": (rrf(dense, lexical, 20, 60), body),
            "path-rrf-union": (rrf(ranked_path, lexical, 20, 60), path),
        }
        ms = (time.perf_counter() - started) * 1000
        for name in manifest["config"]["variants"]:
            ranked, bundle = rankings[name]
            for k in (2, 5):
                hits = [c for c, _ in ranked[:k]]
                selected = select_contexts(case, hits, bundle, index, 8000)
                original = "\n\n".join(bundle["contexts"][cid]["text"] for cid in selected.context_ids)
                packet = union_packet(selected, index)
                keys = set(packet["block_keys"])
                direct = sufficiently_covered(sets, lambda a, hits=hits: coverage(hits, a))
                full = sufficiently_covered(
                    sets, lambda a, keys=keys: (a["source_id"], a["raw_sha256"], a["block_id"]) in keys
                )
                rows.append(
                    {
                        "query_id": case["id"],
                        "variant": name,
                        "k": k,
                        "cohort": "probe" if "based_on" in case else "original",
                        "answerability": label["answerability"],
                        "raw_child_direct": direct,
                        "admitted_group_direct": direct,
                        "authority_expanded": full,
                        "local_packet_covered": full,
                        "authority_chars": selected.exported_chars,
                        "authority_tokens": len(tokenizer.encode(original).ids),
                        "local_chars": packet["exported_chars"],
                        "local_tokens": len(tokenizer.encode(packet["text"]).ids),
                        "local_same_admitted_evidence_set": True,
                        "authority_selection_sha256": selected.fingerprint,
                        "union_text_sha256": packet["text_sha256"],
                        "union_refs": [
                            {"source_id": key[0], "raw_sha256": key[1], "block_id": key[2]} for key in sorted(keys)
                        ],
                        "authority_blocked": list(selected.blocked_ids),
                        "ranking_ms": round(ms, 4),
                        "hits": [{"id": c["id"], "score": s, "source_id": c["source_id"]} for c, s in ranked[:k]],
                    }
                )
    verify_freeze(manifest)
    return {
        "version": "rag-source-union-fusion-v1",
        "origin": "CODEX_REVIEW",
        "blind_review": False,
        "new_chat_api_calls": 0,
        "production_writes": 0,
        "new_embedding_calls": 0,
        "config": manifest["config"],
        "inputs": manifest["inputs"],
        "summaries": metrics(rows),
        "results": rows,
        "union_note": "local_* metric names reused for exact source union here; not adjacent local windows",
        "latency_scope": "all three ranking paths plus both RRFs together; excludes embedding/serialization/DB",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "evals/rag-structure-v1/fusion-manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("fusion result is immutable")
    manifest = read(args.manifest)
    report = evaluate(manifest, read(ROOT / "tmp/rag-structure-v1/vectors-v1.json"))
    report.update(runner_sha256=digest(Path(__file__).read_bytes()), manifest_sha256=digest(args.manifest.read_bytes()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["summaries"]))


if __name__ == "__main__":
    main()
