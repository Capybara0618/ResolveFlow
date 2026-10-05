"""Read-only export of a finished, explicitly synthetic C09 trajectory."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Any

from resolveflow.harness.context import hash_document
from resolveflow.replay.pack import ReplayMiss, UnsupportedRecord, write_pack
from resolveflow.runtime.db import Database


def export_run(database: Database, run_id: str, destination: Path) -> None:
    """One repeatable snapshot; missing and unsupported rows are never filled in."""
    if destination.exists():
        raise FileExistsError(destination)
    with database.connection() as connection, connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        run = connection.execute("SELECT * FROM agent_run WHERE run_id=%s", (run_id,)).fetchone()
        if run is None:
            raise ReplayMiss("REPLAY_MISS: run not found")
        if not run["request_description"].startswith("SYNTHETIC_REPLAY:"):
            raise UnsupportedRecord("UNSUPPORTED_RECORD: explicit synthetic description required")
        frozen = connection.execute("SELECT * FROM agent_run_model_budget WHERE run_id=%s", (run_id,)).fetchone()
        models = connection.execute(
            "SELECT * FROM agent_model_call WHERE run_id=%s ORDER BY call_id", (run_id,)
        ).fetchall()
        tools = connection.execute(
            "SELECT * FROM agent_tool_call WHERE run_id=%s ORDER BY call_id", (run_id,)
        ).fetchall()
        callbacks = connection.execute(
            "SELECT kind,payload FROM agent_callback_outbox WHERE run_id=%s AND kind!='STARTED'", (run_id,)
        ).fetchall()
    if (frozen is None or not isinstance(frozen["manifest"], dict) or len(callbacks) != 1
            or not models or run["active_deadline_at"] is None or run["budget_spent"] is None):
        raise UnsupportedRecord("UNSUPPORTED_RECORD: incomplete terminal run")
    if any(row["state"] != "SAVED" or row["response"] is None or row["request_body"] is None
           or row["sdk_state"] is None or row["settled_spend"] is None for row in models):
        raise UnsupportedRecord("UNSUPPORTED_RECORD: UNKNOWN or incomplete model call")
    if any(row["observation"] is None or (row["local_read"]
           and row["observation"].get("tool_name") != "read_observation") for row in tools):
        raise UnsupportedRecord("UNSUPPORTED_RECORD: missing/unsupported local tool observation")
    if [row["call_id"] for row in models] != [f"model-{i}" for i in range(len(models))]:
        raise UnsupportedRecord("UNSUPPORTED_RECORD: nonsequential model calls")
    if [row["call_id"] for row in tools] != [f"tool-{i}" for i in range(len(tools))]:
        raise UnsupportedRecord("UNSUPPORTED_RECORD: nonsequential tool calls")
    if len(tools) > len(models) or any(row["response"]["mode"] != "mock" for row in models):
        raise UnsupportedRecord("UNSUPPORTED_RECORD: selected subset is sequential synthetic mock only")
    # C09 persists each tool's canonical request hash but not the request body. For the
    # selected sequential subset, the preceding saved model action carries the exact
    # tool name/arguments; require that it reproduces every durable tool hash.
    tool_requests = []
    for row in models:
        decision = row["response"]["decision"]
        if decision.get("kind") == "READ_TOOL":
            tool_requests.append({"name": decision["tool_name"], "arguments": decision["arguments"]})
        elif decision.get("kind") == "READ_OBSERVATION":
            arguments = {"observation_id": decision["observation_id"],
                         **{key: value for key, value in (decision.get("arguments") or {}).items()
                            if key in {"offset", "limit"} and value is not None}}
            tool_requests.append({"name": "read_observation", "arguments": arguments})
    if len(tool_requests) != len(tools) or any(
        hash_document(request) != row["request_hash"]
        or bool(row["local_read"]) != (request["name"] == "read_observation")
        for request, row in zip(tool_requests, tools, strict=True)
    ):
        raise UnsupportedRecord("UNSUPPORTED_RECORD: tool parameters cannot be reconstructed from saved actions")
    document: dict[str, Any] = {
        "schema_version": 1,
        "evaluation_run_id": str(uuid.uuid4()),
        "source_run_id": str(run["run_id"]),
        "clock": (run["active_deadline_at"] - dt.timedelta(seconds=60)).isoformat(),
        "facts": {
            "run_id": str(run["run_id"]), "case_id": str(run["case_id"]),
            "input_revision": run["input_revision"], "line_id": run["line_id"],
            "description": run["request_description"], "merchant_id": run["merchant_id"],
            "customer_id": run["customer_id"], "active_deadline_at": run["active_deadline_at"].isoformat(),
            "policy_manifest": run["policy_manifest"],
            **({"review_context": run["review_context"]} if run["review_context"] else {}),
        },
        "manifest": frozen["manifest"], "budget": frozen["budget"],
        "model_calls": [
            {key: row[key] for key in ("call_id", "kind", "request_hash", "request_body", "replay_spend",
                                         "sdk_state", "response", "settled_spend")}
            for row in models
        ],
        "tool_calls": [
            {**{key: row[key] for key in ("call_id", "request_hash", "local_read", "observation", "before_spend",
                                               "after_spend")}, "request_body": request}
            for row, request in zip(tools, tool_requests, strict=True)
        ],
        "expected": {
            "callback_kind": callbacks[0]["kind"], "callback_payload": callbacks[0]["payload"],
            "budget_spent": run["budget_spent"],
        },
    }
    write_pack(destination, document)
