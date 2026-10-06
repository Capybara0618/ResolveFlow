"""Offline fixed-selection citation serialization; no extra admission or production adoption."""

from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.harness.context import canonical_json  # noqa: E402
from resolveflow.harness.token_counting import GZIP_SHA256, RAW_SHA256, load_tokenizer  # noqa: E402
from scripts.policy_chunks import complete_context  # noqa: E402
from scripts.policy_documents import digest  # noqa: E402
from scripts.policy_query_eval import load_inputs, score_row  # noqa: E402
from scripts.policy_representation_eval import build_block_index  # noqa: E402

FROZEN_FILES = (
    "evals/policy-query-v1/manifest.json",
    "reports/policy-document-ingestion/query-baseline.json",
    "scripts/policy_context_packet_eval.py",
    "agent/tests/unit/test_policy_context_packet_eval.py",
    "scripts/policy_query_eval.py",
    "scripts/policy_representation_eval.py",
    "scripts/policy_chunks.py",
    "scripts/policy_drafts.py",
    "scripts/policy_documents.py",
    "agent/src/resolveflow/policies/retrieval.py",
    "agent/src/resolveflow/harness/context.py",
    "agent/src/resolveflow/harness/token_counting.py",
    "agent/src/resolveflow/assets/deepseek-v41/tokenizer.json.gz",
)
CONFIG = {
    "version": "policy-context-packet-v1",
    "representation": "body",
    "selection": "FROZEN_WHOLE_CONTEXT_BASELINE",
    "context_chars": 8000,
    "serialization": ["repeated", "deduplicated"],
    "methods": ["dense", "bm25"],
    "k": [2, 5],
    "packet_token_probes": [2048, 4096, 8192],
    "probe_kind": "OFFLINE_EVIDENCE_PACKET_ONLY_NOT_SPEND_LIMIT",
    "production_adoption": False,
    "frozen_before_measurement": True,
}


def positive_limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("limit must be a positive integer")


def catalog(draft: dict) -> dict:
    blocks = build_block_index(draft)
    sources = {}
    for doc in draft["documents"]:
        source = (doc["source_id"], doc["raw_sha256"])
        if source in sources:
            raise ValueError("duplicate source snapshot")
        sources[source] = {name: doc[name] for name in ("source_id", "raw_sha256", "subject", "source_url")}
        for block in doc["blocks"]:
            blocks[(*source, block["id"])].update(
                text_sha256=block["text_sha256"],
                raw_fragment_sha256=block["raw_fragment_sha256"],
                locator=copy.deepcopy(block["locator"]),
            )
    return {"sources": sources, "blocks": blocks}


def context_refs(context_id: str, bundle: dict, index: dict) -> tuple:
    context = bundle["contexts"][context_id]
    source = (context["source_id"], context["raw_sha256"])
    if source not in index["sources"] or index["sources"][source]["subject"] != context["subject"]:
        raise ValueError("context source/subject differs")
    refs = tuple((*source, block_id) for block_id in context["required_block_ids"])
    if not refs or len(set(refs)) != len(refs) or any(key not in index["blocks"] for key in refs):
        raise ValueError("invalid complete context source references")
    for key in refs:
        block = index["blocks"][key]
        if block["subject"] != context["subject"] or digest(block["text"].encode()) != block["text_sha256"]:
            raise ValueError("source block hash/subject differs")
    text = "\n\n".join(index["blocks"][key]["text"] for key in refs)
    if text != context["text"] or digest(text.encode()) != context["text_sha256"]:
        raise ValueError("context does not contain its complete source blocks")
    return refs


def ordered_keys(context_ids: tuple, bundle: dict, index: dict) -> tuple:
    keys = list(dict.fromkeys(key for cid in context_ids for key in context_refs(cid, bundle, index)))
    sources = list(dict.fromkeys(key[:2] for key in keys))
    return tuple(sorted(keys, key=lambda key: (sources.index(key[:2]), index["blocks"][key]["ordinal"])))


@dataclass(frozen=True)
class Selection:
    context_ids: tuple
    block_keys: tuple
    blocked_ids: tuple
    exported_chars: int
    fingerprint: str


def seal(selection: Selection, bundle: dict, index: dict) -> str:
    if len(set(selection.context_ids)) != len(selection.context_ids):
        raise ValueError("duplicate selection contexts")
    keys = ordered_keys(selection.context_ids, bundle, index)
    chars = len("\n\n".join(bundle["contexts"][cid]["text"] for cid in selection.context_ids))
    if keys != selection.block_keys or chars != selection.exported_chars:
        raise ValueError("selection block set/size differs")
    payload = {
        "contexts": [(cid, bundle["contexts"][cid]) for cid in selection.context_ids],
        "blocks": [(key, index["blocks"][key]) for key in keys],
        "sources": [(key, index["sources"][key]) for key in dict.fromkeys(k[:2] for k in keys)],
        "blocked_ids": selection.blocked_ids,
    }
    return digest(canonical_json(payload).encode())


def select_contexts(case: dict, hits: list, bundle: dict, index: dict, max_chars: int) -> Selection:
    """Match baseline admission before serialization; never inspect query text or labels."""
    positive_limit(max_chars)
    chunks = {chunk["id"]: chunk for chunk in bundle["chunks"]}
    if len(chunks) != len(bundle["chunks"]) or len({c["id"] for c in hits}) != len(hits):
        raise ValueError("duplicate child identity")
    scope = {(s["source_id"], s["raw_sha256"]) for s in case["scope"]}
    seen, payloads, accepted, blocked, used = set(), {}, [], [], 0
    for chunk in hits:
        if (
            chunk["id"] not in chunks
            or chunks[chunk["id"]] != chunk
            or chunk["subject"] != case["subject"]
            or (chunk["source_id"], chunk["raw_sha256"]) not in scope
        ):
            raise ValueError("unknown or out-of-scope child binding")
        cid = chunk["context_id"]
        full = complete_context(bundle, chunk["id"], max_chars)
        refs = context_refs(cid, bundle, index)
        if cid in seen:
            continue
        seen.add(cid)
        payload_key = (chunk["source_id"], chunk["raw_sha256"], full["text_sha256"])
        if payload_key in payloads:
            if payloads[payload_key] != refs:
                raise ValueError("ambiguous same-text context provenance")
            continue
        payloads[payload_key] = refs
        needed = full["chars"] + (2 if used else 0)
        if not full["complete"] or needed > max_chars - used:
            blocked.append(cid)
            continue
        accepted.append(cid)
        used += needed
    selected = Selection(tuple(accepted), ordered_keys(tuple(accepted), bundle, index), tuple(blocked), used, "")
    return Selection(
        selected.context_ids, selected.block_keys, selected.blocked_ids, used, seal(selected, bundle, index)
    )


def make_packet(selection: Selection, bundle: dict, index: dict, representation: str) -> dict:
    if representation not in CONFIG["serialization"]:
        raise ValueError("unknown packet representation")
    if seal(selection, bundle, index) != selection.fingerprint:
        raise ValueError("selection/source seal differs")
    source_keys = list(dict.fromkeys(key[:2] for key in selection.block_keys))
    source_refs = {key: f"s{i}" for i, key in enumerate(source_keys)}
    block_refs = {key: f"b{i}" for i, key in enumerate(selection.block_keys)}
    sources = [{"ref": source_refs[key], **index["sources"][key]} for key in source_keys]
    blocks = []
    for key in selection.block_keys:
        block = index["blocks"][key]
        value = {
            "ref": block_refs[key],
            "source_ref": source_refs[key[:2]],
            "block_id": key[2],
            **{name: block[name] for name in ("text_sha256", "raw_fragment_sha256", "locator")},
        }
        if representation == "deduplicated":
            value["text"] = block["text"]
        blocks.append(value)
    contexts = []
    for cid in selection.context_ids:
        context = bundle["contexts"][cid]
        value = {
            "id": cid,
            "block_refs": [block_refs[k] for k in context_refs(cid, bundle, index)],
            "text_sha256": context["text_sha256"],
            "section_path": context["section_path"],
        }
        if representation == "repeated":
            value["text"] = context["text"]
        contexts.append(value)
    return {
        "version": "experimental-citation-packet-v1",
        "reference_only": True,
        "representation": representation,
        "sources": copy.deepcopy(sources),
        "blocks": copy.deepcopy(blocks),
        "contexts": copy.deepcopy(contexts),
    }


def count_text(text: str, tokenizer) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False).ids)


def export_packet(packet: dict, max_tokens: int, tokenizer) -> dict:
    """Probe complete serialized packet length; refusal delivers no partial policy."""
    positive_limit(max_tokens)
    wire = canonical_json(packet)
    tokens = count_text(wire, tokenizer)
    fits = tokens <= max_tokens
    return {
        "complete": fits,
        "status": "REFERENCE_ONLY" if fits else "PACKET_TOO_LARGE",
        "packet": copy.deepcopy(packet) if fits else None,
        "tokens": tokens,
        "packet_sha256": digest(wire.encode()),
        "limit_kind": CONFIG["probe_kind"],
    }


def audit_pair(repeated: dict, dedup: dict) -> None:
    """Reconstruct contexts from transmitted blocks, separately from source assembly."""
    if repeated["sources"] != dedup["sources"]:
        raise ValueError("packet source lineage changed")
    if repeated["blocks"] != [{k: v for k, v in block.items() if k != "text"} for block in dedup["blocks"]]:
        raise ValueError("packet block lineage changed")
    blocks = {block["ref"]: block for block in dedup["blocks"]}
    if len(blocks) != len(dedup["blocks"]) or len(repeated["contexts"]) != len(dedup["contexts"]):
        raise ValueError("packet identity count differs")
    used = set()
    for a, b in zip(repeated["contexts"], dedup["contexts"], strict=True):
        if {k: v for k, v in a.items() if k != "text"} != b:
            raise ValueError("packet context references changed")
        text = "\n\n".join(blocks[ref]["text"] for ref in b["block_refs"])
        if text != a["text"] or digest(text.encode()) != b["text_sha256"]:
            raise ValueError("packet lost complete context content")
        used.update(b["block_refs"])
    if used != set(blocks):
        raise ValueError("packet contains additional or missing evidence")


def measure(packet: dict, tokenizer, probes: list) -> dict:
    values = packet["contexts"] if packet["representation"] == "repeated" else packet["blocks"]
    content = "\n\n".join(value["text"] for value in values)
    wire = canonical_json(packet)
    tokens, content_tokens = count_text(wire, tokenizer), count_text(content, tokenizer)
    return {
        "packet_tokens": tokens,
        "content_tokens": content_tokens,
        "wrapper_delta_tokens": tokens - content_tokens,
        "content_chars": len(content),
        "packet_chars": len(wire),
        "packet_sha256": digest(wire.encode()),
        "probe_complete": {str(limit): export_packet(packet, limit, tokenizer)["complete"] for limit in probes},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.cache_output.exists():
        raise FileExistsError("frozen output snapshots must not be overwritten")
    if (
        not args.cache_output.resolve().is_relative_to((ROOT / "tmp").resolve())
        or args.output.resolve() == args.cache_output.resolve()
    ):
        raise ValueError("full text cache must stay in ignored tmp and differ from report")
    manifest_path = ROOT / "evals/policy-context-packet-v1/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if {k: v for k, v in manifest.items() if k != "files"} != CONFIG or set(manifest["files"]) != set(FROZEN_FILES):
        raise ValueError("frozen packet configuration differs")
    for name, sha in manifest["files"].items():
        if digest((ROOT / name).read_bytes()) != sha:
            raise ValueError(f"frozen dependency differs: {name}")
    _, cases, atoms, bundle = load_inputs(
        ROOT / "evals/policy-query-v1",
        ROOT / "tmp/policy-documents-v1/children-final.json",
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
    )
    index = catalog(json.loads((ROOT / "tmp/policy-documents-v1/drafts-audited.json").read_text(encoding="utf-8")))
    baseline = json.loads((ROOT / "reports/policy-document-ingestion/query-baseline.json").read_text(encoding="utf-8"))
    if baseline["context_chars"] != CONFIG["context_chars"]:
        raise ValueError("baseline budget differs")
    expected = {(q["id"], method) for q in cases for method in CONFIG["methods"]}
    actual = [(r["query_id"], r["method"]) for r in baseline["results"]]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError("baseline rows incomplete or duplicate")
    tokenizer = load_tokenizer()
    by_id, children = {q["id"]: q for q in cases}, {c["id"]: c for c in bundle["chunks"]}
    rows, cached = [], []
    for row in baseline["results"]:
        if row["at_k"]["2"]["hits"] != row["at_k"]["5"]["hits"][:2]:
            raise ValueError("baseline hit prefixes differ")
        case = by_id[row["query_id"]]
        for k in CONFIG["k"]:
            old = row["at_k"][str(k)]
            ranked = [(children[h["chunk_id"]], h["score"]) for h in old["hits"]]
            if any(not math.isfinite(s) for _, s in ranked):
                raise ValueError("nonfinite frozen scores")
            hits = [c for c, _ in ranked]
            selection = select_contexts(case, hits, bundle, index, CONFIG["context_chars"])
            replay = score_row(case, ranked, bundle, atoms, CONFIG["context_chars"])["at_k"][str(k)]
            if (
                replay != old
                or selection.exported_chars != old["exported_chars"]
                or list(selection.blocked_ids) != old["blocked_context_ids"]
            ):
                raise ValueError("baseline selection/scoring not reproduced")
            packets = {mode: make_packet(selection, bundle, index, mode) for mode in CONFIG["serialization"]}
            audit_pair(packets["repeated"], packets["deduplicated"])
            metadata = {
                "query_id": case["id"],
                "method": row["method"],
                "k": k,
                "selection_sha256": selection.fingerprint,
                "context_ids": selection.context_ids,
                "blocked_context_ids": selection.blocked_ids,
                "source_blocks": len(selection.block_keys),
            }
            rows.append(
                {
                    **metadata,
                    **{
                        mode: measure(packet, tokenizer, CONFIG["packet_token_probes"])
                        for mode, packet in packets.items()
                    },
                }
            )
            cached.append({**metadata, "packets": packets})
    summary = {}
    for method in CONFIG["methods"]:
        for k in CONFIG["k"]:
            group = [r for r in rows if r["method"] == method and r["k"] == k]
            summary[f"{method}/k{k}"] = {
                "prefixes": len(group),
                **{
                    mode: {
                        "mean_" + key: sum(r[mode][key] for r in group) / len(group)
                        for key in ("packet_tokens", "content_tokens", "wrapper_delta_tokens", "content_chars")
                    }
                    for mode in CONFIG["serialization"]
                },
                "packet_tokens_less_equal_more": [
                    sum(
                        (r["deduplicated"]["packet_tokens"] - r["repeated"]["packet_tokens"]) * sign > 0
                        if sign
                        else r["deduplicated"]["packet_tokens"] == r["repeated"]["packet_tokens"]
                        for r in group
                    )
                    for sign in (-1, 0, 1)
                ],
                "probe_complete": {
                    str(limit): {
                        mode: sum(r[mode]["probe_complete"][str(limit)] for r in group)
                        for mode in CONFIG["serialization"]
                    }
                    for limit in CONFIG["packet_token_probes"]
                },
            }
    common = {
        "version": CONFIG["version"],
        "manifest_sha256": digest(manifest_path.read_bytes()),
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "baseline_reproduced": True,
        "same_selected_information_set": True,
        "independent_review_count": sum(case["review"]["state"] == "APPROVED" for case in cases),
        "official_quality": None,
        "production_adoption": False,
        "new_chat_api_calls": 0,
        "production_writes": 0,
        "token_measurement": "LOCAL_DEEPSEEK_V41_CANONICAL_EVIDENCE_JSON_NOT_FULL_REQUEST_OR_PROVIDER_USAGE",
        "tokenizer": {
            "raw_sha256": RAW_SHA256,
            "gzip_sha256": GZIP_SHA256,
            "package_version": importlib.metadata.version("tokenizers"),
        },
        "context_chars": CONFIG["context_chars"],
        "packet_token_probes": CONFIG["packet_token_probes"],
    }
    for path, payload in (
        (args.cache_output, {**common, "publishable": False, "results": cached}),
        (args.output, {**common, "summary": summary, "results": rows}),
    ):
        if path == args.output:
            payload["cache_sha256"] = digest(args.cache_output.read_bytes())
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
    print(json.dumps({"prefixes": len(rows), "summary": summary}))


if __name__ == "__main__":
    main()
