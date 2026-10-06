"""Token-safe experimental retrieval children with complete source-context references.

No DB writes, policy publication or chat API. Structure remains pending review;
length safety does not establish semantic correctness or merchant adoption.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.policy_documents import digest  # noqa: E402

VERSION = "policy-retrieval-children-v1"


def token_count(text: str, tokenizer) -> int:
    return len(tokenizer(text, truncation=False, add_special_tokens=True)["input_ids"])


def split_text(text: str, tokenizer, limit: int) -> list[dict]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 3:
        raise ValueError("token limit must be an integer of at least 3")
    pieces = []
    start = 0
    while start < len(text):
        remaining = text[start:]
        encoded = tokenizer(remaining, truncation=False, add_special_tokens=True, return_offsets_mapping=True)
        if len(encoded["input_ids"]) <= limit:
            end, boundary = len(remaining), "WHOLE_REMAINDER"
        else:
            offsets = encoded["offset_mapping"]
            valid = [(a, b) for a, b in offsets if 0 <= a < b <= len(remaining)]
            overhead = len(encoded["input_ids"]) - len(valid)
            capacity = limit - overhead
            if capacity < 1 or not valid:
                raise ValueError("token offsets cannot satisfy the declared limit")
            end = valid[min(capacity, len(valid)) - 1][1]
            stops = [m.end() for m in re.finditer(r"[。！？!?；;\n]|\.(?=\s|$)", remaining[:end])]
            boundary = "TOKEN_BOUNDARY"
            if stops and stops[-1] >= end // 2:
                end, boundary = stops[-1], "SENTENCE_BOUNDARY"
            # Re-tokenization can change BPE boundaries. Verify the exact final
            # string rather than trusting offsets/count arithmetic alone.
            while end > 0 and token_count(remaining[:end], tokenizer) > limit:
                end -= 1
                boundary = "TOKEN_BOUNDARY"
            if end <= 0:
                raise ValueError("token offsets cannot make progress within limit")
        piece = remaining[:end]
        pieces.append({"text": piece, "text_range": [start, start + end], "boundary": boundary})
        start += end
    return pieces


def representations(block: dict) -> list[dict]:
    if block["kind"] != "table":
        return [{"text": block["text"], "representation": "BLOCK_TEXT"}]
    rows = block.get("rows", [])
    if not rows:
        raise ValueError("table block has no preserved rows")
    width = len(rows[0])
    simple = (
        width > 0
        and all(c.get("header") for c in rows[0])
        and all(len(row) == width and all(c.get("rowspan") == 1 and c.get("colspan") == 1 for c in row) for row in rows)
    )
    headers = [c["text"] for c in rows[0]] if simple else []
    output = []
    for row_number, row in enumerate(rows):
        text = (
            "\n".join(f"{heading}: {cell['text']}" for heading, cell in zip(headers, row, strict=True))
            if simple and row_number > 0
            else " | ".join(c["text"] for c in row)
        )
        output.append(
            {
                "text": text,
                "representation": "TABLE_ROW_WITH_HEADERS" if simple else "TABLE_ROW_RAW_CELLS",
                "table_row": row_number,
                "column_headers": headers,
                "grid_requires_review": not simple,
            }
        )
    return output


def flush_chunk(fragments, chunks, document, section, unit, tokenizer, max_tokens):
    if not fragments:
        return
    text = "\n\n".join(f["text"] for f in fragments)
    count = token_count(text, tokenizer)
    if count > max_tokens:
        raise ValueError("final chunk would truncate in encoder")
    content_hash = digest(text.encode())
    identity = digest(
        json.dumps(
            {
                "source": document["source_id"],
                "raw": document["raw_sha256"],
                "section": section["id"],
                "fragments": fragments,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    )
    chunks.append(
        {
            "id": f"{document['source_id']}:child:{identity[:24]}",
            "source_id": document["source_id"],
            "subject": document["subject"],
            "source_url": document.get("source_url"),
            "raw_sha256": document["raw_sha256"],
            "section_id": section["id"],
            "section_path": unit["section_path"],
            "context_id": unit["id"],
            "retrieval_text": text,
            "content_sha256": content_hash,
            "encoder_tokens": count,
            "fragments": list(fragments),
            "status": "PENDING_HUMAN_REVIEW",
        }
    )
    fragments.clear()


def build_chunks(bundle: dict, tokenizer, max_tokens: int, encoder_limit: int) -> dict:
    if (
        isinstance(encoder_limit, bool)
        or not isinstance(encoder_limit, int)
        or encoder_limit < 3
        or isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or not 3 <= max_tokens <= encoder_limit
    ):
        raise ValueError("chunk target must be within the actual encoder limit")
    chunks, contexts = [], {}
    source_ids = set()
    for document in bundle["documents"]:
        source_id, subject = document["source_id"], document["subject"]
        if source_id in source_ids or not subject.startswith("EXTERNAL:"):
            raise ValueError("duplicate or non-external source")
        source_ids.add(source_id)
        blocks = document["blocks"]
        by_block = {b["id"]: b for b in blocks}
        if len(by_block) != len(blocks):
            raise ValueError("duplicate source block ids")
        for block in blocks:
            if digest(block["text"].encode()) != block["text_sha256"]:
                raise ValueError("source block hash differs")
        assigned = [key for section in document["sections"] for key in section["direct_block_ids"]]
        if Counter(assigned) != Counter(by_block.keys()):
            raise ValueError("direct block ownership is incomplete or duplicated")
        units = {u["heading_block_id"]: u for u in document["draft_units"]}
        if len(units) != len(document["draft_units"]):
            raise ValueError("duplicate section context drafts")
        for section in document["sections"]:
            if not section["direct_block_ids"]:
                continue
            unit = units.get(section["heading_block_id"])
            if unit is None:
                raise ValueError("section has no complete context draft")
            required = unit["context_block_ids"]
            if len(set(required)) != len(required) or not set(required) <= set(by_block):
                raise ValueError("context contains unknown or duplicated source blocks")
            expected = "\n\n".join(by_block[key]["text"] for key in required)
            if unit["context_text"] != expected or unit["context_sha256"] != digest(expected.encode()):
                raise ValueError("complete context hash/text differs")
            if not set(section["direct_block_ids"]) <= set(required):
                raise ValueError("context excludes its own source section")
            context_id = unit["id"]
            if context_id in contexts:
                raise ValueError("duplicate complete context identity")
            contexts[context_id] = {
                "source_id": source_id,
                "subject": subject,
                "raw_sha256": document["raw_sha256"],
                "required_block_ids": required,
                "text": expected,
                "text_sha256": digest(expected.encode()),
                "chars": len(expected),
                "section_path": unit["section_path"],
                "status": "PENDING_HUMAN_REVIEW",
            }
            fragments = []

            for block_id in section["direct_block_ids"]:
                block = by_block[block_id]
                for representation in representations(block):
                    original = representation["text"]
                    for piece in split_text(original, tokenizer, max_tokens):
                        fragment = {
                            "block_id": block_id,
                            "block_text_sha256": block["text_sha256"],
                            "raw_fragment_sha256": block["raw_fragment_sha256"],
                            "block_locator": block["locator"],
                            "representation": representation["representation"],
                            "text_range": piece["text_range"],
                            "text": piece["text"],
                            "fragment_sha256": digest(piece["text"].encode()),
                            "representation_sha256": digest(original.encode()),
                            "boundary": piece["boundary"],
                        }
                        for key in ("table_row", "column_headers", "grid_requires_review"):
                            if key in representation:
                                fragment[key] = representation[key]
                        combined = "\n\n".join(f["text"] for f in fragments + [fragment])
                        if fragments and token_count(combined, tokenizer) > max_tokens:
                            flush_chunk(fragments, chunks, document, section, unit, tokenizer, max_tokens)
                        fragments.append(fragment)
            flush_chunk(fragments, chunks, document, section, unit, tokenizer, max_tokens)
    if not chunks or len({c["id"] for c in chunks}) != len(chunks):
        raise ValueError("empty or duplicate retrieval children")
    return {
        "version": VERSION,
        "chunks": chunks,
        "contexts": contexts,
        "max_tokens": max_tokens,
        "encoder_limit": encoder_limit,
        "publishable": False,
        "indexable": False,
        "status": "PENDING_HUMAN_REVIEW",
        "independent_review_count": 0,
        "retrieval_accuracy": None,
    }


def complete_context(bundle: dict, chunk_id: str, max_chars: int) -> dict:
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("context character limit must be positive")
    matches = [c for c in bundle["chunks"] if c["id"] == chunk_id]
    if len(matches) != 1:
        raise ValueError("unknown or ambiguous chunk")
    chunk = matches[0]
    context = bundle["contexts"].get(chunk["context_id"])
    if (
        context is None
        or context["source_id"] != chunk["source_id"]
        or context["subject"] != chunk["subject"]
        or context["raw_sha256"] != chunk["raw_sha256"]
    ):
        raise ValueError("chunk/context source binding differs")
    if digest(context["text"].encode()) != context["text_sha256"]:
        raise ValueError("context hash differs")
    fits = len(context["text"]) <= max_chars
    return {
        "source_id": context["source_id"],
        "subject": context["subject"],
        "status": "PENDING_HUMAN_REVIEW" if fits else "CONTEXT_TOO_LARGE",
        "complete": fits,
        "text": context["text"] if fits else None,
        "text_sha256": context["text_sha256"],
        "required_block_ids": context["required_block_ids"],
        "chars": len(context["text"]),
        "max_chars": max_chars,
        "limit_kind": "CHARACTERS_NOT_LLM_TOKENS",
    }


def load_draft(path: Path, summary_path: Path) -> dict:
    raw = path.read_bytes()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if digest(raw) != summary["local_output_sha256"]:
        raise ValueError("frozen draft output hash differs")
    bundle = json.loads(raw)
    for key, file in (
        ("builder_sha256", ROOT / "scripts/policy_drafts.py"),
        ("parser_sha256", ROOT / "scripts/policy_documents.py"),
        ("source_manifest_sha256", ROOT / "evals/policy-documents-v1/manifest.json"),
        ("profile_manifest_sha256", ROOT / "evals/policy-structure-v1/manifest.json"),
    ):
        if bundle[key] != summary[key] or bundle[key] != digest(file.read_bytes()):
            raise ValueError("draft source/config/code fingerprint differs")
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, default=Path("tmp/policy-documents-v1/drafts-audited.json"))
    parser.add_argument(
        "--draft-summary", type=Path, default=Path("reports/policy-document-ingestion/draft-summary.json")
    )
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--embed", action="store_true", help="local experimental vectors, never production policy index"
    )
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("existing child snapshot must not be overwritten")
    draft = load_draft(args.draft, args.draft_summary)
    sys.path.insert(0, str(ROOT / "agent/src"))
    from resolveflow.policies.retrieval import embedder

    local = embedder()
    encoder = local._encoder()
    result = build_chunks(draft, encoder.tokenizer, args.max_tokens, encoder.max_seq_length)
    result.update(
        source_draft_sha256=digest(args.draft.read_bytes()),
        builder_sha256=digest(Path(__file__).read_bytes()),
        encoder={"model": local.model, "revision": local.revision, "dimension": local.dimension},
    )
    if args.embed:
        vectors = local.embed([c["retrieval_text"] for c in result["chunks"]])
        if len(vectors) != len(result["chunks"]):
            raise ValueError("encoder returned incorrect vector count")
        for chunk, vector in zip(result["chunks"], vectors, strict=True):
            if len(vector) != local.dimension or not all(math.isfinite(v) for v in vector) or not any(vector):
                raise ValueError("encoder returned an invalid vector")
            chunk["embedding"] = vector
        result["experimental_vectors_ready"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(
        json.dumps(
            {
                "chunks": len(result["chunks"]),
                "max_encoder_tokens": max(c["encoder_tokens"] for c in result["chunks"]),
                "contexts": len(result["contexts"]),
                "publishable": False,
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
