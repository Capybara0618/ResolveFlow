"""Offline source-structure candidates. No query text, labels, business writes or policy interpretation."""

from __future__ import annotations

import copy
import hashlib
import re
from collections import defaultdict

from scripts.policy_chunks import representations, split_text, token_count
from scripts.policy_documents import digest


def numbered_level(text: str) -> int | None:
    """Short typographic captions only; a numbered substantive sentence is not a heading."""
    if len(text) > 70 or "\n" in text or re.search(r"[。；;！？!?]", text):
        return None
    found = re.match(r"^(\d+(?:\.\d+)*)(?:\.\s*|\s+|(?=[^\d.]))\D", text)
    if found:
        return 2 + len(found.group(1).split("."))
    return None


def source_structure(document: dict) -> dict:
    original = {s["heading_block_id"]: s["level"] for s in document["sections"] if s["heading_block_id"]}
    blocks = {b["id"]: b for b in document["blocks"]}
    stack, governing, rows, additions = [], None, {}, []
    for block in document["blocks"]:
        text, key = block["text"], block["id"]
        level = original.get(key)
        if level is None:
            level = numbered_level(text)
            if level is not None:
                additions.append({"block_id": key, "level": level, "origin": "NUMBERED_CAPTION_CANDIDATE"})
        if level is not None:
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, key))
            governing = None
        # A colon-ended introduction owns following parenthesized list members until a new prose item.
        is_list = bool(re.match(r"^[（(]\d+[）)]", text))
        if governing is not None and not is_list and key != governing:
            governing = None
        refs = [k for _, k in stack if k != key]
        if governing is not None and governing != key:
            refs.append(governing)
        rows[key] = {"heading_ids": list(dict.fromkeys(refs)), "section_key": stack[-1][1] if stack else "$root"}
        if level is None and text.rstrip().endswith(("：", ":")):
            governing = key
    return {"blocks": blocks, "membership": rows, "added_headings": additions}


def source_metadata(draft: dict) -> list:
    result = []
    for doc in draft["documents"]:
        dates = []
        for block in doc["blocks"]:
            match = re.match(r"^(版本生效日期|最近更新日期)\s*[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日", block["text"])
            if match:
                dates.append(
                    {
                        "kind": match.group(1),
                        "date": f"{int(match[2]):04d}-{int(match[3]):02d}-{int(match[4]):02d}",
                        "block_id": block["id"],
                        "text_sha256": block["text_sha256"],
                        "locator": block["locator"],
                    }
                )
        result.append(
            {
                "source_id": doc["source_id"],
                "raw_sha256": doc["raw_sha256"],
                "dates_found_in_source": dates,
                "authority": "EXTERNAL_REFERENCE_NOT_MERCHANT_POLICY",
            }
        )
    return result


def atomic_bundle(draft: dict, original: dict, encoder) -> tuple:
    """One block/table-row group with exact token spans; full old authority context retained separately."""
    output = copy.deepcopy(original)
    output["chunks"] = []
    audits = []
    old_blocks = defaultdict(list)
    for chunk in original["chunks"]:
        for fragment in chunk["fragments"]:
            old_blocks[(chunk["source_id"], fragment["block_id"])].append(chunk["context_id"])
    tokenizer = encoder.tokenizer
    for doc in draft["documents"]:
        structure = source_structure(doc)
        blocks, membership = structure["blocks"], structure["membership"]
        audits.append({"source_id": doc["source_id"], "added_headings": structure["added_headings"]})
        for block in doc["blocks"]:
            key = block["id"]
            headings = membership[key]["heading_ids"]
            prefix = "章节：" + " > ".join(blocks[h]["text"] for h in headings) + "\n\n" if headings else ""
            # Prefix is source-bound search metadata, not a substitute for body evidence.
            reserved = token_count(prefix, tokenizer) if prefix else 0
            capacity = 384 - reserved
            if capacity < 16:
                raise ValueError("source heading prefix too long; requires an explicit new representation")
            contexts = list(dict.fromkeys(old_blocks[(doc["source_id"], key)]))
            if not contexts:
                raise ValueError("source block has no authority context")
            # Keep the smallest full context among the source's existing bindings, not a query-specific selection.
            context_id = min(contexts, key=lambda cid: (len(original["contexts"][cid]["text"]), cid))
            for rep in representations(block):
                row = rep.get("table_row")
                group = f"{key}:row={row}"
                for number, part in enumerate(split_text(rep["text"], tokenizer, capacity)):
                    search_text = prefix + part["text"]
                    tokens = token_count(search_text, tokenizer)
                    if tokens > 384:
                        raise ValueError("atomic source representation exceeds encoder target")
                    fragment = {
                        "block_id": key,
                        "block_text_sha256": block["text_sha256"],
                        "raw_fragment_sha256": block["raw_fragment_sha256"],
                        "block_locator": block["locator"],
                        "representation": rep["representation"],
                        "table_row": row,
                        "text_range": part["text_range"],
                        "text": part["text"],
                        "fragment_sha256": digest(part["text"].encode()),
                        "representation_sha256": digest(rep["text"].encode()),
                        "boundary": part["boundary"],
                    }
                    identity = hashlib.sha256(
                        f"{doc['raw_sha256']}|{group}|{number}|{search_text}".encode()
                    ).hexdigest()[:24]
                    output["chunks"].append(
                        {
                            "id": f"{doc['source_id']}:atomic:{identity}",
                            "source_id": doc["source_id"],
                            "subject": doc["subject"],
                            "raw_sha256": doc["raw_sha256"],
                            "context_id": context_id,
                            "retrieval_text": search_text,
                            "content_sha256": digest(search_text.encode()),
                            "encoder_tokens": tokens,
                            "fragments": [fragment],
                            "group_id": group,
                            "heading_ids": headings,
                            "section_key": membership[key]["section_key"],
                            "section_path": [blocks[h]["text"] for h in headings],
                            "span_space": "ORIGINAL_BODY_NOT_SEARCH_PREFIX",
                            "representation": "SOURCE_PATH_ATOMIC",
                        }
                    )
    return output, audits


def aggregate(ranked: list, mode: str, bundle: dict) -> list:
    if mode not in {"none", "parent", "atom"}:
        raise ValueError("unknown grouping strategy")
    groups, output = set(), []
    for chunk, score in ranked:
        if mode == "none":
            key = chunk["id"]
        elif mode == "parent":
            key = (chunk["source_id"], chunk["raw_sha256"], bundle["contexts"][chunk["context_id"]]["text_sha256"])
        else:
            key = (chunk["source_id"], chunk["raw_sha256"], chunk["group_id"])
        if key in groups:
            continue
        groups.add(key)
        output.append((chunk, score))
    return output


def selected_spans(hits: list, bundle: dict, grouping: str) -> list:
    """An admitted atomic block/row is a group: recover all spans, never treat a partial child as complete."""
    if grouping != "atom":
        return hits
    identities = {(c["source_id"], c["raw_sha256"], c["group_id"]) for c in hits}
    return [c for c in bundle["chunks"] if (c["source_id"], c["raw_sha256"], c["group_id"]) in identities]


def rrf(dense: list, lexical: list, window: int = 20, constant: int = 60) -> list:
    if type(window) is not int or window < 1 or type(constant) is not int or constant < 1:
        raise ValueError("invalid RRF parameters")
    scores, chunks = defaultdict(float), {}
    for results, positive_only in ((dense, False), (lexical, True)):
        if len({c["id"] for c, _ in results}) != len(results):
            raise ValueError("duplicate RRF input identity")
        candidates = [(c, score) for c, score in results if not positive_only or score > 0][:window]
        for position, (chunk, _) in enumerate(candidates, 1):
            key = (chunk["source_id"], chunk["raw_sha256"], chunk.get("group_id", chunk["id"]))
            chunks.setdefault(key, chunk)
            scores[key] += 1 / (constant + position)
    return sorted(((chunks[k], score) for k, score in scores.items()), key=lambda pair: (-pair[1], pair[0]["id"]))


def local_packet(case: dict, hits: list, bundle: dict, draft: dict, max_chars: int) -> dict:
    """Experimental evidence windows, explicitly NOT a guarantee of complete policy conditions."""
    scope = {(s["source_id"], s["raw_sha256"]) for s in case["scope"]}
    documents = {d["source_id"]: d for d in draft["documents"]}
    selected, blocked = {}, []
    for hit in hits:
        source = hit["source_id"]
        if (source, hit["raw_sha256"]) not in scope or hit["subject"] != case["subject"]:
            raise ValueError("local packet escaped frozen scope")
        doc = documents[source]
        if doc["raw_sha256"] != hit["raw_sha256"]:
            raise ValueError("local packet source version differs")
        structure = source_structure(doc)
        blocks, membership = structure["blocks"], structure["membership"]
        ids = [b["id"] for b in doc["blocks"]]
        refs = set()
        for fragment in hit["fragments"]:
            block_id = fragment["block_id"]
            position = ids.index(block_id)
            refs.add(block_id)
            refs.update(membership[block_id]["heading_ids"])
            for offset in (-1, 1):
                next_position = position + offset
                if 0 <= next_position < len(ids):
                    neighbor = ids[next_position]
                    if membership[neighbor]["section_key"] == membership[block_id]["section_key"]:
                        refs.add(neighbor)
        candidate = selected | {(source, hit["raw_sha256"], k): blocks[k] for k in refs}
        text = "\n\n".join(candidate[k]["text"] for k in sorted(candidate))
        if len(text) > max_chars:
            blocked.append(hit["id"])
            continue
        selected = candidate
    keys = sorted(selected)
    text = "\n\n".join(selected[k]["text"] for k in keys)
    return {
        "block_keys": keys,
        "text": text,
        "text_sha256": digest(text.encode()),
        "exported_chars": len(text),
        "blocked_ids": blocked,
        "complete_policy_guaranteed": False,
    }
