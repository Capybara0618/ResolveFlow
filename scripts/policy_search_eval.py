"""The C07.1 retrieval evaluation: Recall@5, ranking quality, version/merchant correctness, and cost.

``docs/policy-rag.md:29-31`` asks for exactly this and for one thing more, which is the reason this file is
written the way it is: **dense 不优于 BM25 也要如实报告**. So the report prints every query's ranking for both
paths rather than only the aggregates — a summary table that showed "dense 0.85, BM25 0.80" while hiding which
queries dense lost would be a result nobody could check. It also prints the two things Recall@5 alone cannot
see: **top-1** (did it rank the right rule first) and **MRR@5** (how high the right rule was). Recall@5 over a
pinned bundle of a few rules is close to always 1, which is a true and uninteresting fact; the interesting one
is whether the ranking separates the near-miss families, and that only shows up in top-1.

**What is measured, and against what.** Each query is pinned to its gold bundle and that bundle's
``manifest_hash`` — the same gate a real run goes through — so the evaluation cannot "succeed" by searching a
bundle the query was not pinned to. Version and merchant correctness are then properties of the returned hits
rather than of the harness: the script asserts every hit came from the pinned bundle and version, and counts a
violation as an error. That is what makes the merchant/version filters measured rather than assumed.

**Cost.** Load time, per-query latency (median and p95) and errors are reported per path. The model's
dimension, revision, licence and disk footprint are recorded in the sibling ``embedding-probe.txt``; this
report repeats the identifier so a number here can be traced to the model that produced it.

Usage (from the repository root; the database must hold the indexed bundles — see
``scripts/policy_index_ingest.py``)::

    & agent\\.venv\\Scripts\\python.exe scripts\\policy_search_eval.py --report reports/c071-policy-index/retrieval-eval.txt
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from resolveflow.policies import (  # noqa: E402 - the path insert above is the point
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_REVISION,
    PolicyIndex,
    PolicyIndexNotReadyError,
    embedder,
)
from resolveflow.runtime.db import Database, default_dsn  # noqa: E402

DEFAULT_QUERIES = REPO_ROOT / "evals" / "policy" / "retrieval-queries.json"

#: The paths compared. Named rather than booleans because the report has to say which one produced a number.
PATHS = ("dense", "bm25")


@dataclass(frozen=True, slots=True)
class Query:
    query_id: str
    split: str
    family: str
    text: str
    gold_bundle: str
    gold_rule: str

    @property
    def gold(self) -> str:
        return f"{self.gold_bundle}/{self.gold_rule}"


def load_queries(path: Path) -> list[Query]:
    document = json.loads(path.read_text(encoding="utf-8"))
    queries: list[Query] = []
    for entry in document["queries"]:
        bundle, rule = entry["gold"].split("/", 1)
        queries.append(
            Query(
                query_id=entry["id"],
                split=entry["split"],
                family=entry["family"],
                text=entry["query"],
                gold_bundle=bundle,
                gold_rule=rule,
            )
        )
    ids = [query.query_id for query in queries]
    if len(set(ids)) != len(ids):
        raise SystemExit("the query set names an id twice")
    return queries


def check_the_split_is_family_separated(queries: list[Query]) -> list[str]:
    """The spec's 按语义家族分离, checked rather than declared.

    Compared by **exact family name**, and the check is deliberately naive: a family that appears in both splits
    is reported whether or not the id looks like a hedge, because a reader who sees this warning in a retrieval
    report cannot tell a real overlap from an intended one. The first version of this function stripped a
    ``_near_miss`` suffix and reported four families as shared — it was describing its own leniency rather than
    the split, which is the failure mode this check exists to prevent.
    """
    families: dict[str, set[str]] = {}
    for query in queries:
        families.setdefault(query.family, set()).add(query.split)
    return sorted(
        f"{family} appears in both splits ({sorted(splits)})"
        for family, splits in families.items()
        if len(splits) > 1
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES))
    parser.add_argument("--dsn", default=default_dsn())
    parser.add_argument("--schema", default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--report", default=None)
    parser.add_argument(
        "--skip-dense",
        action="store_true",
        help="report BM25 only; the report then says dense was not run rather than leaving it blank",
    )
    arguments = parser.parse_args(argv)

    queries = load_queries(Path(arguments.queries))
    separation = check_the_split_is_family_separated(queries)
    by_split: dict[str, int] = {}
    for query in queries:
        by_split[query.split] = by_split.get(query.split, 0) + 1

    database = Database(arguments.dsn, schema=arguments.schema) if arguments.schema else Database(arguments.dsn)
    index = PolicyIndex(database)

    lines: list[str] = []
    add = lines.append
    add("C07.1 policy retrieval evaluation")
    add(f"  started     : {dt.datetime.now(dt.UTC).isoformat()}")
    add(f"  queries     : {len(queries)} ({', '.join(f'{k}={v}' for k, v in sorted(by_split.items()))})")
    add(f"  query file  : {arguments.queries}")
    add(f"  database    : {arguments.dsn}" + (f" schema {arguments.schema}" if arguments.schema else ""))
    add(f"  top_k       : {arguments.top_k}")
    add(f"  dense model : {EMBEDDING_MODEL} @ {EMBEDDING_REVISION} ({EMBEDDING_DIMENSION} dims, see embedding-probe.txt)")
    if separation:
        add(f"  SPLIT WARNING: {separation} — the dev/test split shares a semantic family")
    else:
        add("  split       : families do not overlap between dev and test")

    # Every pinned bundle has to be READY before anything is scored, and the check is done here rather than per
    # query so an unindexed bundle is one clear failure instead of twenty identical ones.
    pinned: dict[str, str] = {}
    for bundle_id in sorted({query.gold_bundle for query in queries}):
        row = database.connection()
        with row as connection:
            found = connection.execute(
                "SELECT manifest_hash FROM policy_index_generation WHERE bundle_id = %s AND status = 'READY' "
                "ORDER BY built_at DESC LIMIT 1",
                (bundle_id,),
            ).fetchone()
        if found is None:
            add(f"  REFUSED: {bundle_id} has no READY generation; run scripts/policy_index_ingest.py first")
            _emit(lines, arguments.report)
            return 1
        pinned[bundle_id] = str(found["manifest_hash"])
        add(f"  pinned      : {bundle_id} @ {pinned[bundle_id][:16]}…")

    the_embedder = None if arguments.skip_dense else embedder()
    if the_embedder is not None:
        started = time.time()
        the_embedder.embed(["预热"])
        add(f"  dense load  : {time.time() - started:.2f}s (model load + one warm-up encode)")

    results: dict[str, dict[str, list[dict[str, Any]]]] = {path: {} for path in PATHS}
    failures: list[str] = []
    for path in PATHS:
        if path == "dense" and arguments.skip_dense:
            continue
        for split in sorted(by_split):
            scored: list[dict[str, Any]] = []
            for query in [item for item in queries if item.split == split]:
                scored.append(_score(index, query, path, pinned, arguments.top_k, the_embedder, failures))
            results[path][split] = scored

    for path in PATHS:
        if not results[path]:
            add(f"\n== {path} == NOT RUN" + (" (--skip-dense)" if arguments.skip_dense else ""))
            continue
        add(f"\n== {path} ==")
        for split in sorted(results[path]):
            add(_summarise(path, split, results[path][split]))
        add(_summarise(path, "all", [item for split in results[path].values() for item in split]))

    add("\n== per query ==")
    for query in queries:
        add(f"\n{query.query_id} [{query.split}/{query.family}] {query.text}")
        add(f"    gold {query.gold}")
        for path in PATHS:
            scored = results[path].get(query.split)
            if scored is None:
                add(f"    {path:<6} not run")
                continue
            entry = next(item for item in scored if item["id"] == query.query_id)
            ranked = " > ".join(entry["top"]) if entry["top"] else "(no hits)"
            mark = "OK " if entry["top1_correct"] else ("r@5" if entry["recall_at_5"] else "MISS")
            add(f"    {path:<6} {mark:<4} rank={entry['gold_rank']} top={ranked}")

    add("\n== errors ==")
    if failures:
        for failure in failures:
            add(f"  {failure}")
    else:
        add("  none")

    add("\n== reading this report ==")
    add("  Recall@5 over a pinned bundle of <=7 rules is close to always 1; top-1 and MRR@5 are the numbers that")
    add("  separate the paths. Where dense loses to BM25, the per-query section above names the query — that is")
    add("  the finding, not a footnote (docs/policy-rag.md:31: dense 不优于 BM25 也要如实报告).")
    add("  version/merchant correctness is counted as violations: every hit must come from the pinned bundle and")
    add("  version. A non-zero count there invalidates the run rather than lowering a score.")
    add("  This corpus is synthetic and small; no generalisation beyond it is claimed (docs/policy-rag.md:31).")

    lines.append(f"\nfinished at {dt.datetime.now(dt.UTC).isoformat()}")
    _emit(lines, arguments.report)
    return 1 if failures else 0


def _score(
    index: PolicyIndex,
    query: Query,
    path: str,
    pinned: dict[str, str],
    top_k: int,
    the_embedder: Any,
    failures: list[str],
) -> dict[str, Any]:
    """One query on one path: its ranked rule ids, whether the gold rule was found, and how long it took."""
    # The run's merchant comes from the indexed generation, exactly as a dispatched run's would come from its
    # pinned manifest: the evaluation does not get to assert a merchant the index disagrees with.
    merchant = _merchant_for(index, query.gold_bundle)
    entry: dict[str, Any] = {
        "id": query.query_id,
        "gold": query.gold,
        "top": [],
        "gold_rank": None,
        "recall_at_5": False,
        "top1_correct": False,
        "elapsed_ms": None,
        "violations": 0,
    }
    started = time.perf_counter()
    try:
        hits = index.search(
            merchant_id=merchant,
            bundle_ids=[query.gold_bundle],
            manifest_hash=pinned[query.gold_bundle],
            query=query.text,
            path=path,  # type: ignore[arg-type]
            top_k=top_k,
            embedder=the_embedder if path == "dense" else None,
        )
    except Exception as failure:  # noqa: BLE001 - an error is a result here, and the report lists it
        entry["elapsed_ms"] = (time.perf_counter() - started) * 1000
        entry["error"] = f"{type(failure).__name__}: {failure}"
        failures.append(f"{query.query_id}/{path}: {entry['error']}")
        return entry

    entry["elapsed_ms"] = (time.perf_counter() - started) * 1000
    entry["top"] = [f"{hit.bundle_id}/{hit.rule_id}" for hit in hits]
    for hit in hits:
        # The filters are measured, not assumed: any hit from outside the pinned bundle or a different version
        # is a violation that invalidates the query.
        if hit.bundle_id != query.gold_bundle or hit.manifest_hash != pinned[query.gold_bundle]:
            entry["violations"] += 1
    entry["recall_at_5"] = query.gold in entry["top"]
    entry["top1_correct"] = bool(entry["top"]) and entry["top"][0] == query.gold
    entry["gold_rank"] = entry["top"].index(query.gold) + 1 if query.gold in entry["top"] else None
    if entry["violations"]:
        failures.append(
            f"{query.query_id}/{path}: {entry['violations']} hit(s) outside the pinned bundle/version"
        )
    return entry


def _merchant_for(index: PolicyIndex, bundle_id: str) -> str:
    generations = index.generations(bundle_id)
    if not generations:
        raise SystemExit(f"{bundle_id} is not indexed at all; run scripts/policy_index_ingest.py")
    return generations[0].merchant_id


def _summarise(path: str, split: str, scored: list[dict[str, Any]]) -> str:
    if not scored:
        return f"  {split:<5} (nothing scored)"
    answered = [entry for entry in scored if entry.get("error") is None]
    latencies = [entry["elapsed_ms"] for entry in answered if entry["elapsed_ms"] is not None]
    recall = sum(1 for entry in answered if entry["recall_at_5"])
    top1 = sum(1 for entry in answered if entry["top1_correct"])
    reciprocal = sum(1.0 / entry["gold_rank"] for entry in answered if entry["gold_rank"])
    violations = sum(entry["violations"] for entry in answered)
    median = statistics.median(latencies) if latencies else 0.0
    p95 = (sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0.0)
    return (
        f"  {split:<5} n={len(scored):<3} answered={len(answered):<3} "
        f"recall@5={recall / max(1, len(answered)):.3f} top1={top1 / max(1, len(answered)):.3f} "
        f"mrr@5={reciprocal / max(1, len(answered)):.3f} "
        f"median={median:.0f}ms p95={p95:.0f}ms errors={len(scored) - len(answered)} "
        f"filter_violations={violations}"
    )


def _emit(lines: list[str], report: str | None) -> None:
    document = "\n".join(lines)
    print(document)
    if report:
        path = Path(report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
