"""Source-grounded offline audit of frozen ranks; never invokes a model or changes retrieval."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from scripts.policy_chunks import load_draft, representations  # noqa: E402
from scripts.policy_context_packet_eval import catalog, make_packet, select_contexts  # noqa: E402
from scripts.policy_documents import digest  # noqa: E402
from scripts.policy_query_eval import ANSWERABILITY, coverage, load_inputs  # noqa: E402


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_atom(ref: dict, case: dict, index: dict) -> dict:
    matches = [(key, block) for key, block in index["blocks"].items() if key[2] == ref["block_id"]]
    if len(matches) != 1:
        raise ValueError("unknown or ambiguous source block")
    key, block = matches[0]
    scope = {(s["source_id"], s["raw_sha256"]) for s in case["scope"]}
    if key[:2] not in scope or block["subject"] != case["subject"]:
        raise ValueError("review evidence escaped query scope")
    rows = [r for r in index["representations"][key] if r.get("table_row") == ref.get("table_row")]
    if len(rows) != 1:
        raise ValueError("unknown or ambiguous table row")
    text = rows[0]["text"]
    return {
        "source_id": key[0], "raw_sha256": key[1], "block_id": key[2],
        "table_row": ref.get("table_row"), "text_range": [0, len(text)],
        "block_text_sha256": block["text_sha256"], "representation_sha256": digest(text.encode()),
        "locator": block["locator"],
    }


def validate_labels(review: dict, cases: list, index: dict) -> dict:
    rows = review["results"]
    if review["origin"] != "CODEX_REVIEW" or review["blind_review"] is not False:
        raise ValueError("review origin differs")
    if len(rows) != len(cases) or {r["id"] for r in rows} != {q["id"] for q in cases}:
        raise ValueError("review denominator or unique identity differs")
    labels = {r["id"]: r for r in rows}
    for case in cases:
        label = labels[case["id"]]
        state, sets = label["answerability"], label["evidence_sets"]
        if state not in ANSWERABILITY or not label["rationale"].strip() or not label["conclusion"].strip():
            raise ValueError("invalid reviewed judgment")
        if bool(sets) != (state in {"ANSWERABLE", "PARTIAL"}) or any(not group for group in sets):
            raise ValueError("answerability/evidence differs")
        for group in sets:
            atoms = [resolve_atom(ref, case, index) for ref in group]
            if len({(a["block_id"], a["table_row"]) for a in atoms}) != len(atoms):
                raise ValueError("duplicate sufficient evidence")
        for ref in label.get("boundary_refs", []):
            resolve_atom(ref, case, index)
    return labels


def sufficiently_covered(sets: list, predicate) -> bool | None:
    # Empty evidence is never awarded a perfect score; partial answers are aggregated separately.
    return any(all(predicate(atom) for atom in group) for group in sets) if sets else None


def validate_fragments(chunks: list, index: dict) -> None:
    for chunk in chunks:
        source = (chunk["source_id"], chunk["raw_sha256"])
        if index["sources"][source]["subject"] != chunk["subject"]:
            raise ValueError("child subject differs")
        for fragment in chunk["fragments"]:
            key = (*source, fragment["block_id"])
            block = index["blocks"][key]
            reps = [r for r in index["representations"][key]
                    if r.get("table_row") == fragment.get("table_row")]
            if len(reps) != 1 or block["text_sha256"] != fragment["block_text_sha256"]:
                raise ValueError("child source block/row differs")
            text = reps[0]["text"]
            start, end = fragment["text_range"]
            if (not 0 <= start < end <= len(text) or text[start:end] != fragment["text"]
                    or digest(text.encode()) != fragment["representation_sha256"]
                    or digest(fragment["text"].encode()) != fragment["fragment_sha256"]):
                raise ValueError("child fragment source span/hash differs")
        body = "\n\n".join(f["text"] for f in chunk["fragments"])
        if body != chunk["retrieval_text"] or digest(body.encode()) != chunk["content_sha256"]:
            raise ValueError("child retrieval body differs")


def summarize(rows: list) -> list:
    summaries = []
    for method in ("dense", "bm25"):
        for k in (2, 5):
            selected = [r for r in rows if r["method"] == method and r["k"] == k]
            answerable = [r for r in selected if r["answerability"] == "ANSWERABLE"]
            partial = [r for r in selected if r["answerability"] == "PARTIAL"]
            summaries.append({
                "method": method, "k": k, "all_queries": len(selected),
                "answerable_denominator": len(answerable),
                "direct_complete": sum(r["direct_sufficient"] for r in answerable),
                "expanded_complete": sum(r["expanded_sufficient"] for r in answerable),
                "expansion_only": sum(r["expanded_sufficient"] and not r["direct_sufficient"] for r in answerable),
                "direct_missing_ids": [r["query_id"] for r in answerable if not r["direct_sufficient"]],
                "expanded_missing_ids": [r["query_id"] for r in answerable if not r["expanded_sufficient"]],
                "partial_denominator": len(partial),
                "partial_direct_support": sum(r["direct_sufficient"] for r in partial),
                "partial_expanded_support": sum(r["expanded_sufficient"] for r in partial),
                "non_answerable_count": sum(r["answerability"] in {"NOT_IN_CORPUS", "NEEDS_CLARIFICATION"}
                                            for r in selected),
                "answerable_mean_exported_chars": round(sum(r["exported_chars"] for r in answerable)
                                                         / len(answerable), 2) if answerable else None,
                "answerable_mean_returned_scope_fraction": round(sum(r["returned_scope_fraction"]
                                                                      for r in answerable) / len(answerable), 4)
                if answerable else None,
                "answerable_entire_scope_returned": sum(r["returned_scope_fraction"] == 1 for r in answerable),
                "all_query_redundant_parent_slots": sum(r["redundant_parent_slots"] for r in selected),
                "non_answerable_all_zero_scores": sum(r["all_hit_scores_zero"] for r in selected
                                                       if r["answerability"] in {"NOT_IN_CORPUS",
                                                                                "NEEDS_CLARIFICATION"}),
            })
    return summaries


def audit(root: Path, manifest: dict) -> dict:
    for name, sha in manifest["inputs"].items():
        if digest((root / name).read_bytes()) != sha:
            raise ValueError(f"frozen input differs: {name}")
    paths = manifest["paths"]
    _, cases, _, bundle = load_inputs(root / paths["queries"], root / paths["children"], root / paths["draft"])
    draft = load_draft(root / paths["draft"], root / "reports/policy-document-ingestion/draft-summary.json")
    index = catalog(draft)
    index["representations"] = {(d["source_id"], d["raw_sha256"], b["id"]): representations(b)
                                for d in draft["documents"] for b in d["blocks"]}
    validate_fragments(bundle["chunks"], index)
    review = read(root / paths["labels"])
    labels = validate_labels(review, cases, index)
    baseline = read(root / paths["baseline"])
    packets = read(root / paths["packets"])
    old = {r["id"]: r for r in read(root / paths["old_judgments"])["results"]}
    if set(old) != set(labels):
        raise ValueError("old judge denominator differs")
    expected = {(q["id"], method) for q in cases for method in ("dense", "bm25")}
    if len(baseline["results"]) != len(expected) or {(r["query_id"], r["method"])
                                                  for r in baseline["results"]} != expected:
        raise ValueError("baseline identity differs")
    packet_rows = {(r["query_id"], r["method"], r["k"]): r for r in packets["results"]}
    if len(packet_rows) != 4 * len(cases) or len(packet_rows) != len(packets["results"]):
        raise ValueError("packet denominator differs")
    cases_by_id = {q["id"]: q for q in cases}
    chunks = {c["id"]: c for c in bundle["chunks"]}
    rows, rankings, evidence = [], [], {}
    for base in baseline["results"]:
        qid, method = base["query_id"], base["method"]
        case, label = cases_by_id[qid], labels[qid]
        sets = [[resolve_atom(ref, case, index) for ref in group] for group in label["evidence_sets"]]
        evidence[qid] = sets
        scope = {(s["source_id"], s["raw_sha256"]) for s in case["scope"]}
        scope_blocks = {key for key in index["blocks"] if key[:2] in scope}
        if base["at_k"]["2"]["hits"] != base["at_k"]["5"]["hits"][:2]:
            raise ValueError("top-k prefixes differ")
        if len(base["at_k"]["5"]["hits"]) != 5:
            raise ValueError("frozen top5 denominator differs")
        hits = []
        for hit in base["at_k"]["5"]["hits"]:
            chunk = chunks[hit["chunk_id"]]
            if (chunk["source_id"], chunk["raw_sha256"]) != (hit["source_id"], hit["raw_sha256"]):
                raise ValueError("hit source binding differs")
            hits.append(chunk)
        direct_first, expanded_first = None, None
        for count in range(1, len(hits) + 1):
            prefix = hits[:count]
            selection = select_contexts(case, prefix, bundle, index, baseline["context_chars"])
            keys = set(selection.block_keys)
            direct = sufficiently_covered(sets, lambda atom, prefix=prefix: coverage(prefix, atom))
            expanded = sufficiently_covered(sets, lambda atom, keys=keys: (atom["source_id"], atom["raw_sha256"],
                                                                         atom["block_id"]) in keys)
            if direct and direct_first is None:
                direct_first = count
            if expanded and expanded_first is None:
                expanded_first = count
            if count not in (2, 5):
                continue
            cached = packet_rows[(qid, method, count)]
            if (cached["selection_sha256"] != selection.fingerprint
                    or cached["context_ids"] != list(selection.context_ids)
                    or cached["blocked_context_ids"] != list(selection.blocked_ids)
                    or cached["packets"]["deduplicated"] != make_packet(selection, bundle, index, "deduplicated")
                    or base["at_k"][str(count)]["exported_chars"] != selection.exported_chars):
                raise ValueError("cached source packet/rank reconstruction differs")
            payloads = {(c["source_id"], c["raw_sha256"], bundle["contexts"][c["context_id"]]["text_sha256"])
                        for c in prefix}
            missing_sets = [[{"block_id": a["block_id"], "table_row": a["table_row"]}
                             for a in group if not coverage(prefix, a)] for group in sets]
            rows.append({
                "query_id": qid, "method": method, "k": count, "answerability": label["answerability"],
                "direct_sufficient": direct, "expanded_sufficient": expanded,
                "direct_missing_by_alternative": missing_sets,
                "expanded_missing_by_alternative": [[a["block_id"] for a in group
                                                       if (a["source_id"], a["raw_sha256"], a["block_id"])
                                                       not in keys] for group in sets],
                "exported_chars": selection.exported_chars, "returned_blocks": len(keys),
                "scope_blocks": len(scope_blocks), "returned_scope_fraction": len(keys) / len(scope_blocks),
                "redundant_parent_slots": count - len(payloads), "blocked_contexts": list(selection.blocked_ids),
                "selection_sha256": selection.fingerprint,
                "all_hit_scores_zero": all(h["score"] == 0 for h in base["at_k"][str(count)]["hits"]),
                "hits": [{**h, "context_id": c["context_id"],
                          "fragment_ranges": [{name: f.get(name) for name in ("block_id", "table_row", "text_range")}
                                              for f in c["fragments"]]}
                         for h, c in zip(base["at_k"][str(count)]["hits"], prefix, strict=True)],
            })
        rankings.append({"query_id": qid, "method": method, "first_direct_sufficient_within_top5": direct_first,
                         "first_expanded_sufficient_within_top5": expanded_first})
    return {
        "version": "rag-codex-source-audit-v1", "origin": "CODEX_REVIEW", "blind_review": False,
        "new_chat_api_calls": 0, "production_writes": 0, "retrieval_reexecuted": False,
        "reviewed_queries": len(cases), "answerability_counts": dict(Counter(r["answerability"]
                                                                            for r in labels.values())),
        "scope": "Frozen external-reference corpus; not merchant production accuracy or end-to-end Agent quality.",
        "non_answerable_answer_accuracy": None,
        "non_answerable_note": "Ranks always return top-k. No saved generated answers/abstention to score here.",
        "frozen_inputs": manifest["inputs"], "summaries": summarize(rows), "rankings": rankings,
        "evidence": evidence, "results": rows,
        "old_judge_comparison": [{
            "query_id": q["id"], "old_status": old[q["id"]]["status"],
            "old_answerability": (old[q["id"]].get("judgment") or {}).get("answerability"),
            "reviewed_answerability": labels[q["id"]]["answerability"],
            "old_protocol_errors": old[q["id"]].get("protocol_errors", []),
        } for q in cases],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "evals/rag-codex-review-v1/manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("audit outputs are immutable; choose a new output path")
    report = audit(ROOT, read(args.manifest))
    report["manifest_sha256"] = digest(args.manifest.read_bytes())
    report["runner_sha256"] = digest(Path(__file__).read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"answerability": report["answerability_counts"], "summaries": report["summaries"]}))


if __name__ == "__main__":
    main()
