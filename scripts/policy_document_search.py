"""Query frozen external documents and produce source-verifiable evidence; never merchant authorization."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.harness.context import canonical_json  # noqa: E402
from resolveflow.harness.token_counting import load_tokenizer  # noqa: E402
from resolveflow.policies.retrieval import embedder  # noqa: E402
from scripts.policy_chunks import load_draft  # noqa: E402
from scripts.policy_context_packet_eval import catalog, make_packet, select_contexts  # noqa: E402
from scripts.policy_documents import digest  # noqa: E402
from scripts.policy_query_eval import load_inputs, rank  # noqa: E402
from scripts.policy_short_packet_eval import compact, resolve  # noqa: E402
from scripts.policy_structure_candidates import rrf  # noqa: E402
from scripts.policy_structure_eval import read, verify_freeze  # noqa: E402


def query_scope(source_ids: list[str], draft: dict) -> dict:
    documents = {d["source_id"]: d for d in draft["documents"]}
    if not source_ids or len(set(source_ids)) != len(source_ids) or not set(source_ids) <= set(documents):
        raise ValueError("explicit known nonduplicate source scope required")
    subjects = {documents[key]["subject"] for key in source_ids}
    if len(subjects) != 1 or not next(iter(subjects)).startswith("EXTERNAL:"):
        raise ValueError("one external subject per query; cross-subject search prohibited")
    return {
        "subject": next(iter(subjects)),
        "scope": [{"source_id": key, "raw_sha256": documents[key]["raw_sha256"]} for key in source_ids],
    }


def search(query: str, source_ids: list[str], strategy: str, top_k: int) -> dict:
    if not isinstance(query, str) or not query.strip() or type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError("nonempty query and top_k=1..5 required")
    if strategy not in {"dense", "body-rrf", "path-rrf"}:
        raise ValueError("unknown explicit document search strategy")
    manifest = read(ROOT / "evals/rag-structure-v1/fusion-manifest.json")
    verify_freeze(manifest)
    _, _, _, body = load_inputs(
        ROOT / "evals/policy-query-v1",
        ROOT / "tmp/policy-documents-v1/children-final.json",
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
    )
    draft = load_draft(
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
        ROOT / "reports/policy-document-ingestion/draft-summary.json",
    )
    case = {**query_scope(source_ids, draft), "query": query}
    local = embedder()
    if body["encoder"] != {"model": local.model, "revision": local.revision, "dimension": local.dimension}:
        raise ValueError("document/query encoder identity differs")
    vector = local.embed([query])[0]
    bundle = (
        read(ROOT / "tmp/policy-documents-v1/representation-v1.json")["variants"]["title_path"]
        if strategy == "path-rrf"
        else body
    )
    ranked = rank(case, bundle, "dense", vector)
    if strategy != "dense":
        ranked = rrf(ranked, rank(case, body, "bm25"), 20, 60)
    selected = select_contexts(case, [c for c, _ in ranked[:top_k]], bundle, catalog(draft), 8000)
    full = make_packet(selected, bundle, catalog(draft), "deduplicated")
    packet, ledger = compact(full)
    ledger_sha = digest(canonical_json(ledger).encode())
    for reference in [b["ref"] for b in packet["blocks"]] + [c["ref"] for c in packet["contexts"]]:
        resolve(
            packet,
            ledger,
            reference,
            ledger_sha256=ledger_sha,
            subject=case["subject"],
            scope={(s["source_id"], s["raw_sha256"]) for s in case["scope"]},
        )
    return {
        "kind": "EXTERNAL_DOCUMENT_EVIDENCE_NOT_MERCHANT_POLICY",
        "reference_only": True,
        "query": query,
        "strategy": strategy,
        "subject": case["subject"],
        "scope": case["scope"],
        "top_k": top_k,
        "new_chat_api_calls": 0,
        "production_writes": 0,
        "semantic_answerability_evaluated": False,
        "experimental_ranking": strategy != "dense",
        "packet": packet,
        "packet_tokens": len(load_tokenizer().encode(canonical_json(packet)).ids),
        "ledger": ledger,
        "ledger_sha256": ledger_sha,
        "selection_sha256": selected.fingerprint,
        "blocked_contexts": list(selected.blocked_ids),
        "hits": [{"child_id": c["id"], "source_id": c["source_id"], "score": score} for c, score in ranked[:top_k]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--strategy", choices=("dense", "body-rrf", "path-rrf"), default="dense")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("source search outputs cannot be overwritten")
    if not args.output.resolve().is_relative_to((ROOT / "tmp").resolve()):
        raise ValueError("full source text/ledger output must stay in ignored local tmp")
    result = search(args.query, args.source, args.strategy, args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps({k: result[k] for k in ("kind", "strategy", "subject", "packet_tokens", "hits")}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
