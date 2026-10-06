"""Frozen offline policy-query diagnostics; pending drafts never become official Gold."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.policies.retrieval import bm25_scores, cosine_similarity, embedder  # noqa: E402
from scripts.policy_chunks import complete_context, load_draft, representations, token_count  # noqa: E402
from scripts.policy_documents import digest  # noqa: E402

ANSWERABILITY = {"ANSWERABLE", "PARTIAL", "NEEDS_CLARIFICATION", "NOT_IN_CORPUS"}


def coverage(chunks: list, atom: dict) -> bool:
    """Full source-span coverage, not merely one matching block ID or repeated overlap."""
    start, end = atom["text_range"]
    intervals = []
    for chunk in chunks:
        if (chunk["source_id"], chunk["raw_sha256"]) != (atom["source_id"], atom["raw_sha256"]):
            continue
        for fragment in chunk["fragments"]:
            if (fragment["block_id"], fragment.get("table_row")) == (atom["block_id"], atom["table_row"]):
                left, right = fragment["text_range"]
                intervals.append((max(start, left), min(end, right)))
    position = start
    for left, right in sorted(intervals):
        if left > position:
            break
        position = max(position, right)
    return position >= end


def validate_cases(cases: list, atoms: dict) -> None:
    if not cases or len({q["id"] for q in cases}) != len(cases):
        raise ValueError("empty or duplicate query ids")
    for case in cases:
        scope = {(s["source_id"], s["raw_sha256"]) for s in case["scope"]}
        if not scope or len(scope) != len(case["scope"]) or not case["query"].strip():
            raise ValueError("invalid query or duplicate scope")
        review = case["review"]
        if review["state"] == "PENDING":
            if any(review.get(key) is not None for key in ("labels", "reviewer", "origin")):
                raise ValueError("pending review cannot contain official labels")
        elif review["state"] == "APPROVED":
            if (
                review.get("origin") != "INDEPENDENT_HUMAN"
                or not isinstance(review.get("reviewer"), str)
                or not review["reviewer"].strip()
                or not isinstance(review.get("labels"), dict)
            ):
                raise ValueError("approved review requires independently attributed labels")
        else:
            raise ValueError("unknown review state")
        for labels in (case["draft"], review.get("labels")):
            if labels is None:
                continue
            if labels["answerability"] not in ANSWERABILITY:
                raise ValueError("unknown answerability")
            required, nearby = labels["required"], labels["related_not_sufficient"]
            if len(set(required)) != len(required) or len(set(nearby)) != len(nearby) or set(required) & set(nearby):
                raise ValueError("ambiguous evidence labels")
            if (
                labels["answerability"] == "ANSWERABLE"
                and not required
                or labels["answerability"] in {"NOT_IN_CORPUS", "NEEDS_CLARIFICATION"}
                and required
            ):
                raise ValueError("answerability/evidence differs")
            for key in required + nearby:
                atom = atoms.get(key)
                if atom is None or (atom["source_id"], atom["raw_sha256"]) not in scope:
                    raise ValueError("unknown or out-of-scope evidence")


def rank(case: dict, bundle: dict, method: str, query_vector: list | None = None) -> list:
    scope = {(s["source_id"], s["raw_sha256"]) for s in case["scope"]}
    candidates = [
        c for c in bundle["chunks"] if c["subject"] == case["subject"] and (c["source_id"], c["raw_sha256"]) in scope
    ]
    if not candidates:
        raise ValueError("query has no scoped candidates")
    if method == "dense":
        scores = [cosine_similarity(query_vector, c["embedding"]) for c in candidates]
    elif method == "bm25":
        scores = bm25_scores([c["retrieval_text"] for c in candidates], case["query"])
    else:
        raise ValueError("unknown retrieval method")
    if len(scores) != len(candidates) or not all(math.isfinite(s) for s in scores):
        raise ValueError("invalid retrieval scores")
    return sorted(zip(candidates, scores, strict=True), key=lambda pair: (-pair[1], pair[0]["id"]))


def score_row(case: dict, ranked: list, bundle: dict, atoms: dict, max_context_chars: int) -> dict:
    if isinstance(max_context_chars, bool) or not isinstance(max_context_chars, int) or max_context_chars < 1:
        raise ValueError("total context character limit must be positive")
    scope = {(s["source_id"], s["raw_sha256"]) for s in case["scope"]}
    if any(c["subject"] != case["subject"] or (c["source_id"], c["raw_sha256"]) not in scope for c, _ in ranked):
        raise ValueError("ranked result escaped frozen query scope")
    if len({c["id"] for c, _ in ranked}) != len(ranked):
        raise ValueError("duplicate ranked children")
    at_k = {}
    approved = case["review"]["state"] == "APPROVED"
    for k in (2, 5):
        hits = [c for c, _ in ranked[:k]]
        seen_ids, seen_payloads, expanded, blocked = set(), set(), set(), []
        used = 0
        for chunk in hits:
            context_id = chunk["context_id"]
            if context_id in seen_ids:
                continue
            seen_ids.add(context_id)
            # Validate complete context even when its identical payload was already seen.
            context = complete_context(bundle, chunk["id"], max_context_chars)
            payload_key = (chunk["source_id"], chunk["raw_sha256"], context["text_sha256"])
            if payload_key in seen_payloads:
                continue
            seen_payloads.add(payload_key)
            separator = 2 if used else 0
            if not context["complete"] or context["chars"] + separator > max_context_chars - used:
                blocked.append(context_id)
                continue
            used += context["chars"] + separator
            expanded.update((chunk["source_id"], chunk["raw_sha256"], key) for key in context["required_block_ids"])

        values = {
            "hits": [
                {"chunk_id": c["id"], "source_id": c["source_id"], "raw_sha256": c["raw_sha256"], "score": s}
                for c, s in ranked[:k]
            ],
            "exported_chars": used,
            "blocked_context_ids": blocked,
        }
        for prefix, labels in (("draft", case["draft"]), ("reviewed", case["review"].get("labels"))):
            if labels is None:
                continue
            required = labels["required"]
            direct_missing = [key for key in required if not coverage(hits, atoms[key])]
            context_missing = [
                key
                for key in required
                if (atoms[key]["source_id"], atoms[key]["raw_sha256"], atoms[key]["block_id"]) not in expanded
            ]
            values.update(
                {
                    f"{prefix}_direct_missing": direct_missing,
                    f"{prefix}_context_missing": context_missing,
                    f"{prefix}_direct_complete": not direct_missing if required else None,
                    f"{prefix}_context_complete": not context_missing if required else None,
                    f"{prefix}_related_not_sufficient_hits": [
                        key for key in labels["related_not_sufficient"] if coverage(hits, atoms[key])
                    ],
                }
            )
        at_k[str(k)] = values
    return {
        "query_id": case["id"],
        "origin": case["origin"],
        "subject": case["subject"],
        "review_state": case["review"]["state"],
        "draft_answerability": case["draft"]["answerability"],
        "official_score": {str(k): at_k[str(k)]["reviewed_context_complete"] for k in (2, 5)}
        if approved and case["review"]["labels"]["answerability"] == "ANSWERABLE"
        else None,
        "at_k": at_k,
    }


def load_inputs(directory: Path, child_path: Path, draft_path: Path) -> tuple:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if set(manifest["files"]) != {"queries.json", "evidence.json"}:
        raise ValueError("unexpected frozen query files")
    for name, sha in manifest["files"].items():
        if digest((directory / name).read_bytes()) != sha:
            raise ValueError("query/evidence frozen hash differs")
    if (
        digest(child_path.read_bytes()) != manifest["children_sha256"]
        or digest(draft_path.read_bytes()) != manifest["draft_sha256"]
    ):
        raise ValueError("corpus snapshot differs")
    upstream = ROOT / "evals/external-faq-v1"
    if digest((upstream / "manifest.json").read_bytes()) != manifest["faq_manifest_sha256"]:
        raise ValueError("FAQ manifest differs")
    faq_manifest = json.loads((upstream / "manifest.json").read_text(encoding="utf-8"))
    for name, sha in faq_manifest["files"].items():
        if name not in {"queries.json", "sources.json"} or digest((upstream / name).read_bytes()) != sha:
            raise ValueError("FAQ frozen source differs")
    faq = {s["id"]: s for s in json.loads((upstream / "sources.json").read_text(encoding="utf-8"))}
    draft = load_draft(draft_path, ROOT / "reports/policy-document-ingestion/draft-summary.json")
    children = json.loads(child_path.read_text(encoding="utf-8"))
    if children["builder_sha256"] != digest((ROOT / "scripts/policy_chunks.py").read_bytes()) or children[
        "source_draft_sha256"
    ] != digest(draft_path.read_bytes()):
        raise ValueError("child builder or source draft differs")
    documents = {d["source_id"]: d for d in draft["documents"]}
    atom_list = json.loads((directory / "evidence.json").read_text(encoding="utf-8"))
    atoms = {a["id"]: a for a in atom_list}
    if not atoms or len(atoms) != len(atom_list):
        raise ValueError("empty or duplicate evidence ids")
    for atom in atoms.values():
        doc = documents.get(atom["source_id"])
        if doc is None or atom["raw_sha256"] != doc["raw_sha256"] or atom["subject"] != doc["subject"]:
            raise ValueError("evidence source binding differs")
        block = next((b for b in doc["blocks"] if b["id"] == atom["block_id"]), None)
        reps = [] if block is None else [r for r in representations(block) if r.get("table_row") == atom["table_row"]]
        if len(reps) != 1 or block["text_sha256"] != atom["block_text_sha256"]:
            raise ValueError("evidence block/row differs")
        text = reps[0]["text"]
        start, end = atom["text_range"]
        if (
            not all(isinstance(n, int) and not isinstance(n, bool) for n in (start, end))
            or not 0 <= start < end <= len(text)
            or digest(text.encode()) != atom["representation_sha256"]
            or digest(text[start:end].encode()) != atom["span_sha256"]
        ):
            raise ValueError("evidence span/hash differs")
    cases = json.loads((directory / "queries.json").read_text(encoding="utf-8"))
    validate_cases(cases, atoms)
    if (
        manifest["queries"] != len(cases)
        or manifest["faq_questions"] != sum(q["origin"]["kind"] == "OFFICIAL_FAQ_REUSED" for q in cases)
        or manifest["synthetic_questions"] != sum(q["origin"]["kind"] == "CODEX_SYNTHETIC" for q in cases)
        or manifest["source_families"] != len({q["subject"] for q in cases})
    ):
        raise ValueError("query origin/family denominator differs")
    for case in cases:
        for scope in case["scope"]:
            doc = documents.get(scope["source_id"])
            if doc is None or scope["raw_sha256"] != doc["raw_sha256"] or case["subject"] != doc["subject"]:
                raise ValueError("query subject/snapshot differs")
        origin = case["origin"]
        if origin["kind"] == "OFFICIAL_FAQ_REUSED":
            source = faq.get(origin["source_id"])
            if (
                source is None
                or case["query"] != source["question"]
                or origin["url"] != source["url"]
                or digest(case["query"].encode()) != source["question_sha256"]
                or case["subject"] != "EXTERNAL:JD"
            ):
                raise ValueError("official query provenance differs")
        elif origin["kind"] != "CODEX_SYNTHETIC":
            raise ValueError("unknown query origin")
    return manifest, cases, atoms, children


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals/policy-query-v1")
    parser.add_argument("--children", type=Path, default=ROOT / "tmp/policy-documents-v1/children-final.json")
    parser.add_argument("--draft", type=Path, default=ROOT / "tmp/policy-documents-v1/drafts-audited.json")
    parser.add_argument("--context-chars", type=int, default=8000)
    parser.add_argument("--require-reviewed", action="store_true")
    parser.add_argument(
        "--prepare-review", action="store_true", help="local full-source pack without draft labels/rankings"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.context_chars < 1:
        parser.error("context-chars must be positive")
    if args.output.exists():
        raise FileExistsError("existing report must not be overwritten")
    _, cases, atoms, children = load_inputs(args.dataset, args.children, args.draft)
    if args.require_reviewed and any(q["review"]["state"] != "APPROVED" for q in cases):
        raise ValueError("independent labels pending; reviewed quality gate cannot pass")
    if args.prepare_review:
        if not args.output.resolve().is_relative_to((ROOT / "tmp").resolve()):
            raise ValueError("full-source review pack must stay in ignored local tmp")
        draft = json.loads(args.draft.read_text(encoding="utf-8"))
        pack = {
            "kind": "UNLABELLED_SOURCE_REVIEW_PACK_NOT_GOLD",
            "query_manifest_sha256": digest((args.dataset / "manifest.json").read_bytes()),
            "source_structure_status": "CODEX_STRUCTURE_DRAFT_PENDING_REVIEW",
            "questions": [{key: case[key] for key in ("id", "query", "subject", "scope", "origin")} for case in cases],
            "documents": [
                {key: d[key] for key in ("source_id", "subject", "source_url", "raw_sha256", "blocks")}
                for d in draft["documents"]
            ],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(pack, file, ensure_ascii=False, indent=2)
            file.write("\n")
        print(json.dumps({"review_questions": len(cases), "documents": len(pack["documents"]), "rankings": 0}))
        return
    local = embedder()
    encoder = local._encoder()
    if children["encoder"] != {"model": local.model, "revision": local.revision, "dimension": local.dimension}:
        raise ValueError("query encoder differs from corpus")
    if any(token_count(q["query"], encoder.tokenizer) > encoder.max_seq_length for q in cases):
        raise ValueError("query would truncate in encoder")
    vectors = local.embed([q["query"] for q in cases])
    if len(vectors) != len(cases):
        raise ValueError("query vector count differs")
    for vector in vectors + [c["embedding"] for c in children["chunks"]]:
        if len(vector) != local.dimension or not all(math.isfinite(v) for v in vector) or not any(vector):
            raise ValueError("invalid query/corpus vector")
    rows = []
    for case, vector in zip(cases, vectors, strict=True):
        for method in ("dense", "bm25"):
            row = score_row(case, rank(case, children, method, vector), children, atoms, args.context_chars)
            row["method"] = method
            rows.append(row)
    summary = {}
    for method in ("dense", "bm25"):
        group = [r for r in rows if r["method"] == method]
        reviewed = [r for r in group if r["official_score"] is not None]
        summary[method] = {
            "queries": len(group),
            "reviewed_answerable_n": len(reviewed),
            "all_required_context_at_k": {
                str(k): sum(r["official_score"][str(k)] for r in reviewed) / len(reviewed) if reviewed else None
                for k in (2, 5)
            },
            "mean_exported_chars_at_k": {
                str(k): sum(r["at_k"][str(k)]["exported_chars"] for r in group) / len(group) for k in (2, 5)
            },
            "all_required_direct_at_k": {
                str(k): sum(r["at_k"][str(k)]["reviewed_direct_complete"] for r in reviewed) / len(reviewed)
                if reviewed
                else None
                for k in (2, 5)
            },
            "abstention_accuracy": None,
        }
    output = {
        "version": "policy-query-baseline-v1",
        "query_manifest_sha256": digest((args.dataset / "manifest.json").read_bytes()),
        "children_sha256": digest(args.children.read_bytes()),
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "retrieval_code_sha256": digest((ROOT / "agent/src/resolveflow/policies/retrieval.py").read_bytes()),
        "child_builder_sha256": children["builder_sha256"],
        "encoder": children["encoder"],
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("sentence-transformers", "transformers", "torch", "jieba", "rank-bm25")
        },
        "context_chars": args.context_chars,
        "limit_kind": "TOTAL_CHARACTERS_NOT_CHAT_LLM_TOKENS",
        "independent_review_count": sum(q["review"]["state"] == "APPROVED" for q in cases),
        "official_faq_questions": sum(q["origin"]["kind"] == "OFFICIAL_FAQ_REUSED" for q in cases),
        "synthetic_questions": sum(q["origin"]["kind"] == "CODEX_SYNTHETIC" for q in cases),
        "new_chat_api_calls": 0,
        "production_writes": 0,
        "summary": summary,
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps({"rows": len(rows), "reviewed": output["independent_review_count"], "summary": summary}))


if __name__ == "__main__":
    main()
