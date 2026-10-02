"""Read-only index projection; no model, embeddings, generation writes or source text."""

from resolveflow.runtime.db import Database


def policy_index_status(database: Database, merchant: str, bundle: str, manifest_hash: str) -> dict:
    with database.connection() as connection:
        row = connection.execute(
            """SELECT generation_id,status,chunk_count,built_at FROM policy_index_generation
               WHERE merchant_id=%s AND bundle_id=%s AND manifest_hash=%s
               ORDER BY (status='READY') DESC,built_at DESC,generation_id LIMIT 1""",
            (merchant, bundle, manifest_hash),
        ).fetchone()
    return {
        "bundle_id": bundle,
        "manifest_hash": manifest_hash,
        "status": row["status"] if row else "MISSING",
        "generation_id": row["generation_id"] if row else None,
        "chunk_count": row["chunk_count"] if row else None,
        "built_at": row["built_at"].isoformat() if row else None,
    }
