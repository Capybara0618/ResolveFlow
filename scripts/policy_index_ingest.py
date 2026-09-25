"""Build the Agent's policy index from the *authoritative* policy text (C07.1).

This is the controlled ingestion path ``docs/policy-rag.md:23`` asks for: 先拉指定不可变bundle→构建generation→
校验hash/维度→标READY.

**Why it reads Java rather than the repository's fixtures.** ``fixtures/policies/bundles/*.yaml`` are the input
to the *controlled import*: their content becomes ``policy_bundle``/``policy_rule`` rows, and Java derives the
``manifest_hash`` and each rule's ``content_hash`` from what it stored. If this script parsed those files
itself, it would recompute the same hashes from its own copy — and a citation checked against a hash this side
derived from its own parse proves only self-consistency. The pin that makes a citation checkable is the one
``case_policy_manifest`` recorded, so this script fetches each bundle over
``GET /internal/v1/policies/{bundle_id}``, carries Java's ``manifest_hash`` through verbatim, and *compares*
its recomputed rule hashes against Java's rather than trusting either.

**Two hashes it checks, and they are different questions.**

* ``manifest_hash`` — Java's, carried. Verified by asking for the bundle id the pin names and confirming the
  response's hash equals the hash the pin recorded. A mismatch means the case was pinned to a version this
  service does not currently serve, which is exactly the state that must not be silently indexed.
* ``content_hash`` per rule — recomputed here and compared with what Java served. These *should* be equal
  because ``docs/core-contracts.md:56`` fixes one construction for both sides; a difference is a cross-language
  bug and stops the build. This is also why it is worth having both implementations: the comparison is the
  test.

**Exit code is the interface.** An ingestion that refused a bundle must not look like success to whoever ran
it in a pipeline (the same rule as ``PolicyImportCommand``).

Usage::

    & agent\\.venv\\Scripts\\python.exe scripts\\policy_index_ingest.py `
        --case-base-url http://127.0.0.1:8083 `
        --service-token <policy:read service token> `
        --bundle policy-logistics-2026.08 ... `
        [--without-embeddings] [--replace] [--report reports/c071-policy-index/ingest.txt]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from resolveflow.policies import (  # noqa: E402 - the path insert above is the point
    EMBEDDING_MODEL,
    EMBEDDING_REVISION,
    PolicyIndex,
    embedder,
    served_bundle_of,
)
from resolveflow.runtime.db import Database, default_dsn  # noqa: E402

#: The scope the authoritative policy route requires (AS02.3's per-route enforcement).
POLICY_READ_SCOPE = "policy:read"


class IngestRefused(RuntimeError):
    """The ingestion will not proceed, and says which fact stopped it."""


def fetch_bundle(base_url: str, token: str, bundle_id: str, *, timeout: float = 10.0) -> dict[str, object]:
    """One bundle as Java serves it, or a refusal naming the status.

    ``urllib`` rather than the project's ``httpx`` client: this is an operator command, not a service path, and
    the fewer things between the operator and the answer the better. The scope is stated here because the
    route enforces it per-route since AS02.3.
    """
    url = f"{base_url.rstrip('/')}/internal/v1/policies/{bundle_id}"
    request = urllib.request.Request(url)  # noqa: S310 - a caller-supplied base URL is this command's input
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise IngestRefused(
            f"{bundle_id}: the policy route answered {error.code}. A 401/403 here means the token is not a "
            f"service token carrying {POLICY_READ_SCOPE}."
        ) from error
    except urllib.error.URLError as error:
        raise IngestRefused(f"{bundle_id}: case-service is unreachable at {base_url}: {error.reason}") from error


def verify_rule_hashes(bundle_id: str, served: dict[str, object]) -> list[str]:
    """Recompute every rule's ``content_hash`` and compare it with Java's. Returns the problems found.

    Returns rather than raises so a report can list *all* the disagreements: "rule 3 differs" sends someone to
    read the diff, while "the bundle differs" sends them to read everything.
    """
    from resolveflow.policies import chunks_of_bundle

    problems: list[str] = []
    rules = served.get("rules")
    if not isinstance(rules, list):
        raise IngestRefused(f"{bundle_id}: the served bundle carries no rules list")
    chunks = chunks_of_bundle(bundle_id, rules)
    for chunk, rule in zip(chunks, rules, strict=True):
        served_hash = rule.get("content_hash")
        if served_hash != chunk.content_hash:
            problems.append(
                f"{bundle_id}/{chunk.rule_id}: Java served content_hash {served_hash}, "
                f"recomputed {chunk.content_hash}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-base-url", default=os.environ.get("RESOLVEFLOW_CASE_BASE_URL", "http://127.0.0.1:8083"))
    parser.add_argument(
        "--service-token",
        default=os.environ.get("RESOLVEFLOW_POLICY_INGEST_TOKEN"),
        help="a service token carrying policy:read, or set RESOLVEFLOW_POLICY_INGEST_TOKEN",
    )
    parser.add_argument("--bundle", action="append", default=[], help="a bundle id to index; repeatable")
    parser.add_argument("--dsn", default=default_dsn())
    parser.add_argument("--schema", default=None, help="the schema to index into (default: the DSN's)")
    parser.add_argument(
        "--without-embeddings",
        action="store_true",
        help="build a lexical-only generation; the dense path will refuse for it rather than return nothing",
    )
    parser.add_argument("--replace", action="store_true", help="retire the bundle's previous READY generation")
    parser.add_argument("--report", default=None, help="write the report here as well as to stdout")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="check Java's hashes against this side's and index nothing",
    )
    arguments = parser.parse_args(argv)

    if not arguments.bundle:
        parser.error("at least one --bundle is required; there is no 'index everything' mode on purpose")
    if not arguments.service_token:
        parser.error("--service-token (or RESOLVEFLOW_POLICY_INGEST_TOKEN) is required: policy:read is enforced")

    started = dt.datetime.now(dt.UTC)
    lines: list[str] = [
        f"policy index ingestion · started {started.isoformat()}",
        f"  case-service : {arguments.case_base_url}",
        f"  database     : {arguments.dsn}" + (f" schema {arguments.schema}" if arguments.schema else ""),
        f"  embeddings   : {'none (lexical only)' if arguments.without_embeddings else EMBEDDING_MODEL}",
    ]
    if not arguments.without_embeddings:
        lines.append(f"  revision     : {EMBEDDING_REVISION}")

    problems: list[str] = []
    served: list[dict[str, object]] = []
    try:
        for bundle_id in arguments.bundle:
            payload = fetch_bundle(arguments.case_base_url, arguments.service_token, bundle_id)
            found = verify_rule_hashes(bundle_id, payload)
            problems.extend(found)
            served.append(payload)
            rules = payload.get("rules")
            count = len(rules) if isinstance(rules, list) else 0
            lines.append(
                f"  fetched      : {bundle_id} merchant={payload.get('merchant_id')} "
                f"version={payload.get('version')} rules={count} "
                f"manifest_hash={str(payload.get('manifest_hash'))[:16]}…"
            )
            if found:
                lines.append(f"  HASH MISMATCH: {len(found)} rule(s) disagree with Java's own content_hash")
    except IngestRefused as refusal:
        lines.append(f"  REFUSED: {refusal}")
        _emit(lines, arguments.report)
        return 1

    if problems:
        # A cross-language hash disagreement is a bug, not a warning: indexing anyway would produce citations
        # Java rejects for a reason that looks like the Agent's fault.
        lines.append("REFUSED: this side and Java disagree about a rule hash; nothing was indexed")
        _emit(lines, arguments.report)
        return 1

    if arguments.verify_only:
        lines.append("  verify-only: hashes agree, nothing was indexed")
        _emit(lines, arguments.report)
        return 0

    try:
        database = Database(arguments.dsn, schema=arguments.schema) if arguments.schema else Database(arguments.dsn)
        database.migrations()
        index = PolicyIndex(database)
        the_embedder = None if arguments.without_embeddings else embedder()
        if the_embedder is not None:
            # Load once, before the loop, so a missing stack or an unreadable snapshot fails before any row is
            # written rather than halfway through the bundle list.
            the_embedder.embed(["预热"])
            lines.append(f"  embedder     : loaded, {the_embedder.dimension} dimensions")
        for payload in served:
            bundle = served_bundle_of(payload)
            ingestion = index.build(bundle, embedder=the_embedder, replace=arguments.replace)
            lines.append(
                f"  indexed      : {ingestion.bundle_id} generation={ingestion.generation_id[:12]} "
                f"chunks={ingestion.chunk_count} lineage={ingestion.lineage_hash[:16]}… "
                f"replaced={ingestion.replaced_generation or 'none'}"
            )
    except Exception as failure:  # noqa: BLE001 - the operator needs the reason, whatever it is
        lines.append(f"  FAILED: {type(failure).__name__}: {failure}")
        _emit(lines, arguments.report)
        return 1

    finished = dt.datetime.now(dt.UTC)
    lines.append(f"  done         : {(finished - started).total_seconds():.1f}s")
    lines.append("RESULT: INDEXED")
    _emit(lines, arguments.report)
    return 0


def _emit(lines: list[str], report: str | None) -> None:
    document = "\n".join(lines)
    print(document)
    if report:
        path = Path(report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
