"""A bounded read of immutable tool observations, without model requests or SDK state."""
from __future__ import annotations

import json
from typing import Any

from resolveflow.runtime.db import Database
from resolveflow.runtime.runs import RunNotFoundError, _require_uuid

MAX_OBSERVATIONS = 40
MAX_BODY_BYTES = 32768


def review_sources(database: Database, run_id: str, *, case_id: str, input_revision: int,
                   merchant_id: str, customer_id: str) -> dict[str, Any]:
    _require_uuid("run_id", run_id, not_found=True)
    _require_uuid("case_id", case_id, not_found=True)
    with database.connection() as connection:
        row = connection.execute(
            "SELECT run_id,case_id,input_revision,status FROM agent_run WHERE run_id=%s AND case_id=%s "
            "AND input_revision=%s AND merchant_id=%s AND customer_id=%s",
            (run_id, case_id, input_revision, merchant_id, customer_id),
        ).fetchone()
        if row is None:
            raise RunNotFoundError("no reviewable run for this case revision")
        entries = connection.execute(
            "SELECT call_id,observation FROM agent_tool_call WHERE run_id=%s AND observation IS NOT NULL "
            "ORDER BY observation->>'observed_at',call_id LIMIT %s", (run_id, MAX_OBSERVATIONS + 1),
        ).fetchall()
        frozen = connection.execute("SELECT manifest FROM agent_run_model_budget WHERE run_id=%s", (run_id,)).fetchone()
    # Expose only the declared model identity, never request bodies, credentials, or SDK conversations.
    model = ((frozen or {}).get("manifest") or {}).get("model") or {}
    observations = []
    for entry in entries[:MAX_OBSERVATIONS]:
        value = entry["observation"]
        if not isinstance(value, dict):
            continue
        item = {name: value.get(name) for name in (
            "observation_id", "tool_name", "source_type", "source_ref", "source_version", "content_hash",
            "observed_at")}
        result = value.get("result")
        omitted = len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_BODY_BYTES
        item.update(call_id=entry["call_id"], result=None if omitted else result, body_omitted=omitted,
                    error_code=(value.get("error") or {}).get("code"))
        observations.append(item)
    return {"run_id": str(row["run_id"]), "case_id": str(row["case_id"]), "input_revision": row["input_revision"],
            "status": row["status"], "model_provider": model.get("provider"), "model_id": model.get("model_id"),
            "observations": observations, "truncated": len(entries) > MAX_OBSERVATIONS}
