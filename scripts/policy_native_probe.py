"""Real BGE/PostgreSQL length and citation probe, not a semantic accuracy benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

from resolveflow.policies import PolicyIndex, ServedBundle
from resolveflow.policies.retrieval import embedder
from resolveflow.policies.segments import encoder_tokens
from resolveflow.runtime.db import Database, create_schema, default_dsn, drop_schema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("probe results are immutable")
    encoder = embedder()
    text = (
        "适用范围及办理条件需要核对商品与订单信息。" * 70
        + "例外：已经退款不得再次退款，支付状态不明确时不得执行退款。"
    )
    bundle = ServedBundle(
        "synthetic-length-probe", "synthetic-probe-merchant", "v1", "a" * 64, 1,
        [{"rule_id": "LENGTH", "title": "长度工程探针", "text": text}],
    )
    dsn, schema = default_dsn(), "probe_" + uuid.uuid4().hex[:16]
    create_schema(dsn, schema)
    database = Database(dsn, schema=schema)
    try:
        migrations = database.migrations()
        index = PolicyIndex(database)
        build = index.build(bundle, embedder=encoder)
        generation = index.generation_for(bundle.bundle_id, bundle.manifest_hash)
        hits = index.search(
            merchant_id=bundle.merchant_id, bundle_ids=[bundle.bundle_id], manifest_hash=bundle.manifest_hash,
            query="已经退款还能再次申请吗？", path="dense", embedder=encoder,
            generation_ids={bundle.bundle_id: build.generation_id},
        )
        with database.connection() as connection:
            children = connection.execute(
                "SELECT text,encoder_tokens FROM policy_index_child WHERE generation_id=%s ORDER BY start_offset",
                (build.generation_id,),
            ).fetchall()
            version = connection.execute("SELECT version() AS version").fetchone()["version"]
            db_settings = {k: connection.execute("SHOW " + k).fetchone()[k] for k in ("fsync", "synchronous_commit")}
        actual_tokens = [encoder_tokens(row["text"], encoder._encoder().tokenizer) for row in children]
        assert len(children) > 1 and max(actual_tokens) <= 384
        assert [r["encoder_tokens"] for r in children] == actual_tokens
        assert "".join(r["text"] for r in children) == text
        assert len(hits) == 1 and hits[0].text == text
        assert hits[0].content_hash == bundle.chunks()[0].content_hash
        try:
            encoder.embed(["超长查询" * 600])
        except ValueError as error:
            oversized_query = "no truncation" in str(error)
        else:
            oversized_query = False
        assert oversized_query
        report = {
            "kind": "SYNTHETIC_LENGTH_ENGINEERING_PROBE", "semantic_accuracy": None,
            "postgres_version": version, "temporary_schema_cleaned": True,
            "isolated_database_settings": db_settings,
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "migrations": migrations, "model": encoder.model, "revision": encoder.revision,
            "dimension": encoder.dimension, "encoder_window": encoder._encoder().max_seq_length,
            "full_rule_encoder_tokens": encoder_tokens(text, encoder._encoder().tokenizer),
            "retrieval_layout": generation.retrieval_layout,
            "children": len(children), "min_child_tokens": min(actual_tokens), "max_child_tokens": max(actual_tokens),
            "whole_rule_returned": True, "trailing_exception_preserved": True,
            "authority_citation_hash": hits[0].content_hash, "oversized_query_rejected": oversized_query,
        }
    finally:
        database.close()
        drop_schema(dsn, schema)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: report[k] for k in ("children", "max_child_tokens", "whole_rule_returned")}))


if __name__ == "__main__":
    main()
