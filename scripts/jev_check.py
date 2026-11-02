"""Inspect saved Jev checks, or explicitly run twelve synthetic cases through the real SupportRuntime."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import statistics
import sys
import uuid
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from resolveflow.harness.model import MockModelClient
from resolveflow.runtime.db import DEFAULT_DSN, Database, create_schema
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.jev import JevClient, JevConfig, load_local_env
from resolveflow.support.protocol import SupportInput
from resolveflow.support.service import SupportRuntime

FIXTURE = ROOT / "agent/tests/fixtures/jev-smoke-v1.json"


class SyntheticSources:
    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case

    def read(self, _name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        if self.case.get("error"):
            return {"error": self.case["error"], "retryable": False}
        return {"source_type": self.case["source_type"], "version": "synthetic-v1",
                "data": {"text": self.case["evidence"], "synthetic": True}}

    def search(self, _query: str, _top_k: int) -> list[dict[str, Any]]:
        return [self.read("", {})]


def inspect(database: Database, run_id: str) -> list[dict[str, Any]]:
    with database.connection() as c:
        return cast(list[dict[str, Any]], c.execute(
            "SELECT position,status,request_hash,request_json,response_json,created_at "
            "FROM support_agent_call WHERE run_id=%s AND kind='jev' ORDER BY position",
            (str(uuid.UUID(run_id)),)).fetchall())


def smoke(output: Path, config: JevConfig) -> dict[str, Any]:
    # Create the output before any network call. Never overwrite or silently re-run a paid cohort.
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = FIXTURE.read_bytes()
    cases = json.loads(raw)
    dsn = os.environ.get("RESOLVEFLOW_AGENT_DB", DEFAULT_DSN)
    schema = "jev_smoke_" + uuid.uuid4().hex[:12]
    report: dict[str, Any] = {"version": "jev-smoke-v1", "data_kind": "synthetic",
                              "primary_model": "scripted-mock", "judge_model": "live-typesafe",
                              "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                              "config": config.manifest(), "schema": schema, "cases": [],
                              "limits": {"calls": 12, "estimated_usd": 1.0}}
    with output.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    create_schema(dsn, schema)
    database = Database(dsn, schema=schema)
    try:
        database.migrations()
        reserved_cost = 0.0
        for case in cases:
            # Each request is bounded by the existing 8192-token allowance. No retries or extra judges.
            reserved_cost += 8192 * .042 / 1_000_000
            if len(report["cases"]) >= 12 or reserved_cost > 1:
                break
            request = SupportInput(run_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()), input_version=1,
                                   merchant_id="JEV-SYNTHETIC", customer_id="JEV-SYNTHETIC", line_id="JEV-LINE",
                                   deadline_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=60),
                                   context={"current_request": case["question"], "history": []})
            is_policy, failed = case["source_type"] == "POLICY", bool(case.get("error"))
            opening = ({"kind": "SEARCH_POLICY", "query": case["question"], "top_k": 1} if is_policy else
                       {"kind": "READ_TOOL", "tool_name": "get_shipment_trace", "arguments": {}})
            closing = {"kind": "ANSWER", "text": case["answer"], "handoff_summary": None,
                       "citations": [] if failed else ["P1" if is_policy else "O1"]}
            runtime = SupportRuntime(database, DeploymentConfig(mode="mock"), jev_config=config,
                                     jev_client=JevClient(config),
                                     model_factory=lambda opening=opening, closing=closing:
                                         MockModelClient(script=[opening, closing]),
                                     sources_factory=lambda *_, case=case: SyntheticSources(case))
            result = runtime.run(request, "synthetic-no-network-source-token")
            rows = inspect(database, request.run_id)
            check = rows[0]["response_json"] if rows else None
            entry = {"id": case["id"], "run_id": request.run_id, "expected": case["expected"],
                     "runtime_status": result["status"], "runtime_reason": result["reason"],
                     "answer_unchanged": (result.get("answer") or {}).get("text") == case["answer"],
                     "check": check, "saved_calls": rows,
                     "matches_expected": bool(check and check.get("verdict") == case["expected"])}
            report["cases"].append(entry)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                              encoding="utf-8", newline="\n")
            print(json.dumps({"case": case["id"], "expected": case["expected"],
                              "actual": check.get("verdict", check.get("reason")) if check else result["reason"]},
                             ensure_ascii=False), flush=True)
        checks = [row["check"] for row in report["cases"] if row["check"]]
        times = [check["elapsed_ms"] for check in checks if "elapsed_ms" in check]
        report["summary"] = {"total": len(report["cases"]),
                             "matches_expected": sum(row["matches_expected"] for row in report["cases"]),
                             "completed": sum(check["status"] == "COMPLETE" for check in checks),
                             "input_tokens": sum(check.get("usage", {}).get("input_tokens", 0) for check in checks),
                             "median_ms": statistics.median(times) if times else None,
                             "max_ms": max(times) if times else None}
        report["summary"]["estimated_usd"] = report["summary"]["input_tokens"] * .042 / 1_000_000
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                          encoding="utf-8", newline="\n")
    finally:
        database.close()
    return report


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--live", action="store_true", help="explicitly authorize at most twelve paid Jev calls")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/jev-smoke-20261102/results.json")
    args = parser.parse_args()
    if args.smoke:
        if not args.live or args.run_id:
            parser.error("--smoke requires --live and cannot be combined with --run-id")
        load_local_env(ROOT / ".env")
        config = JevConfig.from_environ()
        if not config.enabled:
            parser.error("RESOLVEFLOW_JEV_ENABLED=1 is required")
        report = smoke(args.output, config)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    elif args.run_id:
        database = Database(schema=args.schema)
        try:
            print(json.dumps(inspect(database, args.run_id), ensure_ascii=False, indent=2, default=str))
        finally:
            database.close()
    else:
        parser.error("choose --run-id for read-only inspection or --smoke --live for the paid smoke test")


if __name__ == "__main__":
    main()
