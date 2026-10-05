"""Traceable external questions and current live queries; no invented per-query Gold."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from scripts.evaluation.dataset import ALIGNED_DATA, check_input, digest, read, validate  # noqa: E402
from scripts.evaluation.environment import environment  # noqa: E402

EXTERNAL = ROOT / "evals/external-faq-v1"


def external_queries(directory=EXTERNAL):
    manifest = read("manifest.json", directory)
    if manifest["base_manifest_sha256"] != digest(ALIGNED_DATA / "manifest.json"):
        raise ValueError("External corpus base differs")
    if set(manifest["files"]) != {"sources.json", "queries.json"}:
        raise ValueError("External corpus must freeze sources and questions")
    for name, expected in manifest["files"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or digest(path) != expected:
            raise ValueError("External corpus frozen hash differs")
    queries, sources = read("queries.json", directory), read("sources.json", directory)
    check_input(queries)
    check_input(sources)
    by_id = {s["id"]: s for s in sources}
    if not sources or len(by_id) != len(sources) or len({q["id"] for q in queries}) != len(queries):
        raise ValueError("External corpus empty or duplicate ids")
    if (len({s["url"] for s in sources}) != len(sources)
            or len({s["question_sha256"] for s in sources}) != len(sources)):
        raise ValueError("Repeated question/page is not an independent source")
    bundles = {b["bundle_id"]: b for b in read("policies/bundles.json", ALIGNED_DATA)}
    bindings = set()
    for query in queries:
        source = by_id.get(query["source_id"])
        bundle = bundles.get(query["bundle_id"])
        if source is None or bundle is None or query["merchant_id"] != bundle["merchant_id"]:
            raise ValueError("External source or subject differs")
        url = urlparse(source["url"])
        if (source["kind"] != "OFFICIAL_FAQ" or url.scheme != "https" or url.hostname != "help.jd.com"
                or not source["retrieved_at"] or query["query"] != source["question"]
                or source["question_sha256"] != hashlib.sha256(query["query"].encode()).hexdigest()):
            raise ValueError("External question provenance differs")
        binding = query["source_id"], query["bundle_id"]
        if binding in bindings:
            raise ValueError("Duplicate source/bundle diagnostic")
        bindings.add(binding)
    expected_bindings = {(source, bundle) for source in by_id for bundle in manifest["scope_bundle_ids"]}
    if (not queries or bindings != expected_bindings or manifest["unique_questions"] != len(sources)
            or manifest["scoped_query_count"] != len(queries)):
        raise ValueError("External source/query denominator differs")
    return queries, sources


def current_live_queries(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    if (report.get("mode") != "live" or report.get("synthetic") is not True
            or report.get("manifest_hash") != digest(ALIGNED_DATA / "manifest.json")
            or report.get("state") != "FINISHED"):
        raise ValueError("Expected finished live report on this frozen corpus")
    production = {name: sha for name, sha in report.get("code_hashes", {}).items()
                  if name.startswith(("agent/src/resolveflow/harness/", "agent/src/resolveflow/policies/",
                                      "agent/src/resolveflow/tools/"))}
    expected = {p.relative_to(ROOT).as_posix() for area in ("harness", "policies", "tools")
                for p in (ROOT / "agent/src/resolveflow" / area).glob("*.py")}
    if set(production) != expected or any(digest(ROOT / name) != sha for name, sha in production.items()):
        raise ValueError("Live production code fingerprint differs")
    cases = {c["id"]: c for c in read("agent/cases.json", ALIGNED_DATA)}
    entries = report["results"]
    if not entries or len({e["id"] for e in entries}) != len(entries):
        raise ValueError("Live report empty or duplicate cases")
    queries = []
    for entry in entries:
        source = cases.get(entry["id"])
        if source is None:
            raise ValueError("Unknown frozen case")
        for turn, request in enumerate(entry.get("requests", []), 1):
            action = request.get("decision") or {}
            if action.get("kind") != "SEARCH_POLICY":
                continue
            query = action.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("Live search decision has invalid query")
            queries.append({"id": f"LIVE:{entry['id']}:{turn}", "split": "current_live_query_probe",
                "query": query, "merchant_id": source["scope"]["merchant_id"], "bundle_id": source["bundle_id"],
                "case_id": entry["id"], "turn": turn, "original_top_k": action.get("arguments", {}).get("top_k"),
                "request_failed": "error" in request, "source_report": path.as_posix(),
                "source_sha256": digest(path)})
    if not queries:
        raise ValueError("Zero live queries is not a successful diagnostic")
    check_input(queries)
    return queries


def probe_summary(rows):
    groups = {}
    for row in rows:
        groups.setdefault(f"{row['split']}/{row['path']}", []).append(row)
    return {key: {"n": len(values), "unscored_n": len(values), "accuracy": None,
        "errors": sum("error" in v for v in values),
        "filter_violations": sum(v.get("filter_violations", 0) for v in values),
        "mean_returned_chars_at_2": round(sum(v.get("returned_chars_at_2", 0) for v in values) / len(values), 2)}
        for key, values in groups.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.resolve() == args.review_output.resolve() or any(
            p.exists() for p in (args.output, args.review_output)):
        parser.error("Report and review must have distinct new paths")
    validate(ALIGNED_DATA)
    external, sources = external_queries()
    queries = external + current_live_queries(args.live_report)
    bundles = {b["bundle_id"]: b for b in read("policies/bundles.json", ALIGNED_DATA)}
    report = {"mode": "unlabelled_query_diagnostic", "scored": False,
        "manifest_hash": digest(ALIGNED_DATA / "manifest.json"),
        "external_manifest_sha256": digest(EXTERNAL / "manifest.json"),
        "live_report_sha256": digest(args.live_report), "script_sha256": digest(Path(__file__)),
        "sources": sources, "unique_external_questions": len(sources),
        "external_scope_queries": len(external), "live_queries": len(queries) - len(external),
        "limits": ["FAQ is platform-authored, not customer logs; project policy is synthetic.",
                   "Live query decisions are model-generated, not necessarily valid or executed tool calls.",
                   "Offline top5 differs from original top_k; no intermediate query Gold is inferred.",
                   "Similarity and returned candidates do not imply applicability or refund authorization."],
        "results": []}
    with environment(dataset=ALIGNED_DATA) as (_, index, encoder, pins):
        report["embedding"] = {"model": encoder.model, "revision": encoder.revision, "dimension": encoder.dimension}
        for query in queries:
            pin, bundle = pins[query["bundle_id"]], bundles[query["bundle_id"]]
            for path in ("dense", "bm25"):
                started = time.perf_counter()
                row = {**query, "path": path, "diagnostic_top_k": 5, "scored": False}
                try:
                    hits = index.search(**{k: pin[k] for k in ("merchant_id", "bundle_ids", "manifest_hash")},
                                        query=query["query"], path=path, top_k=5, embedder=encoder)
                    row.update(hits=[asdict(h) for h in hits], filter_violations=sum(
                        h.bundle_id != query["bundle_id"] or h.merchant_id != query["merchant_id"]
                        or h.version != bundle["version"] or h.manifest_hash != pin["manifest_hash"] for h in hits),
                        returned_chars_at_2=sum(len(h.title) + len(h.text) for h in hits[:2]))
                except Exception as error:
                    row["error"] = f"{type(error).__name__}: {error}"
                row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
                report["results"].append(row)
    report["summary"] = probe_summary(report["results"])
    review = {"status": "PENDING", "reviewer_kind": "HUMAN", "reviewer": "", "reviewed_at": "",
        "corpus_manifest_sha256": report["manifest_hash"], "live_report_sha256": report["live_report_sha256"],
        "external_manifest_sha256": report["external_manifest_sha256"],
        "instructions": "逐query判断项目条款相关性；must_rules=null为待标注，[]仅用于确认无适用条款。"
                        "先看问法及完整条款再看候选，不能抄最终工单Gold，不写京东政策或授权。",
        "policy_bundles": list(bundles.values()),
        "queries": [{**q, "must_rules": None, "notes": ""} for q in queries]}
    for output, content in ((args.output, report), (args.review_output, review)):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return int(any("error" in r or r.get("filter_violations") for r in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
