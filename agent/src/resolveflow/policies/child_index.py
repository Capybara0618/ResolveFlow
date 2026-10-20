"""Persist bounded retrieval spans, rank them, then return complete authoritative rules."""

from __future__ import annotations

import hashlib
import math
import struct
import time
from typing import TYPE_CHECKING, Any

from resolveflow.contracts.canonical import canonical_bytes, content_hash
from resolveflow.policies.retrieval import cosine_similarity, embed_query
from resolveflow.policies.segments import RETRIEVAL_LAYOUT

if TYPE_CHECKING:
    from resolveflow.policies.chunking import Chunk
    from resolveflow.policies.index import PolicyChunkRow, PolicyGeneration


def vector_digest(vector: list[float]) -> str:
    return hashlib.sha256(struct.pack(f"!{len(vector)}f", *vector)).hexdigest()


def fingerprint(children: list[dict[str, Any]]) -> str:
    records = [
        {
            k: row[k]
            for k in ("child_id", "parent_chunk_id", "start_offset", "end_offset", "encoder_tokens", "text_sha256")
        }
        | {"vector_sha256": vector_digest(row["embedding"])}
        for row in children
    ]
    records.sort(key=lambda row: row["child_id"])
    return hashlib.sha256(canonical_bytes(records)).hexdigest()


def prepare(chunks: tuple[Chunk, ...], encoder: Any) -> list[dict[str, Any]] | None:
    split = getattr(encoder, "policy_segments", None)
    if not callable(split):
        return None  # Existing fixture/lexical generations retain the explicit legacy layout.
    children = []
    for chunk in chunks:
        position = 0
        for number, part in enumerate(split(chunk.text)):
            if (
                part["start"] != position
                or part["end"] <= position
                or part["end"] > len(chunk.text)
                or part["text"] != chunk.text[position : part["end"]]
                or hashlib.sha256(part["text"].encode()).hexdigest() != part["text_sha256"]
                or type(part["encoder_tokens"]) is not int
                or part["encoder_tokens"] < 3
            ):
                raise ValueError("policy segmentation lost original source span")
            children.append(
                {
                    "child_id": f"{chunk.chunk_id}:s{number:04d}",
                    "parent_chunk_id": chunk.chunk_id,
                    "start_offset": part["start"],
                    "end_offset": part["end"],
                    "encoder_tokens": part["encoder_tokens"],
                    "text": part["text"],
                    "text_sha256": part["text_sha256"],
                }
            )
            position = part["end"]
        if position != len(chunk.text):
            raise ValueError("policy segmentation omitted trailing conditions")
    vectors = encoder.embed([row["text"] for row in children])
    if len(vectors) != len(children):
        raise ValueError("policy child vector count differs")
    for row, vector in zip(children, vectors, strict=True):
        if (
            len(vector) != encoder.dimension
            or not vector
            or not all(math.isfinite(v) for v in vector)
            or not any(vector)
        ):
            raise ValueError("invalid policy child embedding")
        row["embedding"] = vector
    return children


def store(connection: Any, generation: str, bundle: str, children: list[dict[str, Any]]) -> None:
    for row in children:
        connection.execute(
            """INSERT INTO policy_index_child
               (generation_id,bundle_id,child_id,parent_chunk_id,start_offset,end_offset,
                encoder_tokens,text,text_sha256,embedding)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                generation,
                bundle,
                *(
                    row[k]
                    for k in (
                        "child_id",
                        "parent_chunk_id",
                        "start_offset",
                        "end_offset",
                        "encoder_tokens",
                        "text",
                        "text_sha256",
                        "embedding",
                    )
                ),
            ),
        )


def validate_children(
    parents: list[PolicyChunkRow], children: list[dict[str, Any]], generation: PolicyGeneration
) -> None:
    if len(children) != generation.child_count or len({c["child_id"] for c in children}) != len(children):
        raise ValueError("READY policy child count/identity differs")
    if fingerprint(children) != generation.retrieval_fingerprint:
        raise ValueError("READY policy child fingerprint differs")
    by_id = {p.chunk_id: p for p in parents}
    if {c["parent_chunk_id"] for c in children} != set(by_id):
        raise ValueError("policy child parent coverage differs")
    for parent in parents:
        if (
            content_hash(
                {"bundle_id": parent.bundle_id, "chunk_id": parent.chunk_id, "title": parent.title, "text": parent.text}
            )
            != parent.content_hash
        ):
            raise ValueError("authority-owned policy parent hash differs")
        position = 0
        spans = sorted(
            (c for c in children if c["parent_chunk_id"] == parent.chunk_id), key=lambda c: c["start_offset"]
        )
        for child in spans:
            if (
                child["start_offset"] != position
                or child["end_offset"] <= position
                or child["end_offset"] > len(parent.text)
                or child["text"] != parent.text[position : child["end_offset"]]
                or hashlib.sha256(child["text"].encode()).hexdigest() != child["text_sha256"]
            ):
                raise ValueError("policy child source span/hash differs")
            vector = child["embedding"]
            if (
                len(vector) != generation.embedding_dimension
                or not all(math.isfinite(v) for v in vector)
                or not any(vector)
            ):
                raise ValueError("stored policy child vector is invalid")
            position = child["end_offset"]
        if position != len(parent.text):
            raise ValueError("policy child omitted trailing source")


def rank(
    database: Any,
    parents: list[PolicyChunkRow],
    generations: list[PolicyGeneration],
    query: str,
    encoder: Any,
    timings: dict[str, float] | None = None,
) -> list[PolicyChunkRow]:
    from resolveflow.policies.index import PolicyIndexNotReadyError

    started = time.perf_counter()
    all_children: list[tuple[str, dict[str, Any]]] = []
    try:
        for generation in generations:
            selected = [p for p in parents if p.bundle_id == generation.bundle_id]
            if generation.retrieval_layout == "whole-rule-v1":
                for parent in selected:
                    vector = parent.embedding
                    if (
                        vector is None
                        or len(vector) != generation.embedding_dimension
                        or not all(math.isfinite(v) for v in vector)
                        or not any(vector)
                    ):
                        raise ValueError("legacy policy vector is invalid")
                    all_children.append(
                        (generation.bundle_id, {"parent_chunk_id": parent.chunk_id, "embedding": vector})
                    )
                continue
            if generation.retrieval_layout != RETRIEVAL_LAYOUT:
                raise ValueError("unsupported policy retrieval layout")
            with database.connection() as connection:
                children = connection.execute(
                    """SELECT child_id,parent_chunk_id,start_offset,end_offset,encoder_tokens,text,text_sha256,embedding
                       FROM policy_index_child WHERE generation_id=%s AND bundle_id=%s ORDER BY child_id""",
                    (generation.generation_id, generation.bundle_id),
                ).fetchall()
            validate_children(selected, children, generation)
            all_children.extend((generation.bundle_id, child) for child in children)
    except (ValueError, KeyError, OverflowError, struct.error) as error:
        raise PolicyIndexNotReadyError(f"policy retrieval child integrity failed: {error}") from error
    if timings is not None:
        timings["child_read_ms"] = (time.perf_counter() - started) * 1000
    if encoder is None:
        raise PolicyIndexNotReadyError("policy child retrieval needs its pinned encoder")
    vectors = embed_query(encoder, query, timings)
    if (
        len(vectors) != 1
        or len(vectors[0]) != encoder.dimension
        or not all(math.isfinite(v) for v in vectors[0])
        or not any(vectors[0])
    ):
        raise ValueError("invalid policy query embedding")
    scores: dict[tuple[str, str], float] = {}
    for bundle, child in all_children:
        key = (bundle, child["parent_chunk_id"])
        score = cosine_similarity(vectors[0], child["embedding"])
        scores[key] = max(scores.get(key, -math.inf), score)
    for parent in parents:
        parent.score = scores[(parent.bundle_id, parent.chunk_id)]
    return parents
