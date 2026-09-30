"""Explicit, finite live acceptance on synthetic demo cases; never a second production loop.

Prepare creates fresh order lines plus authenticated cases/evidence. Investigate delegates one
current revision to the production RunWorker/AgentScope/MCP/RAG pipeline. A read-only demo API
delivers its callbacks. Keys are environment-only; reports contain synthetic facts and usage.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from dataclasses import replace
from pathlib import Path

import reviewer_demo as demo
from resolveflow.harness.live_model import ModelRefusedError, _urllib_transport
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import DeploymentConfig, _live_client, build_investigation
from resolveflow.runtime.worker import RunWorker

PREFIX = "【真实模型验收·合成】"


class BoundedTransport:
    """Count transmissions before sending, including retries and timed-out responses."""

    def __init__(self, limit: int = 12):
        self.limit = limit
        self.calls = 0
        self.usage: list[dict] = []
        self.errors: list[dict] = []

    def __call__(self, url, body, headers, timeout):
        if self.calls >= self.limit:
            raise ModelRefusedError("LIVE_ACCEPTANCE_CALL_LIMIT")
        if url != "https://api.deepseek.com/chat/completions":
            raise ModelRefusedError("LIVE_ACCEPTANCE_ENDPOINT_REFUSED")
        self.calls += 1
        response = _urllib_transport(url, body, headers, min(timeout, 30))
        if response.status == 200:
            envelope = json.loads(response.body)
            self.usage.append({"model": envelope.get("model"), **envelope.get("usage", {})})
        else:
            secret = headers.get("Authorization", "").removeprefix("Bearer ")
            message = response.body.decode("utf-8", errors="replace")[:1000]
            self.errors.append({"status": response.status, "message": message.replace(secret, "[redacted]")
                                if secret else message})
        print(json.dumps({"provider_call": self.calls, "status": response.status}, ensure_ascii=False), flush=True)
        return response


def prepare(settings, name):
    scenario = replace(demo.SCENARIOS[name], description=PREFIX + demo.SCENARIOS[name].description)
    if name == "waiting-info":
        # Recent scans deliberately do not satisfy the pinned seven-day no-scan rule.
        current = datetime.now(UTC)
        scenario = replace(scenario, shipment_events=(
            ("SHIPMENT_CREATED", (current - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S.%f")),
            ("IN_TRANSIT_HUB", (current - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S.%f")),
        ))
    line_id = demo.seed_line(settings, scenario, 31)
    customer = demo.login(settings, scenario.customer_username, scenario.customer_password)
    reviewer = demo.login(settings, scenario.reviewer_username, scenario.reviewer_password)
    created = demo.api(settings, "/api/v1/cases", token=customer,
                       headers={"Idempotency-Key": f"live-acceptance:{line_id}"},
                       body={"line_id": line_id, "description": scenario.description,
                             "requested_actions": ["REFUND"]}, expect=(201,))
    case_id = str(uuid.UUID(created["case_id"]))
    demo.api(settings, f"/api/v1/cases/{case_id}/evidence", token=customer,
             body={"text": scenario.customer_material, "evidence_kind": "CUSTOMER_STATEMENT"})
    if scenario.verification:
        view = demo.api(settings, f"/api/v1/cases/{case_id}", token=reviewer)
        source = next(item for item in view["evidence"] if item["evidence_kind"] == "CUSTOMER_STATEMENT")
        demo.api(settings, f"/api/v1/cases/{case_id}/reviewed-evidence", token=reviewer,
                 body={"source_evidence_id": source["observation_id"],
                       "verification_result": scenario.verification[0], "reason": scenario.verification[1]})
    view = demo.api(settings, f"/api/v1/cases/{case_id}", token=reviewer)
    return {"scenario": name, "case_id": case_id, "line_id": line_id,
            "input_revision": view["case"]["input_revision"], "synthetic": True}


def investigate(settings, case_id):
    key = os.environ.get("RESOLVEFLOW_MODEL_API_KEY")
    if not key:
        raise demo.DemoRefused("Missing RESOLVEFLOW_MODEL_API_KEY (environment only).")
    case_id = str(uuid.UUID(case_id))
    reviewer = demo.login(settings, "demo-reviewer", "demo-pass-1003")
    view = demo.api(settings, f"/api/v1/cases/{case_id}", token=reviewer)
    if not view["case"]["description"].startswith(PREFIX):
        raise demo.DemoRefused("Only fresh live-acceptance synthetic cases are allowed.")
    revision = view["case"]["input_revision"]
    run_id = demo.agent_run_id(case_id, revision)
    database = Database(settings.agent_dsn)
    transport = BoundedTransport()
    config = DeploymentConfig(mode="live", provider="deepseek", model_id="deepseek-flash",
                              context_window_tokens=32768,
                              endpoint="https://api.deepseek.com/chat/completions", api_key=key,
                              case_base_url=settings.case_url, commerce_base_url=settings.commerce_url,
                              policy_index=True, embedding_path=str(demo.EMBEDDING_PATH))
    # Warm the real local embedder before claiming: cold model loading must not consume the run's deadline.
    from resolveflow.policies.retrieval import embedder
    policy_embedder = embedder(local_path=config.embedding_path)
    policy_embedder.embed(["验收预热"])
    client = _live_client(config)
    client.transport = transport
    production = build_investigation(database=database, config=config, model=client,
                                    policy_embedder=policy_embedder,
                                    service_identity_source=lambda: demo.mint_service_token("agent-service"))

    def current_only(facts):
        if facts.run_id != run_id:
            raise demo.DemoRefused("A different runnable case appeared; no provider request was sent for it.")
        return production(facts)

    worker = RunWorker(database, investigate=current_only, recoverable=True)
    started = time.monotonic()
    result = None
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            with database.connection() as connection:
                row = connection.execute("SELECT status FROM agent_run WHERE run_id=%s", (run_id,)).fetchone()
            if row:
                break
            time.sleep(0.5)
        if not row or row["status"] != "QUEUED":
            raise demo.DemoRefused("Current run is missing or already investigated; refusing duplicate live work.")
        with database.connection() as connection:
            others = connection.execute(
                "SELECT run_id FROM agent_run WHERE status IN ('QUEUED','RUNNING') AND cancelled_at IS NULL "
                "AND deadline_at>clock_timestamp() AND run_id<>%s", (run_id,)).fetchall()
        if others:
            raise demo.DemoRefused("Other active runs exist; finish them before finite acceptance.")
        # Expired historical queued records may precede this run. Worker terminates them without any model call.
        for _ in range(32):
            outcome = worker.run_once()
            if outcome is None:
                raise demo.DemoRefused("No claimable run; another worker may own it.")
            if outcome.run_id == run_id:
                result = outcome
                break
        if result is None:
            raise demo.DemoRefused("Too many expired historical runs precede this sample.")
        with database.connection() as connection:
            row = connection.execute("SELECT status,budget_spent,review_context FROM agent_run WHERE run_id=%s",
                                     (run_id,)).fetchone()
            tools = connection.execute("SELECT observation FROM agent_tool_call WHERE run_id=%s ORDER BY call_id",
                                       (run_id,)).fetchall()
        return {"case_id": case_id, "run_id": run_id, "input_revision": revision, "synthetic": True,
                "model_id": config.model_id, "mode": "live", "provider_calls": transport.calls,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "status": row["status"], "reason_code": result.result.reason_code if result.result else None,
                "budget_spent": row["budget_spent"], "usage": transport.usage,
                "provider_errors": transport.errors,
                "review_context": row["review_context"], "observations": [item["observation"] for item in tools],
                "decision": result.result.decision.model_dump(mode="json")
                if result.result and result.result.decision else None}
    finally:
        database.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "investigate"))
    parser.add_argument("--scenario", choices=("lost-review", "signed-conflict", "damage-review", "waiting-info"))
    parser.add_argument("--case-id")
    parser.add_argument("--output", type=Path, required=True, help="synthetic acceptance report, never a key file")
    args = parser.parse_args()
    settings = demo.settings_from_environ()
    demo.guard(settings)
    if any(item["name"] in {"agent", "agent-live"} for item in demo.read_owned(settings)):
        raise demo.DemoRefused("Use demo.ps1 without -Live to leave only the read-only callback API running.")
    if args.command == "prepare":
        if not args.scenario:
            parser.error("prepare requires --scenario")
        report = prepare(settings, args.scenario)
    else:
        if not args.case_id:
            parser.error("investigate requires --case-id")
        report = investigate(settings, args.case_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    demo.atomic_write(args.output, json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps({key: report[key] for key in ("case_id", "input_revision", "status", "reason_code") if key in report},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
