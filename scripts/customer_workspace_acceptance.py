"""Scoped synthetic browser acceptance support; every case write remains on the public UI/API.

Seeds new demo orders only. Investigates exactly one case from this manifest with the production
AgentScope factory, lease/fence and callback outbox. It never drains the shared queue, starts live
models, rewrites a case state, or substitutes a SQL refund for a business step.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "agent" / "src"))
import reviewer_demo as demo
from resolveflow.harness.model import MockModelClient
from resolveflow.policies.index import PolicyIndex
from resolveflow.policies.retrieval import embedder
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.leases import RunLease
from resolveflow.runtime.worker import RunWorker

MANIFEST = ROOT / "reports" / "customer-workspace" / "acceptance.json"


def save(document: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    demo.atomic_write(MANIFEST, json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def protected_runs(database: Database, ids: list[str] | None = None) -> list[dict]:
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT run_id,status,version,fence FROM agent_run "
            + ("WHERE run_id=ANY(%s::uuid[]) " if ids is not None else "")
            + "ORDER BY run_id", (ids,) if ids is not None else (),
        ).fetchall()
    return [{**row, "run_id": str(row["run_id"])} for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["seed", "inspect", "investigate", "verify-isolation",
                                            "verify-ownership", "verify-outcomes"])
    parser.add_argument("--case-id")
    args = parser.parse_args()
    settings = demo.settings_from_environ()
    demo.guard(settings)
    scenario = demo.SCENARIOS["lost-review"]
    database = Database(settings.agent_dsn)
    try:
        if args.command == "seed":
            if MANIFEST.exists():
                print("Existing acceptance manifest retained; no new orders seeded.")
                return 0
            document = {"environment": settings.environment, "date": datetime.now(UTC).isoformat(),
                        "model_mode": "mock", "synthetic": True, "orders": [], "investigations": [],
                        "protected_runs": protected_runs(database)}
            save(document)
            for i in range(3):
                line = demo.seed_line(settings, scenario, 80 + i)
                document["orders"].append({"line_id": line, "purpose": ["answer-approve", "reject", "cancel"][i], "case_id": None})
                save(document)
            print(json.dumps(document["orders"], ensure_ascii=False))
            return 0
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if document["environment"] != settings.environment:
            raise demo.DemoRefused("acceptance manifest belongs to another environment")
        customer = demo.login(settings, scenario.customer_username, scenario.customer_password)
        for item in document["orders"]:
            page = demo.api(settings, f"/api/v1/customer/cases?line_id={item['line_id']}&limit=100", token=customer)
            if page["items"]:
                item["case_id"] = page["items"][0]["case_id"]
                item["detail"] = demo.api(settings, f"/api/v1/customer/cases/{item['case_id']}", token=customer)
        if args.command == "investigate":
            case_id = str(uuid.UUID(args.case_id or ""))
            item = next((row for row in document["orders"] if row["case_id"] == case_id), None)
            if item is None:
                raise demo.DemoRefused("only a new browser case from this acceptance manifest may be investigated")
            revision = item["detail"]["input_revision"]
            run_id = demo.agent_run_id(case_id, revision)
            with database.connection() as connection:
                row = connection.execute("SELECT status FROM agent_run WHERE run_id=%s AND case_id=%s AND input_revision=%s", (run_id, case_id, revision)).fetchone()
            if row is None or row["status"] != "QUEUED":
                raise demo.DemoRefused("target run must already have been dispatched and still be queued; do not reset or replay it")
            bundle, digest = demo.pinned_bundle(settings, case_id)
            citations = demo.preflight(settings, case_id=case_id, run_id=run_id, input_revision=revision,
                                      line_id=item["line_id"], tool_calls=demo._tool_calls_for(scenario))
            policies = demo._policies_for(settings, scenario, bundle_id=bundle, manifest_hash=digest)
            script = demo.build_script(scenario, citations=citations, policies=policies)
            # An explicit mock fixture may target its known rule, never invent a policy hit.
            # All hard limits and the server's whole-bundle exception check remain enabled.
            index = PolicyIndex(database)
            encoder = embedder(str(demo.EMBEDDING_PATH))
            hits = index.search(merchant_id=scenario.merchant_id, bundle_ids=[bundle], manifest_hash=digest,
                                query="物流丢失 全额退款", path="dense", top_k=5, embedder=encoder)
            rule = next(hit for hit in hits if hit.rule_id == "R-LOST-001")
            narrow = index.search(merchant_id=scenario.merchant_id, bundle_ids=[bundle], manifest_hash=digest,
                                 query=rule.text, path="dense", top_k=1, embedder=encoder)
            if not narrow or narrow[0].rule_id != rule.rule_id:
                raise demo.DemoRefused("the explicit mock query did not retrieve its actual pinned rule")
            search = next(step for step in script if step["kind"] == "SEARCH_POLICY")
            search.update(query=rule.text, arguments={"top_k": 1})
            config = DeploymentConfig(mode="mock", context_window_tokens=32768, case_base_url=settings.case_url,
                                      commerce_base_url=settings.commerce_url, policy_index=True,
                                      embedding_path=str(demo.EMBEDDING_PATH))
            investigate = build_investigation(database=database, config=config, model=MockModelClient(script=script),
                                             service_identity_source=lambda: demo.mint_service_token("agent-service"))
            worker = RunWorker(database, investigate=investigate, recoverable=True)
            with RunLease(database, owner="customer-browser-acceptance").acquire(run_id=run_id) as claimed:
                if claimed is None or claimed.legacy:
                    raise demo.DemoRefused("target could not be claimed; no other run will be taken")
                outcome = worker.finish(claimed, investigate(claimed.facts))
            document["investigations"].append({"case_id": case_id, "run_id": run_id, "input_revision": revision,
                                               "callback_kind": outcome.callback_kind, "status": outcome.status,
                                               "reason_code": outcome.result.reason_code, "model_mode": "mock"})
            save(document)
            print(json.dumps(document["investigations"][-1], ensure_ascii=False))
            if outcome.callback_kind != "PROPOSAL":
                return 1
        elif args.command == "verify-outcomes":
            expected = ["CLOSED_SUCCESS", "CLOSED_REJECTED", "CANCELLED"]
            for item, status in zip(document["orders"], expected, strict=True):
                detail = item["detail"]
                assert detail["case"]["status"] == status and detail["allowed_actions"] == []
                assert detail["case"]["description"]
                if status != "CANCELLED":
                    assert len(detail["questions"]) == 2
                    assert all(q["status"] == "ANSWERED" and q["answers"] for q in detail["questions"])
                if status == "CLOSED_SUCCESS":
                    assert detail["result"]["amount_minor"] == 32900
                else:
                    assert detail["result"]["amount_minor"] is None
            document["outcomes_verified"] = True
            with database.connection() as connection:
                runs = connection.execute(
                    "SELECT run_id,input_revision,status,budget_spent FROM agent_run "
                    "WHERE case_id=ANY(%s::uuid[]) ORDER BY case_id,input_revision",
                    ([item["case_id"] for item in document["orders"]],),
                ).fetchall()
            document["run_audit"] = [{**row, "run_id": str(row["run_id"])} for row in runs]
            print("Three terminal outcomes and retained two-round answers verified")
        elif args.command == "verify-ownership":
            checks = []
            for username, password in [("demo-customer-2", "demo-pass-1002"),
                                       ("demo-customer-m2", "demo-pass-2001")]:
                other = demo.login(settings, username, password)
                for item in document["orders"]:
                    if not item["case_id"]:
                        continue
                    for path in [f"/api/v1/customer/cases/{item['case_id']}",
                                 f"/api/v1/customer/order-lines/{item['line_id']}"]:
                        status, _ = demo.http("GET", settings.gateway_url + path, token=other)
                        checks.append({"account": username, "path": path, "status": status})
                        assert status == 404, f"customer ownership isolation failed: {username} {path} returned {status}"
            document["ownership_checks"] = checks
            print(f"Customer and merchant ownership checks passed: {len(checks)}")
        elif args.command == "verify-isolation":
            before = document["protected_runs"]
            after = protected_runs(database, [row["run_id"] for row in before])
            assert before == after, "An unrelated persisted run changed; do not report isolation success"
            document["unrelated_runs_unchanged"] = True
            print(f"Protected historical runs unchanged: {len(before)}")
        else:
            print(json.dumps([{k: v for k, v in row.items() if k != "detail"} | {"status": row.get("detail", {}).get("case", {}).get("status")} for row in document["orders"]], ensure_ascii=False))
        save(document)
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
