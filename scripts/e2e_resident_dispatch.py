"""C08.2: real Case dispatch -> resident Agent -> MCP read -> Case callback.

This deliberately ends before a human approval or refund. The model is an explicit mock script; Java,
MySQL, PostgreSQL, the AgentScope loop, and the MCP subprocess are real. Run from the repository root with
``agent/.venv/Scripts/python.exe scripts/e2e_resident_dispatch.py`` after starting the existing MySQL and
PostgreSQL containers. The driver never stops a process it did not start.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import UTC, datetime

import e2e_harness_java_tools as tools_driver
import e2e_refund_chain as chain
import e2e_transport_refund as base

ROOT = base.ROOT
CASE_PORT = chain.CASE_PORT
COMMERCE_PORT = chain.COMMERCE_PORT
AGENT_PYTHON = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"


def _callback_rows(case_id: str) -> list[list[str]]:
    case_id = str(uuid.UUID(case_id))
    return base.mysql_rows(
        "SELECT kind, disposition FROM case_db.agent_callback "  # noqa: S608 - canonical UUID only
        f"WHERE case_id = '{case_id}' ORDER BY received_at"
    )


def main() -> int:
    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S")
    output = ROOT / "reports" / "c08-resident-java" / stamp
    output.mkdir(parents=True, exist_ok=True)
    report = base.Report(output / "result.txt")
    report.head("# C08.2 Case dispatch -> resident Agent -> Case callback (mock model, real services)")
    report.head(f"run {stamp}")
    agent_proc = case_proc = commerce_proc = None
    try:
        if not chain.java_ports_available(report):
            report.finish("FAILED: Java service port occupied")
            return 1
        if base.mysql_rows("SELECT 1") != [["1"]]:
            report.finish("FAILED: MySQL unavailable")
            return 1

        amount = int(base.scalar("SELECT line_paid_amount FROM commerce_db.order_line WHERE line_id = '7001'"))
        agent_port = chain.free_port()
        script = output / "mock-decisions.json"
        script.write_text(json.dumps([
            {"kind": "READ_TOOL", "tool_name": "get_shipment_trace", "arguments": {"limit": 3}},
            {
                "kind": "PROPOSE", "case_type": "LOGISTICS", "recommended_action": "MANUAL_REVIEW",
                "reason_codes": ["LOGISTICS_REVIEW"],
                "summary": "Synthetic model requested a human logistics review after reading the shipment trace",
            },
        ]), encoding="utf-8")
        agent_url = f"http://127.0.0.1:{agent_port}"
        case_url = f"http://127.0.0.1:{CASE_PORT}"

        agent_proc = chain.start(
            "agent", [AGENT_PYTHON, "-m", "uvicorn", "resolveflow.api.app:app", "--host", "127.0.0.1",
                      "--port", str(agent_port), "--log-level", "warning"],
            base.child_env(
                RESOLVEFLOW_INVESTIGATION_ENABLED="1", RESOLVEFLOW_MODEL_MODE="mock",
                RESOLVEFLOW_MOCK_SCRIPT=str(script), RESOLVEFLOW_CASE_BASE_URL=case_url,
                RESOLVEFLOW_COMMERCE_BASE_URL=f"http://127.0.0.1:{COMMERCE_PORT}",
            ), report, output)
        commerce_proc = chain.start(
            "commerce-service", [base.JAVA_HOME / "bin" / "java", "-jar", base.COMMERCE_JAR],
            base.child_env(), report, output)
        case_proc = chain.start(
            "case-service",
            [base.JAVA_HOME / "bin" / "java", "-jar", chain.CASE_JAR,
             f"--resolveflow.agent.base-url={agent_url}", "--resolveflow.dispatch.enabled=true",
             "--resolveflow.dispatch.poll-interval-ms=500"],
            base.child_env(), report, output)

        started = time.monotonic()
        ready = (
            chain.wait_reachable("agent", f"{agent_url}/health", agent_proc, report)
            and chain.wait_health("commerce", f"http://127.0.0.1:{COMMERCE_PORT}/actuator/health",
                                  commerce_proc, report)
            and chain.wait_health("case", f"{case_url}/actuator/health", case_proc, report)
        )
        report.step("three services are healthy", ready, time.monotonic() - started)
        if not ready:
            report.finish("FAILED: service startup")
            return 1

        line_id, _, _ = chain.create_demo_line(amount, report)
        status, login = tools_driver.request_json(
            f"{case_url}/api/v1/auth/login", method="POST",
            body={"username": tools_driver.CUSTOMER, "password": tools_driver.CUSTOMER_PASSWORD})
        report.step("customer login", status == 200, 0, str(status))
        if status != 200:
            report.finish("FAILED: customer login")
            return 1
        status, created = tools_driver.request_json(
            f"{case_url}/api/v1/cases", method="POST", token=login["access_token"],
            headers={"Idempotency-Key": f"c08-resident-{line_id}"},
            body={"line_id": line_id, "description": "包裹多日无物流更新，请调查",
                  "requested_actions": ["REFUND"]})
        report.step("case opened", status == 201, 0, str(status) if status == 201 else f"{status} {created}")
        if status != 201:
            report.finish("FAILED: case creation")
            return 1
        case_id = str(uuid.UUID(created["case_id"]))
        run_id = str(uuid.UUID(tools_driver.agent_run_id_for(case_id, created["input_revision"])))
        report.note(f"case={case_id} run={run_id} line={line_id}")

        deadline = time.monotonic() + 90
        callbacks: list[list[str]] = []
        while time.monotonic() < deadline:
            callbacks = _callback_rows(case_id)
            if ["PROPOSAL", "ACCEPTED"] in callbacks:
                break
            if any(proc.poll() is not None for proc in (agent_proc, case_proc, commerce_proc)):
                break
            time.sleep(0.5)
        report.check("Case accepted a proposal callback", str(callbacks), "PROPOSAL ACCEPTED",
                     ["PROPOSAL", "ACCEPTED"] in callbacks)
        binding = base.mysql_rows(
            f"SELECT dispatch_status FROM case_db.agent_binding WHERE run_id = '{run_id}'")  # noqa: S608
        report.check("Case dispatched the bound run", str(binding), "DISPATCHED",
                     binding == [["DISPATCHED"]])
        status, run = tools_driver.request_json(
            f"{agent_url}/internal/v1/runs/{run_id}", token=tools_driver.mint_service_token("agent-service"))
        report.check("Agent completed after Case accepted the proposal",
                     str(run.get("status") if isinstance(run, dict) else run),
                     "COMPLETED", status == 200 and run.get("status") == "COMPLETED")
        case_state = base.mysql_rows(
            f"SELECT status FROM case_db.aftersale_case WHERE case_id = '{case_id}'")  # noqa: S608
        report.check("Case entered human review", str(case_state), "PENDING_REVIEW",
                     case_state == [["PENDING_REVIEW"]])
        verdict = not report.failures
        report.finish("PASSED" if verdict else "FAILED: " + "; ".join(report.failures))
        return 0 if verdict else 1
    except Exception as unexpected:  # noqa: BLE001 - report the failed boundary and preserve its logs
        import traceback
        report.note(traceback.format_exc())
        report.finish(f"FAILED: {unexpected}")
        return 1
    finally:
        owned = ((case_proc, CASE_PORT), (commerce_proc, COMMERCE_PORT),
                 (agent_proc, agent_port if agent_proc else 0))
        for proc, port in owned:
            if proc is not None:
                chain.stop(proc, port)


if __name__ == "__main__":
    sys.exit(main())
