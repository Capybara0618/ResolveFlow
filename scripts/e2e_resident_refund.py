"""C08.2 mock-model refund from real Case dispatch through reviewer, broker and provider.

The script creates its own paid line and LOST shipment, reads the actual shipment and indexed policy before
writing a synthetic model script, then lets the resident Agent investigate the same run. It keeps raw service
logs under ignored ``tmp/`` and only stops processes it started. Run after the existing MySQL, PostgreSQL and
RocketMQ containers are healthy; no database or volume is cleared.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import e2e_harness_java_tools as tools_driver
import e2e_refund_chain as chain
import e2e_transport_refund as base

ROOT = base.ROOT
AGENT_PYTHON = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"
sys.path.insert(0, str(ROOT / "agent" / "src"))

from resolveflow.harness.mcp_client import McpToolExecutor
from resolveflow.policies.index import PolicyIndex
from resolveflow.policies.retrieval import embedder
from resolveflow.runtime.db import Database
from resolveflow.tools.credential import credential_source

REVIEWER_PASSWORD = "demo-pass-1003"  # local fixture account, not a deployment secret
POLICY_QUERY = "物流丢失 全额退款"


def _rows(statement: str) -> list[list[str]]:
    return base.mysql_rows(statement)


def _wait_for(statement: str, expected: str, processes: tuple[Any, ...], timeout: float = 90) -> list[list[str]]:
    deadline = time.monotonic() + timeout
    rows: list[list[str]] = []
    while time.monotonic() < deadline:
        rows = _rows(statement)
        if rows and rows[0][0] == expected:
            break
        if any(proc.poll() is not None for proc in processes):
            break
        time.sleep(0.5)
    return rows


def _preflight(case_id: str, run_id: str, line_id: str, manifest_hash: str, bundle_id: str,
               report: base.Report) -> tuple[dict[str, str], dict[str, str]]:
    """Get real citation values. The later resident read/search must see these exact pinned values."""
    case_url = f"http://127.0.0.1:{chain.CASE_PORT}"
    source = credential_source(
        case_base_url=case_url, run_id=run_id, case_id=case_id, input_revision=1,
        service_token=tools_driver.mint_service_token("agent-service"), static_token=None)
    assert source is not None
    tool = McpToolExecutor(
        python=str(AGENT_PYTHON), line_id=line_id, run_id=run_id, case_id=case_id, input_revision=1,
        case_base_url=case_url, commerce_base_url=f"http://127.0.0.1:{chain.COMMERCE_PORT}",
        credential_source=source, env_extra={"PYTHONPATH": str(ROOT / "agent" / "src")})
    try:
        shipment = tool.call_tool(run_id=run_id, tool_name="get_shipment_trace", arguments={"limit": 3})
    finally:
        tool.close()
    if shipment.error is not None:
        raise RuntimeError(f"real shipment tool returned {shipment.error.code}: {shipment.error.message}")
    evidence = {key: getattr(shipment, key) for key in (
        "observation_id", "source_ref", "source_version", "content_hash")}
    if any(value is None for value in evidence.values()):
        raise RuntimeError("real shipment observation has no citable version/hash")
    report.note(f"real MCP shipment: {evidence['observation_id']} {evidence['source_ref']} "
                f"version={evidence['source_version']}")

    database = Database()
    try:
        hits = PolicyIndex(database).search(
            merchant_id="M-1001", bundle_ids=[bundle_id], manifest_hash=manifest_hash,
            query=POLICY_QUERY, path="dense", top_k=5, embedder=embedder())
    finally:
        database.close()
    matching = next((hit for hit in hits if hit.rule_id == "R-LOST-001"), None)
    if matching is None:
        raise RuntimeError("pinned dense search did not show the lost-parcel rule in its top five")
    policy = {key: getattr(matching, key) for key in (
        "bundle_id", "version", "rule_id", "chunk_id", "content_hash")}
    report.note(f"real PG policy hit: {policy['bundle_id']}/{policy['rule_id']} {policy['chunk_id']}")
    return evidence, policy


def main() -> int:
    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S")
    output = ROOT / "tmp" / "c08-resident-refund" / stamp
    output.mkdir(parents=True, exist_ok=True)
    report = base.Report(output / "result.txt")
    report.head("# C08.2 real Java/PG/MCP/MQ refund with explicit mock model")
    report.head(f"run {stamp}")
    agent_proc = case_proc = commerce_proc = None
    try:
        if not chain.java_ports_available(report):
            report.finish("FAILED: Java service port occupied")
            return 1
        if _rows("SELECT 1") != [["1"]] or not base.tcp_open("127.0.0.1", 9876):
            report.finish("FAILED: MySQL or RocketMQ nameserver unavailable")
            return 1

        agent_port = chain.free_port()
        agent_url = f"http://127.0.0.1:{agent_port}"
        case_url = f"http://127.0.0.1:{chain.CASE_PORT}"
        amount = int(base.scalar("SELECT line_paid_amount FROM commerce_db.order_line WHERE line_id = '7001'"))

        commerce_proc = chain.start(
            "commerce-service",
            [base.JAVA_HOME / "bin" / "java", "-jar", base.COMMERCE_JAR,
             f"--resolveflow.provider.base-url={agent_url}",
             f"--resolveflow.events.namesrv={base.NAMESRV}",
             "--resolveflow.events.consumer.enabled=true", "--resolveflow.events.publisher.enabled=true",
             "--resolveflow.events.outbox.delivery-enabled=true", "--resolveflow.events.outbox.poll-interval-ms=300",
             "--resolveflow.refund.dispatch-enabled=true", "--resolveflow.refund.reconcile-enabled=true",
             "--resolveflow.refund.poll-interval-ms=1000"],
            base.child_env(), report, output)
        case_proc = chain.start(
            "case-service",
            [base.JAVA_HOME / "bin" / "java", "-jar", chain.CASE_JAR,
             f"--resolveflow.agent.base-url={agent_url}", "--resolveflow.dispatch.enabled=true",
             "--resolveflow.dispatch.poll-interval-ms=500",
             f"--resolveflow.events.namesrv={base.NAMESRV}",
             "--resolveflow.events.publisher.enabled=true", "--resolveflow.events.consumer.enabled=true",
             "--resolveflow.events.outbox.delivery-enabled=true", "--resolveflow.events.outbox.poll-interval-ms=300"],
            base.child_env(), report, output)
        ready = (
            chain.wait_health("commerce", f"http://127.0.0.1:{chain.COMMERCE_PORT}/actuator/health",
                              commerce_proc, report)
            and chain.wait_health("case", f"{case_url}/actuator/health", case_proc, report)
        )
        report.step("Java services healthy", ready, 0)
        if not ready:
            report.finish("FAILED: Java service startup")
            return 1

        line_id, _, _ = chain.create_demo_line(amount, report)
        if not line_id.isdecimal():
            raise RuntimeError("driver-minted line id is not numeric")
        now = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")
        _rows(
            "START TRANSACTION;"
            " INSERT INTO commerce_db.shipment (line_id,status,carrier_conclusion,source_version)"
            f" VALUES ('{line_id}','LOST','LOST',1);"
            " INSERT INTO commerce_db.shipment_event (line_id,code,occurred_at,source_version)"
            f" VALUES ('{line_id}','CARRIER_LOST','{now}',1); COMMIT;")

        status, login = tools_driver.request_json(
            f"{case_url}/api/v1/auth/login", method="POST",
            body={"username": tools_driver.CUSTOMER, "password": tools_driver.CUSTOMER_PASSWORD})
        if status != 200:
            raise RuntimeError(f"customer login returned {status}")
        status, created = tools_driver.request_json(
            f"{case_url}/api/v1/cases", method="POST", token=login["access_token"],
            headers={"Idempotency-Key": f"c08-refund-{line_id}"},
            body={"line_id": line_id, "description": "承运商确认包裹丢失，申请全行退款",
                  "requested_actions": ["REFUND"]})
        report.step("case opened", status == 201, 0, str(status) if status == 201 else f"{status} {created}")
        if status != 201:
            report.finish("FAILED: case creation")
            return 1
        case_id = str(uuid.UUID(created["case_id"]))
        run_id = str(uuid.UUID(tools_driver.agent_run_id_for(case_id, created["input_revision"])))
        report.note(f"case={case_id} run={run_id} line={line_id}")
        manifest_hash = base.scalar(
            f"SELECT manifest_hash FROM case_db.case_policy_manifest WHERE case_id='{case_id}'")
        bundle_id = base.scalar(
            f"SELECT bundle_id FROM case_db.case_policy_bundle WHERE case_id='{case_id}' LIMIT 1")
        evidence, policy = _preflight(case_id, run_id, line_id, manifest_hash, bundle_id, report)
        script = output / "mock-decisions.json"
        script.write_text(json.dumps([
            {"kind": "READ_TOOL", "tool_name": "get_shipment_trace", "arguments": {"limit": 3}},
            {"kind": "SEARCH_POLICY", "query": POLICY_QUERY, "arguments": {"top_k": 5}},
            {"kind": "PROPOSE", "case_type": "LOGISTICS", "recommended_action": "REFUND",
             "reason_codes": ["CARRIER_LOST"], "summary": "承运商确认丢失，按固定政策建议全行退款",
             "evidence_refs": [evidence], "policy_refs": [policy]},
        ], ensure_ascii=False), encoding="utf-8")
        agent_proc = chain.start(
            "agent-provider", [AGENT_PYTHON, "-m", "uvicorn", "resolveflow.api.app:app",
                               "--host", "127.0.0.1", "--port", str(agent_port), "--log-level", "warning"],
            base.child_env(
                RESOLVEFLOW_INVESTIGATION_ENABLED="1", RESOLVEFLOW_MODEL_MODE="mock",
                RESOLVEFLOW_MOCK_SCRIPT=str(script), RESOLVEFLOW_POLICY_INDEX="1",
                RESOLVEFLOW_CASE_BASE_URL=case_url,
                RESOLVEFLOW_COMMERCE_BASE_URL=f"http://127.0.0.1:{chain.COMMERCE_PORT}",
                RESOLVEFLOW_PROVIDER_DB=str(output / "provider.sqlite3")), report, output)
        if not chain.wait_reachable("agent", f"{agent_url}/health", agent_proc, report):
            report.finish("FAILED: Agent startup")
            return 1

        proposal = _wait_for(
            "SELECT status FROM case_db.case_proposal "
            f"WHERE case_id='{case_id}' ORDER BY created_at DESC LIMIT 1",
            "VALIDATED", (agent_proc, case_proc, commerce_proc), timeout=120)
        report.check("Case revalidated the Agent refund proposal", str(proposal), "VALIDATED",
                     proposal == [["VALIDATED"]])
        if proposal != [["VALIDATED"]]:
            report.finish("FAILED: Agent proposal not validated")
            return 1
        authorization = _rows(
            f"SELECT authorization_id,authorization_version FROM case_db.case_authorization WHERE case_id='{case_id}'")
        case_version = base.scalar(
            f"SELECT version FROM case_db.aftersale_case WHERE case_id='{case_id}'")
        report.check("reviewable authorization exists", str(authorization), "one authorization",
                     len(authorization) == 1)
        if len(authorization) != 1:
            report.finish("FAILED: no reviewable authorization")
            return 1

        status, reviewer = tools_driver.request_json(
            f"{case_url}/api/v1/auth/login", method="POST",
            body={"username": "demo-reviewer", "password": REVIEWER_PASSWORD})
        if status != 200:
            raise RuntimeError(f"reviewer login returned {status}")
        status, ownership = tools_driver.request_json(
            f"{case_url}/api/v1/cases/{case_id}/collaboration", method="POST", token=reviewer["access_token"],
            headers={"If-Collaboration-Match": '"0"'},
            body={"action": "CLAIM", "reason": "合成链路：领取本次新建工单"})
        if status != 200 or not ownership.get("is_owner"):
            raise RuntimeError(f"synthetic case claim failed: {status}")
        status, decision = tools_driver.request_json(
            f"{case_url}/api/v1/cases/{case_id}/reviews", method="POST", token=reviewer["access_token"],
            headers={"If-Match": f'"{case_version}"', "If-Collaboration-Match": f'"{ownership["version"]}"'},
            body={"authorization_id": authorization[0][0], "authorization_version": int(authorization[0][1]),
                  "decision": "APPROVE", "reason": "物流证据与固定政策一致，同意全行退款"})
        report.step("human reviewer approved", status == 200, 0, str(status) if status == 200 else f"{status} {decision}")
        if status != 200:
            report.finish("FAILED: review decision")
            return 1

        closed = _wait_for(
            f"SELECT status FROM case_db.aftersale_case WHERE case_id='{case_id}'",
            "CLOSED_SUCCESS", (agent_proc, case_proc, commerce_proc), timeout=120)
        report.check("case closed after real refund result", str(closed), "CLOSED_SUCCESS",
                     closed == [["CLOSED_SUCCESS"]])
        operation = _rows(
            "SELECT operation_id,state,amount_minor FROM commerce_db.refund_operation "
            f"WHERE line_id='{line_id}' ORDER BY reserved_at DESC LIMIT 1")
        report.check("Commerce recorded one successful full-line refund", str(operation), f"SUCCEEDED {amount}",
                     len(operation) == 1 and operation[0][1:] == ["SUCCEEDED", str(amount)])
        order_id = str(uuid.UUID(base.scalar(
            f"SELECT order_id FROM commerce_db.order_line WHERE line_id='{line_id}'")))
        ledger = _rows(
            "SELECT paid_amount,refunded_amount,reserved_refund_amount FROM commerce_db.payment_ledger "
            f"WHERE order_id='{order_id}'")
        report.check("ledger paid=refunded and no reserve remains", str(ledger), f"{amount} {amount} 0",
                     ledger == [[str(amount), str(amount), "0"]])
        slot = _rows(f"SELECT state FROM commerce_db.line_refund WHERE line_id='{line_id}'")
        report.check("line's one refund slot is consumed", str(slot), "CONSUMED", slot == [["CONSUMED"]])
        callbacks = _rows(
            "SELECT kind,disposition FROM case_db.agent_callback "
            f"WHERE case_id='{case_id}' ORDER BY received_at")
        report.check("Case accepted the run's two callbacks", str(callbacks), "STARTED/PROPOSAL ACCEPTED",
                     callbacks == [["STARTED", "ACCEPTED"], ["PROPOSAL", "ACCEPTED"]])
        if len(operation) == 1:
            with sqlite3.connect((output / "provider.sqlite3").as_uri() + "?mode=ro", uri=True) as provider:
                provider_row = provider.execute(
                    "SELECT state,amount_minor FROM refund_request WHERE operation_id=?", (operation[0][0],)
                ).fetchone()
                attempts = provider.execute(
                    "SELECT COUNT(*) FROM request_attempt WHERE operation_id=?", (operation[0][0],)
                ).fetchone()[0]
            report.check("provider settled the same operation once", f"{provider_row} attempts={attempts}",
                         f"SUCCEEDED {amount}, one attempt",
                         provider_row == ("SUCCEEDED", amount) and attempts == 1)
        verdict = not report.failures
        report.finish("PASSED" if verdict else "FAILED: " + "; ".join(report.failures))
        return 0 if verdict else 1
    except Exception as unexpected:  # noqa: BLE001 - preserve the failed boundary and raw logs
        import traceback
        report.note(traceback.format_exc())
        report.finish(f"FAILED: {unexpected}")
        return 1
    finally:
        owned = ((case_proc, chain.CASE_PORT), (commerce_proc, chain.COMMERCE_PORT),
                 (agent_proc, agent_port if agent_proc else 0))
        for proc, port in owned:
            if proc is not None:
                chain.stop(proc, port)


if __name__ == "__main__":
    sys.exit(main())
