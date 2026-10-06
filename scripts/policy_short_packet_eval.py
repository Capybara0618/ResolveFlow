"""Short model references with an externally trusted, complete source ledger."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.harness.context import canonical_json  # noqa: E402
from resolveflow.harness.token_counting import load_tokenizer  # noqa: E402
from scripts.policy_context_packet_eval import audit_pair, measure  # noqa: E402
from scripts.policy_documents import digest  # noqa: E402


def compact(full: dict) -> tuple[dict, dict]:
    """Keep the selected text and section relationships; move proof metadata off prompt."""
    if full["representation"] != "deduplicated" or not full["reference_only"]:
        raise ValueError("requires an external reference-only deduplicated packet")
    sources = [{"ref": s["ref"], "subject": s["subject"], "name": s["source_id"]} for s in full["sources"]]
    blocks = [{"ref": b["ref"], "source_ref": b["source_ref"], "text": b["text"]} for b in full["blocks"]]
    contexts = [
        {"ref": f"C{i}", "section_path": c["section_path"], "block_refs": c["block_refs"]}
        for i, c in enumerate(full["contexts"])
    ]
    packet = {
        "version": "short-source-packet-v1",
        "reference_only": True,
        "sources": sources,
        "blocks": blocks,
        "contexts": contexts,
    }
    ledger = {
        "version": "source-ledger-v1",
        "full_packet": copy.deepcopy(full),
        "packet_sha256": digest(canonical_json(packet).encode()),
    }
    return copy.deepcopy(packet), ledger


def resolve(packet: dict, ledger: dict, reference: str, *, ledger_sha256: str, subject: str, scope: set) -> dict:
    """The caller supplies its trusted ledger digest and source scope, never the model."""
    if digest(canonical_json(ledger).encode()) != ledger_sha256:
        raise ValueError("trusted ledger fingerprint differs")
    full = ledger["full_packet"]
    expected, _ = compact(full)
    if packet != expected or digest(canonical_json(packet).encode()) != ledger["packet_sha256"]:
        raise ValueError("model packet differs from trusted source ledger")
    sources = {s["ref"]: s for s in full["sources"]}
    blocks = {b["ref"]: b for b in full["blocks"]}
    if len(sources) != len(full["sources"]) or len(blocks) != len(full["blocks"]):
        raise ValueError("ambiguous ledger identities")
    # Validate every block, including those the requested reference does not name.
    for b in blocks.values():
        s = sources[b["source_ref"]]
        if s["subject"] != subject or (s["source_id"], s["raw_sha256"]) not in scope:
            raise ValueError("reference escaped subject or snapshot scope")
        if digest(b["text"].encode()) != b["text_sha256"]:
            raise ValueError("source block content hash differs")
    if reference in blocks:
        ids = [reference]
        context_id = None
    else:
        matches = [i for i, c in enumerate(packet["contexts"]) if c["ref"] == reference]
        if len(matches) != 1:
            raise ValueError("unknown or wrong-kind short reference")
        context = full["contexts"][matches[0]]
        ids, context_id = context["block_refs"], context["id"]
        text = "\n\n".join(blocks[ref]["text"] for ref in ids)
        if digest(text.encode()) != context["text_sha256"]:
            raise ValueError("complete context reconstruction differs")
    return {
        "context_id": context_id,
        "blocks": [copy.deepcopy(blocks[ref]) for ref in ids],
        "sources": [copy.deepcopy(sources[key]) for key in dict.fromkeys(blocks[ref]["source_ref"] for ref in ids)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.cache_output.exists():
        raise FileExistsError("frozen outputs cannot be overwritten")
    if not args.cache_output.resolve().is_relative_to((ROOT / "tmp").resolve()):
        raise ValueError("full source ledger stays in ignored tmp")
    path = ROOT / "tmp/policy-documents-v1/context-packets-v1.json"
    prior = json.loads(
        (ROOT / "reports/policy-document-ingestion/context-packet-experiment.json").read_text(encoding="utf-8")
    )
    if digest(path.read_bytes()) != prior["cache_sha256"]:
        raise ValueError("frozen complete packet cache differs")
    cache = json.loads(path.read_text(encoding="utf-8"))
    tokenizer = load_tokenizer()
    rows, private = [], []
    for row in cache["results"]:
        full = row["packets"]["deduplicated"]
        audit_pair(row["packets"]["repeated"], full)
        packet, ledger = compact(full)
        sha = digest(canonical_json(ledger).encode())
        subjects = {s["subject"] for s in full["sources"]}
        if len(subjects) != 1:
            raise ValueError("source packet must have one scoped subject")
        subject = next(iter(subjects))
        scope = {(s["source_id"], s["raw_sha256"]) for s in full["sources"]}
        for ref in [b["ref"] for b in packet["blocks"]] + [c["ref"] for c in packet["contexts"]]:
            resolve(packet, ledger, ref, ledger_sha256=sha, subject=subject, scope=scope)
        # measure() accepts the same text-field grouping; no packet is admitted anew.
        counts = measure({**packet, "representation": "deduplicated"}, tokenizer, [2048, 4096, 8192])
        # Count the actual transmitted packet, without the diagnostic representation field.
        wire = canonical_json(packet)
        counts["packet_tokens"] = len(tokenizer.encode(wire, add_special_tokens=False).ids)
        counts["packet_sha256"] = digest(wire.encode())
        counts["packet_chars"] = len(wire)
        counts["wrapper_delta_tokens"] = counts["packet_tokens"] - counts["content_tokens"]
        counts["probe_complete"] = {str(n): counts["packet_tokens"] <= n for n in (2048, 4096, 8192)}
        metadata = {k: row[k] for k in ("query_id", "method", "k", "selection_sha256", "context_ids", "source_blocks")}
        rows.append({**metadata, "short": counts, "ledger_sha256": sha})
        private.append({**metadata, "packet": packet, "ledger": ledger, "ledger_sha256": sha})
    output = {
        "version": "policy-short-packet-v1",
        "full_report_sha256": digest(
            (ROOT / "reports/policy-document-ingestion/context-packet-experiment.json").read_bytes()
        ),
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "same_selected_information_set": True,
        "roundtrip_validated_prefixes": len(rows),
        "independent_human_review_count": 0,
        "new_chat_api_calls": 0,
        "production_adoption": False,
        "results": rows,
    }
    for destination, value in ((args.cache_output, {**output, "results": private}), (args.output, output)):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination == args.output:
            value["cache_sha256"] = digest(args.cache_output.read_bytes())
        with destination.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
    print(json.dumps({"validated_prefixes": len(rows)}))


if __name__ == "__main__":
    main()
