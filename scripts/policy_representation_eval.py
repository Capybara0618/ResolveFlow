"""Controlled offline title/body and source-block union experiments, never production policy writes."""

from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.policies.retrieval import embedder  # noqa: E402
from scripts.policy_chunks import complete_context, token_count  # noqa: E402
from scripts.policy_documents import digest  # noqa: E402
from scripts.policy_query_eval import load_inputs, rank, score_row  # noqa: E402


def represented_text(chunk: dict, mode: str) -> str:
    if mode == "body":
        return chunk["retrieval_text"]
    if mode != "title_path":
        raise ValueError("unknown representation")
    path = chunk["section_path"]
    if not isinstance(path, list) or not all(isinstance(title, str) and title.strip() for title in path):
        raise ValueError("invalid source heading path")
    return f"章节：{' > '.join(path)}\n\n{chunk['retrieval_text']}" if path else chunk["retrieval_text"]


def build_block_index(draft: dict) -> dict:
    blocks = {}
    for document in draft["documents"]:
        for ordinal, block in enumerate(document["blocks"]):
            key = (document["source_id"], document["raw_sha256"], block["id"])
            if key in blocks or digest(block["text"].encode()) != block["text_sha256"]:
                raise ValueError("duplicate or changed source block")
            blocks[key] = {"text": block["text"], "subject": document["subject"], "ordinal": ordinal}
    return blocks


def pack_contexts(hits: list, bundle: dict, blocks: dict, max_chars: int) -> dict:
    """Admit complete contexts atomically; reuse already delivered source blocks."""
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("total context character limit must be positive")
    keys, seen, accepted, blocked = [], set(), [], []
    seen_contexts = set()
    text = ""
    for chunk in hits:
        context_id = chunk["context_id"]
        if context_id in seen_contexts:
            continue
        seen_contexts.add(context_id)
        context = bundle["contexts"].get(context_id)
        if context is None:
            raise ValueError("unknown context")
        # Validate lineage/hash independently of the export budget. Export only
        # after the entire required block union fits, never a partial context.
        complete_context(bundle, chunk["id"], max(1, len(context["text"])))
        if (context["source_id"], context["raw_sha256"], context["subject"]) != (
            chunk["source_id"],
            chunk["raw_sha256"],
            chunk["subject"],
        ):
            raise ValueError("context/source binding differs")
        refs = [(chunk["source_id"], chunk["raw_sha256"], key) for key in context["required_block_ids"]]
        if len(set(refs)) != len(refs) or any(key not in blocks for key in refs):
            raise ValueError("duplicate or unknown context source blocks")
        if any(blocks[key]["subject"] != chunk["subject"] for key in refs):
            raise ValueError("context subject differs from source")
        original = "\n\n".join(blocks[key]["text"] for key in refs)
        if original != context["text"]:
            raise ValueError("context does not contain its complete source blocks")
        added = [key for key in refs if key not in seen]
        candidate_keys = keys + added
        documents = list(dict.fromkeys(key[:2] for key in candidate_keys))
        candidate_keys.sort(key=lambda key: (documents.index(key[:2]), blocks[key]["ordinal"]))
        candidate_text = "\n\n".join(blocks[key]["text"] for key in candidate_keys)
        if len(candidate_text) > max_chars:
            blocked.append(context_id)
            continue
        keys, text = candidate_keys, candidate_text
        seen.update(added)
        accepted.append(context_id)
        if not set(refs) <= seen:
            raise ValueError("accepted context lost required evidence")
    return {
        "text": text,
        "text_sha256": digest(text.encode()),
        "exported_chars": len(text),
        "block_keys": keys,
        "accepted_context_ids": accepted,
        "blocked_context_ids": blocked,
    }


def make_variant(bundle: dict, mode: str, local) -> tuple:
    result = copy.deepcopy(bundle)
    encoder = local._encoder()
    texts = [represented_text(c, mode) for c in bundle["chunks"]]
    counts = [token_count(text, encoder.tokenizer) for text in texts]
    if any(n > encoder.max_seq_length for n in counts):
        raise ValueError("experimental representation would truncate; no implicit fallback")
    if mode == "body":
        vectors = [c["embedding"] for c in bundle["chunks"]]
    else:
        vectors = local.embed(texts)
    if len(vectors) != len(texts):
        raise ValueError("experimental vector count differs")
    for chunk, text, count, vector in zip(result["chunks"], texts, counts, vectors, strict=True):
        if len(vector) != local.dimension or not all(math.isfinite(v) for v in vector) or not any(vector):
            raise ValueError("invalid experimental vector")
        chunk.update(
            body_content_sha256=chunk["content_sha256"],
            retrieval_text=text,
            content_sha256=digest(text.encode()),
            encoder_tokens=count,
            embedding=vector,
            representation=mode,
            span_space="ORIGINAL_BODY_FRAGMENTS_NOT_PREFIXED_TEXT",
        )
    return result, {
        "chunks": len(texts),
        "max_encoder_tokens": max(counts),
        "encoder_limit": encoder.max_seq_length,
        "total_encoder_tokens": sum(counts),
    }


def check_body_reproduction(row: dict, baseline_row: dict) -> None:
    for k in ("2", "5"):
        current, previous = row["at_k"][k], baseline_row["at_k"][k]
        if [h["chunk_id"] for h in current["hits"]] != [h["chunk_id"] for h in previous["hits"]]:
            raise ValueError("body baseline ranking not reproduced")
        if any(
            not math.isclose(a["score"], b["score"], rel_tol=0, abs_tol=1e-6)
            for a, b in zip(current["hits"], previous["hits"], strict=True)
        ):
            raise ValueError("body baseline score not reproduced")
        for key in ("exported_chars", "blocked_context_ids", "draft_direct_missing", "draft_context_missing"):
            if current[key] != previous[key]:
                raise ValueError("body baseline scoring not reproduced")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.cache_output.exists():
        raise FileExistsError("experimental output snapshots must not be overwritten")
    if not args.cache_output.resolve().is_relative_to((ROOT / "tmp").resolve()):
        raise ValueError("full representation/vector cache must stay in ignored local tmp")
    if args.output.resolve() == args.cache_output.resolve():
        raise ValueError("report and full-text cache must be distinct")
    manifest_path = ROOT / "evals/policy-representation-v1/manifest.json"
    config = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files = {
        "evals/policy-query-v1/manifest.json",
        "reports/policy-document-ingestion/query-baseline.json",
        "scripts/policy_query_eval.py",
        "scripts/policy_chunks.py",
        "scripts/policy_drafts.py",
        "scripts/policy_documents.py",
        "agent/src/resolveflow/policies/retrieval.py",
    }
    if set(config["files"]) != expected_files or config["representations"] != ["body", "title_path"]:
        raise ValueError("unexpected experimental inputs/variants")
    for name, sha in config["files"].items():
        if digest((ROOT / name).read_bytes()) != sha:
            raise ValueError("frozen experiment dependency differs")
    _, cases, atoms, children = load_inputs(
        ROOT / "evals/policy-query-v1",
        ROOT / "tmp/policy-documents-v1/children-final.json",
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
    )
    draft = json.loads((ROOT / "tmp/policy-documents-v1/drafts-audited.json").read_text(encoding="utf-8"))
    blocks = build_block_index(draft)
    baseline = json.loads((ROOT / "reports/policy-document-ingestion/query-baseline.json").read_text(encoding="utf-8"))
    if config["context_chars"] != baseline["context_chars"] or config["methods"] != ["dense", "bm25"]:
        raise ValueError("baseline/config comparison differs")
    local = embedder()
    if children["encoder"] != {"model": local.model, "revision": local.revision, "dimension": local.dimension}:
        raise ValueError("experimental encoder differs")
    for name, version in baseline["packages"].items():
        if importlib.metadata.version(name) != version:
            raise ValueError("baseline package version differs")
    if any(token_count(q["query"], local._encoder().tokenizer) > local._encoder().max_seq_length for q in cases):
        raise ValueError("experimental query would truncate")
    query_vectors = local.embed([q["query"] for q in cases])
    if len(query_vectors) != len(cases) or any(
        len(v) != local.dimension or not all(math.isfinite(n) for n in v) or not any(v) for v in query_vectors
    ):
        raise ValueError("invalid experimental query vectors")
    variants, audits, rows = {}, {}, []
    old_rows = {(r["query_id"], r["method"]): r for r in baseline["results"]}
    for mode in config["representations"]:
        variant, audits[mode] = make_variant(children, mode, local)
        variants[mode] = variant
        for case, vector in zip(cases, query_vectors, strict=True):
            for method in config["methods"]:
                ranked = rank(case, variant, method, vector)
                row = score_row(case, ranked, variant, atoms, config["context_chars"])
                row.update(method=method, representation=mode)
                if mode == "body":
                    check_body_reproduction(row, old_rows[(case["id"], method)])
                for k in ("2", "5"):
                    packed = pack_contexts([c for c, _ in ranked[: int(k)]], variant, blocks, config["context_chars"])
                    selected = set(packed["block_keys"])
                    required = case["draft"]["required"]
                    missing = [
                        key
                        for key in required
                        if (atoms[key]["source_id"], atoms[key]["raw_sha256"], atoms[key]["block_id"]) not in selected
                    ]
                    row["at_k"][k]["source_block_union"] = {
                        key: packed[key]
                        for key in ("text_sha256", "exported_chars", "accepted_context_ids", "blocked_context_ids")
                    }
                    row["at_k"][k]["source_block_union"].update(
                        blocks=len(selected), draft_missing=missing, draft_complete=not missing if required else None
                    )
                rows.append(row)
    by_id = {q["id"]: q for q in cases}
    summary = {}
    for mode in config["representations"]:
        for method in config["methods"]:
            group = [r for r in rows if r["representation"] == mode and r["method"] == method]
            answerable = [r for r in group if by_id[r["query_id"]]["draft"]["answerability"] == "ANSWERABLE"]
            summary[f"{mode}/{method}"] = {
                "queries": len(group),
                "draft_answerable_n": len(answerable),
                "official_quality": None,
                "at_k": {
                    k: {
                        "draft_direct_complete": sum(r["at_k"][k]["draft_direct_complete"] for r in answerable),
                        "draft_context_complete": sum(r["at_k"][k]["draft_context_complete"] for r in answerable),
                        "draft_union_complete": sum(
                            r["at_k"][k]["source_block_union"]["draft_complete"] for r in answerable
                        ),
                        "mean_context_chars": sum(r["at_k"][k]["exported_chars"] for r in group) / len(group),
                        "mean_union_chars": sum(r["at_k"][k]["source_block_union"]["exported_chars"] for r in group)
                        / len(group),
                    }
                    for k in ("2", "5")
                },
            }
    cache = {
        "experimental_only": True,
        "publishable": False,
        "variants": variants,
        "audits": audits,
        "manifest_sha256": digest(manifest_path.read_bytes()),
        "runner_sha256": digest(Path(__file__).read_bytes()),
    }
    args.cache_output.parent.mkdir(parents=True, exist_ok=True)
    with args.cache_output.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(cache, file, ensure_ascii=False, indent=2)
        file.write("\n")
    output = {
        "version": "policy-representation-experiment-v1",
        "manifest_sha256": digest(manifest_path.read_bytes()),
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "cache_sha256": digest(args.cache_output.read_bytes()),
        "encoder": children["encoder"],
        "packages": baseline["packages"],
        "audits": audits,
        "body_baseline_reproduced": True,
        "independent_review_count": sum(q["review"]["state"] == "APPROVED" for q in cases),
        "official_quality": None,
        "production_adoption": False,
        "new_chat_api_calls": 0,
        "production_writes": 0,
        "context_chars": config["context_chars"],
        "limit_kind": "TEXT_CHARACTERS_NOT_CHAT_LLM_TOKENS",
        "summary": summary,
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps({"rows": len(rows), "audits": audits, "summary": summary}))


if __name__ == "__main__":
    main()
