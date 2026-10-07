"""Paired live crash/restart measurements; production AgentScope and fenced PG journals."""

import argparse
import copy
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src"), str(ROOT / "agent")]
from psycopg.types.json import Jsonb
from resolveflow.harness.budget import RunBudget
from resolveflow.harness.live_model import LiveModelClient
from resolveflow.policies import embedder
from resolveflow.runtime.db import Database
from resolveflow.runtime.durable import DurableRun
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.runs import RunRequest, RunStore, VerifiedCaller
from resolveflow.runtime.worker import RunWorker

from scripts.agent_eval import allowance
from scripts.evaluation.dataset import digest, read
from scripts.evaluation.environment import business_tools, environment
from scripts.evaluation.models import CaptureModel, live_guard
from scripts.evaluation.scoring import score_agent

DATA = ROOT / "evals/resume-quantification-v1/business-v1"
LEDGER = ROOT / "tmp/evaluation-live-budget.json"


def save(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def request(case, pin, run_id, case_id, deadline):
    return RunRequest(
        run_id=run_id,
        case_id=case_id,
        input_revision=1,
        **case["scope"],
        order_id=case["backend"]["order"]["order_id"],
        description=case["description"],
        requested_actions=("REFUND",),
        evidence_refs=tuple(
            m["evidence_id"]
            for m in case.get("review_context", {}).get("materials", [])
        ),
        policy_manifest=pin,
        deadline_at=deadline,
        review_context=case.get("review_context", {}),
    )


def child(args):
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    database = Database(spec["dsn"], schema=spec["schema"])
    case, pin = copy.deepcopy(spec["case"]), spec["pin"]
    # Each isolated evaluation run has a fresh case identity. Rebind only that wire identity,
    # so get_case_evidence is scoped to the actual request; all source facts/materials stay equal.
    case["case_id"] = spec["case_id"]
    case["backend"]["evidence"]["case_id"] = spec["case_id"]
    result_path = args.record
    report = {"stage": args.stage, "requests": [], "http_reads": []}

    def checkpoint(rows):
        report["requests"] = rows
        save(result_path, report)

    model = CaptureModel(
        LiveModelClient(
            endpoint="https://api.deepseek.com/chat/completions",
            model_id="deepseek-flash",
            provider="deepseek",
            api_key=os.environ["RESOLVEFLOW_MODEL_API_KEY"],
            parameters={
                "thinking": {"type": "disabled"},
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        ),
        allowance(LEDGER),
        on_record=checkpoint,
    )
    from resolveflow.runtime import factory

    def fault(stage):
        if stage == args.stage:
            report["fault_reached"] = stage
            report["http_reads"] = reads
            save(result_path, report)
            os._exit(73)

    class RedoDurable(DurableRun):
        def bind(self, runner):
            super().bind(runner)
            # Evaluation-only new run. Carry prefix spend/partition; no recorded replies or tools
            # are copied and no production run is reset. The original deadline is its queue deadline.
            inherited = spec.get("inherited")
            if inherited:
                with self.database.connection() as connection, connection.transaction():
                    connection.execute(
                        "UPDATE agent_run SET budget_spent=%s WHERE run_id=%s",
                        (Jsonb(inherited["budget_spent"]), self.facts.run_id),
                    )
                    connection.execute(
                        "UPDATE agent_run_model_budget SET call_partition=%s WHERE run_id=%s",
                        (Jsonb(inherited["call_partition"]), self.facts.run_id),
                    )

    factory.DurableRun = lambda db, facts: RedoDurable(db, facts, fault=fault)
    started = time.monotonic()
    try:
        with business_tools(
            case, pin, run_id=spec["run_id"], case_id=spec["case_id"]
        ) as (tools, reads):
            investigate = build_investigation(
                database=database,
                config=DeploymentConfig(
                    mode="live",
                    provider="deepseek",
                    endpoint=model.endpoint,
                    model_id=model.model_id,
                    policy_index=True,
                ),
                model=model,
                tools=tools,
                policy_embedder=embedder(),
                budget=RunBudget(model_calls=12),
            )
            outcome = RunWorker(database, investigate, recoverable=True).run_once()
            report.update(
                http_reads=reads,
                callback_kind=outcome.callback_kind,
                completed=outcome.result.completed,
                reason_code=outcome.result.reason_code,
                decision=outcome.result.decision.model_dump(mode="json")
                if outcome.result.decision
                else None,
                trajectory=outcome.result.trajectory,
                spend=asdict(outcome.result.spend),
                observations=[
                    o.model_dump(mode="json") for o in outcome.result.observations
                ],
                automatic=score_agent(
                    outcome.result, read("gold/agent.json", DATA)[case["id"]], case=case
                ),
            )
    except Exception as error:  # noqa: BLE001 - preserve every measured failure
        report.update(completed=False, error=f"{type(error).__name__}: {error}")
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        save(result_path, report)
        database.close()
    return int(not report.get("completed"))


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "state": "RUNNING",
        "trial": args.trial,
        "pairs": [],
        "runner_sha256": digest(Path(__file__)),
        "case": "A01A",
        "policy_variant": "B dense",
        "provider": "deepseek-flash",
        "temperature": 0,
        "scope": "real LLM/PG/AgentScope; production MCP to frozen synthetic read sources",
    }
    with live_guard(LEDGER), environment(dataset=DATA) as (db, _, _, pins):
        case = next(c for c in read("agent/cases.json", DATA) if c["id"] == "A01A")
        pin = pins[case["bundle_id"]]
        caller = VerifiedCaller(
            service="case-service",
            scope="run:dispatch",
            merchant_id=case["scope"]["merchant_id"],
            customer_id=case["scope"]["customer_id"],
        )
        for window in ("before_model_saved", "after_model_saved", "after_tool_saved"):
            for repeat in range(1 if args.trial else 5):
                pair = {"window": window, "repeat": repeat, "groups": {}}
                report["pairs"].append(pair)
                for group in (
                    ("resume", "redo") if repeat % 2 == 0 else ("redo", "resume")
                ):
                    run_id, case_id = str(uuid.uuid4()), str(uuid.uuid4())
                    RunStore(db).queue(
                        request(
                            case,
                            pin,
                            run_id,
                            case_id,
                            (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                        ),
                        caller=caller,
                    )
                    spec = {
                        "dsn": db.dsn,
                        "schema": db.schema,
                        "case": case,
                        "pin": pin,
                        "run_id": run_id,
                        "case_id": case_id,
                    }
                    label = f"{window}-{repeat}-{group}"
                    spec_path = (
                        ROOT / f"tmp/resume/recovery-{label}-{args.output.name}.json"
                    )
                    save(spec_path, spec)
                    prefix_path = args.output / f"{label}-prefix.json"
                    prefix = subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__)),
                            "--child",
                            "--spec",
                            str(spec_path),
                            "--stage",
                            window,
                            "--record",
                            str(prefix_path),
                        ],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        timeout=160,
                        check=False,
                    )
                    measured = {
                        "prefix_exit": prefix.returncode,
                        "prefix_file": prefix_path.name,
                    }
                    pair["groups"][group] = measured
                    if prefix.returncode != 73:
                        measured["error"] = (
                            "prefix did not reach expected crash; see captured record"
                        )
                        measured["stderr"] = prefix.stderr[-3000:]
                        save(args.output / "results.json", report)
                        if args.trial:
                            return 1
                        RunStore(db).cancel(run_id)
                        continue
                    with db.connection() as connection:
                        before = connection.execute(
                            "SELECT active_deadline_at,budget_spent FROM agent_run WHERE run_id=%s",
                            (run_id,),
                        ).fetchone()
                        partition = connection.execute(
                            "SELECT call_partition FROM agent_run_model_budget WHERE run_id=%s",
                            (run_id,),
                        ).fetchone()["call_partition"]
                        connection.execute(
                            "UPDATE agent_run SET lease_until=now()-interval '1 second' WHERE run_id=%s",
                            (run_id,),
                        )
                    measured["before"] = before
                    if group == "redo":
                        RunStore(db).cancel(run_id)
                        spec.update(
                            run_id=str(uuid.uuid4()),
                            case_id=str(uuid.uuid4()),
                            inherited={
                                "budget_spent": before["budget_spent"],
                                "call_partition": partition,
                            },
                        )
                        RunStore(db).queue(
                            request(
                                case,
                                pin,
                                spec["run_id"],
                                spec["case_id"],
                                before["active_deadline_at"].isoformat(),
                            ),
                            caller=caller,
                        )
                        save(spec_path, spec)
                    continuation_path = args.output / f"{label}-continuation.json"
                    continuation = subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__)),
                            "--child",
                            "--spec",
                            str(spec_path),
                            "--stage",
                            "continue",
                            "--record",
                            str(continuation_path),
                        ],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        timeout=160,
                        check=False,
                    )
                    measured.update(
                        continuation_exit=continuation.returncode,
                        continuation_file=continuation_path.name,
                    )
                    with db.connection() as connection:
                        after = connection.execute(
                            "SELECT active_deadline_at,budget_spent,fence FROM agent_run WHERE run_id=%s",
                            (spec["run_id"],),
                        ).fetchone()
                    measured["after"] = after
                    measured["same_deadline"] = (
                        before["active_deadline_at"] == after["active_deadline_at"]
                    )
                    assert measured["same_deadline"]
                    measured["post_requests"] = len(
                        json.loads(continuation_path.read_text(encoding="utf-8"))[
                            "requests"
                        ]
                    )
                    save(args.output / "results.json", report)
                    print(
                        json.dumps(
                            {
                                "window": window,
                                "repeat": repeat,
                                "group": group,
                                "post_requests": measured["post_requests"],
                                "exit": continuation.returncode,
                            }
                        ),
                        flush=True,
                    )
    report["state"] = "COMPLETED"
    save(args.output / "results.json", report)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--trial", action="store_true")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--stage")
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--record", type=Path)
    options = parser.parse_args()
    raise SystemExit(child(options) if options.child else main(options))
