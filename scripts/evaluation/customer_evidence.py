"""Offline source-bound evidence assembly; selection never receives questions or scoring labels."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from scripts.policy_chunks import representations
from scripts.policy_context_packet_eval import context_refs


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _count(tokenizer, text):
    return len(tokenizer.encode(text).ids)


def _render(spans, index, source_order):
    grouped = defaultdict(list)
    for span in spans:
        source = (span["source_id"], span["raw_sha256"])
        key = (*source, span["block_id"], span.get("table_row"))
        block = index["blocks"][key[:3]]
        if _sha(block["text"]) != block["text_sha256"]:
            raise ValueError("source block hash differs")
        rows = (
            representations(block)
            if block.get("kind") == "table"
            else [{"text": block["text"]}]
        )
        row = next((r for r in rows if r.get("table_row") == key[3]), None)
        if row is None:
            raise ValueError("unknown source table row")
        left, right = span["text_range"]
        if not (
            type(left) is int
            and type(right) is int
            and 0 <= left < right <= len(row["text"])
        ):
            raise ValueError("invalid source span")
        grouped[key].append((left, right))
    pieces = []
    keys = sorted(
        grouped,
        key=lambda k: (
            source_order.index(k[:2]),
            index["blocks"][k[:3]]["ordinal"],
            -1 if k[3] is None else k[3],
        ),
    )
    for key in keys:
        block = index["blocks"][key[:3]]
        rows = (
            representations(block)
            if block.get("kind") == "table"
            else [{"text": block["text"]}]
        )
        original = next(r["text"] for r in rows if r.get("table_row") == key[3])
        merged = []
        for left, right in sorted(grouped[key]):
            if merged and left <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], right)
            else:
                merged.append([left, right])
        for left, right in merged:
            text = original[left:right]
            pieces.append(
                {
                    "source_id": key[0],
                    "raw_sha256": key[1],
                    "block_id": key[2],
                    "table_row": key[3],
                    "text_range": [left, right],
                    "block_text_sha256": block["text_sha256"],
                    "text_sha256": _sha(text),
                    "text": text,
                }
            )
    return {"pieces": pieces, "body": "\n\n".join(p["text"] for p in pieces)}


def assemble(
    case,
    hits,
    bundle,
    index,
    tokenizer,
    *,
    expand=False,
    max_chars=8000,
    max_tokens=4096,
):
    """Admit whole retrieval anchors first, then whole existing contexts within the same body budget."""
    if (
        type(max_chars) is not int
        or type(max_tokens) is not int
        or min(max_chars, max_tokens) < 1
    ):
        raise ValueError("positive budgets required")
    originals = {c["id"]: c for c in bundle["chunks"]}
    if len(originals) != len(bundle["chunks"]):
        raise ValueError("duplicate child identity")
    scope = {(s["source_id"], s["raw_sha256"]) for s in case["scope"]}
    source_order = []
    for hit in hits:
        source = (hit["source_id"], hit["raw_sha256"])
        if (
            originals.get(hit["id"]) != hit
            or hit["subject"] != case["subject"]
            or source not in scope
        ):
            raise ValueError("unknown or out-of-scope child")
        if index["sources"][source]["subject"] != case["subject"]:
            raise ValueError("source subject differs")
        if source not in source_order:
            source_order.append(source)

    spans, admitted, blocked, parents, rejected = [], [], [], [], []

    def fits(proposed):
        packet = _render(proposed, index, source_order)
        return (
            len(packet["body"]) <= max_chars
            and _count(tokenizer, packet["body"]) <= max_tokens
        )

    for hit in hits:
        if hit["id"] in admitted or hit["id"] in blocked:
            continue
        additions = [
            {**f, "source_id": hit["source_id"], "raw_sha256": hit["raw_sha256"]}
            for f in hit["fragments"]
        ]
        if fits(spans + additions):
            spans.extend(additions)
            admitted.append(hit["id"])
        else:
            blocked.append(hit["id"])
    if expand:
        seen = set()
        for hit in hits:
            if hit["id"] not in admitted:
                continue
            cid = hit["context_id"]
            context = bundle["contexts"][cid]
            if (context["source_id"], context["raw_sha256"], context["subject"]) != (
                hit["source_id"],
                hit["raw_sha256"],
                hit["subject"],
            ):
                raise ValueError("parent binding differs from child source")
            refs = context_refs(cid, bundle, index)
            if refs in seen:
                continue
            seen.add(refs)
            additions = []
            for source, version, block_id in refs:
                block = index["blocks"][(source, version, block_id)]
                rows = (
                    representations(block)
                    if block.get("kind") == "table"
                    else [{"text": block["text"]}]
                )
                additions.extend(
                    {
                        "source_id": source,
                        "raw_sha256": version,
                        "block_id": block_id,
                        "table_row": row.get("table_row"),
                        "text_range": [0, len(row["text"])],
                    }
                    for row in rows
                    if row["text"]
                )
            if fits(spans + additions):
                spans.extend(additions)
                parents.append(cid)
            else:
                rejected.append(cid)
    packet = _render(spans, index, source_order)
    packet.update(
        admitted_child_ids=admitted,
        blocked_child_ids=blocked,
        expanded_context_ids=parents,
        blocked_context_ids=rejected,
        body_chars=len(packet["body"]),
        body_tokens=_count(tokenizer, packet["body"]),
        body_sha256=_sha(packet["body"]),
    )
    wire = {key: value for key, value in packet.items() if key != "body"}
    serialized = json.dumps(wire, ensure_ascii=False, sort_keys=True)
    packet["serialized_tokens"] = _count(tokenizer, serialized)
    packet["packet_sha256"] = _sha(serialized)
    return packet
