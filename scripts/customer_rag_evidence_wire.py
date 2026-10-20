"""Reuse the existing short-reference ledger on fixed evidence; never change selected spans or quality scores."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from resolveflow.harness.context import canonical_json  # noqa: E402
from resolveflow.harness.token_counting import load_tokenizer  # noqa: E402
from scripts.customer_rag_rerank import digest, verify  # noqa: E402
from scripts.evaluation.customer_evidence import _render  # noqa: E402
from scripts.policy_chunks import load_draft  # noqa: E402
from scripts.policy_context_packet_eval import catalog  # noqa: E402
from scripts.policy_documents import digest as text_digest  # noqa: E402
from scripts.policy_short_packet_eval import compact, resolve  # noqa: E402

MANIFEST = ROOT / "evals/customer-rag-v4/wire-manifest.json"
RESULT = ROOT / "reports/customer-rag-v4/results.json"
FILES = [
    "scripts/customer_rag_evidence_wire.py",
    "scripts/policy_short_packet_eval.py",
    "agent/src/resolveflow/harness/context.py",
    "reports/customer-rag-v4/results.json",
]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def freeze():
    if MANIFEST.exists():
        raise FileExistsError("wire manifest is immutable")
    parent = read(ROOT / "evals/customer-rag-v4/manifest.json")
    verify(parent)
    result = {
        "version": "fixed-evidence-short-wire-v1",
        "model": parent["model"],
        "inputs": {**parent["inputs"], **{p: digest(ROOT / p) for p in FILES}},
        "phase": "After assembly measurement; serialization only; no reselection or scoring changes.",
        "production_adoption": False,
        "new_model_calls": 0,
    }
    MANIFEST.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def evaluate(output):
    if output.exists():
        raise FileExistsError("wire result is immutable")
    manifest = read(MANIFEST)
    verify(manifest)
    original = read(RESULT)
    draft = load_draft(
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
        ROOT / "reports/policy-document-ingestion/draft-summary.json",
    )
    index = catalog(draft)
    for document in draft["documents"]:
        for block in document["blocks"]:
            index["blocks"][(document["source_id"], document["raw_sha256"], block["id"])].update(
                kind=block["kind"], rows=block.get("rows", [])
            )
    tokenizer = load_tokenizer()
    rows = []
    for row in original["rows"]:
        sources = list(dict.fromkeys((p["source_id"], p["raw_sha256"]) for p in row["pieces"]))
        rendered = _render(row["pieces"], index, sources)
        if text_digest(rendered["body"].encode()) != row["body_sha256"]:
            raise ValueError("reconstructed body differs from measured packet")
        source_refs = {source: f"s{i}" for i, source in enumerate(sources)}
        blocks = []
        for i, piece in enumerate(rendered["pieces"]):
            block = index["blocks"][(piece["source_id"], piece["raw_sha256"], piece["block_id"])]
            blocks.append(
                {
                    "ref": f"b{i}",
                    "source_ref": source_refs[(piece["source_id"], piece["raw_sha256"])],
                    **{k: v for k, v in piece.items() if k not in {"source_id", "raw_sha256"}},
                    "locator": block["locator"],
                }
            )
        # This context reconstructs selected evidence only; it is not a newly inferred complete policy.
        full = {
            "representation": "deduplicated",
            "reference_only": True,
            "sources": [{"ref": source_refs[key], **index["sources"][key]} for key in sources],
            "blocks": blocks,
            "contexts": [
                {
                    "id": "selected-spans:" + row["packet_sha256"],
                    "section_path": ["检索证据（不代表完整政策）"],
                    "block_refs": [b["ref"] for b in blocks],
                    "text_sha256": row["body_sha256"],
                }
            ],
        }
        packet, ledger = compact(full)
        ledger_sha = text_digest(canonical_json(ledger).encode())
        subject_set = {s["subject"] for s in full["sources"]}
        if len(subject_set) != 1:
            raise ValueError("mixed subjects")
        resolved = resolve(
            packet, ledger, "C0", ledger_sha256=ledger_sha, subject=next(iter(subject_set)), scope=set(sources)
        )
        if resolved["blocks"] != blocks or "\n\n".join(b["text"] for b in packet["blocks"]) != rendered["body"]:
            raise ValueError("short references lost evidence or provenance")
        rows.append(
            {
                "id": row["id"],
                "cohort": row["cohort"],
                "variant": row["variant"],
                "seed_k": row["seed_k"],
                "body_sha256": row["body_sha256"],
                "assembly_packet_sha256": row["packet_sha256"],
                "ledger_sha256": ledger_sha,
                "short_packet_sha256": text_digest(canonical_json(packet).encode()),
                "body_tokens": row["body_tokens"],
                "full_ledger_packet_tokens": len(tokenizer.encode(canonical_json(full)).ids),
                "short_packet_tokens": len(tokenizer.encode(canonical_json(packet)).ids),
                "reference_n": len(blocks) + 1,
                "roundtrip_equal": True,
            }
        )
    summaries = []
    for cohort in ["external-original", "external-probe"]:
        for k in [3, 5]:
            for variant in original["config"]["variants"]:
                selected = [r for r in rows if (r["cohort"], r["seed_k"], r["variant"]) == (cohort, k, variant)]
                summaries.append(
                    {
                        "cohort": cohort,
                        "seed_k": k,
                        "variant": variant,
                        "median_body_tokens": statistics.median(r["body_tokens"] for r in selected),
                        "median_full_ledger_packet_tokens": statistics.median(
                            r["full_ledger_packet_tokens"] for r in selected
                        ),
                        "median_short_packet_tokens": statistics.median(r["short_packet_tokens"] for r in selected),
                        "max_short_packet_tokens": max(r["short_packet_tokens"] for r in selected),
                    }
                )
    verify(manifest)
    result = {
        "version": manifest["version"],
        "manifest_sha256": digest(MANIFEST),
        "quality_selection_changed": False,
        "scope": "Serialization only after results observed; same source/span/text and quality, no new model call.",
        "all_roundtrips_equal": True,
        "summary": summaries,
        "rows": rows,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


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
