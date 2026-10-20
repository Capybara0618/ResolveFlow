"""Read-only diagnosis of frozen L07/L08 evidence; no model API or business writes."""

import json
from pathlib import Path

import reviewer_demo as demo
from resolveflow.policies.index import PolicyIndex
from resolveflow.policies.retrieval import embedder
from resolveflow.runtime.db import Database


def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / "reports/customer-agent-live-v1"
    runtime = json.loads((directory / "runtime-results.json").read_text(encoding="utf-8"))
    settings = demo.settings_from_environ()
    demo.guard(settings)
    failed = next(v for v in runtime["turns"] if v["id"] == "L07")
    token = demo.mint_service_token("case-service", scope="commerce:read")
    status, value = demo.http(
        "GET", settings.commerce_url + "/internal/v1/order-lines/" + failed["line_id"] + "/shipment", token=token
    )
    result = {
        "l07": {
            "direct_shipment_http": status,
            "direct_shipment_response": value,
            "existing_fault_rows": demo.mysql_rows("SELECT * FROM commerce_db.shipment_simulation_fault", settings),
            "consultation_tool_fact": next(
                c["response_json"]
                for v in runtime["runs"]
                if v["case"] == "L07"
                for c in v["calls"]
                if c["kind"] == "tool" and c["request_json"]["name"] == "get_shipment_trace"
            ),
            "cause": "SupportAgentTurns.fact(shipment) calls shopping.fulfillment; MerchantTradeService.fulfillment "
            "reads shipment tables without ShipmentReadService.queryUnavailable check.",
        }
    }
    lost = next(v for v in runtime["runs"] if v["case"] == "L08")
    query = next(
        c["request_json"]["arguments"]["query"]
        for c in lost["calls"]
        if c["kind"] == "tool" and c["request_json"]["name"] == "search_policy"
    )
    manifest = lost["run"]["input_json"]["context"]["policy_manifest"]
    database = Database(settings.agent_dsn)
    try:
        index, encoder = PolicyIndex(database), embedder(local_path=str(demo.EMBEDDING_PATH))
        ranks = {}
        for path in ["dense", "bm25"]:
            hits = index.search(
                merchant_id=lost["run"]["input_json"]["merchant_id"],
                bundle_ids=manifest["bundle_ids"],
                manifest_hash=manifest["manifest_hash"],
                query=query,
                path=path,
                top_k=5,
                embedder=encoder if path == "dense" else None,
                generation_ids=lost["run"]["generations_json"],
            )
            ranks[path] = [
                {"rank": n + 1, "rule_id": h.rule_id, "title": h.title, "score": h.score} for n, h in enumerate(hits)
            ]
        with database.connection() as conn:
            times = conn.execute(
                "SELECT kind,position,created_at FROM support_agent_call WHERE run_id=%s ORDER BY created_at",
                (next(v["run"]["run_id"] for v in runtime["runs"] if v["case"] == "L02"),),
            ).fetchall()
        result["l08"] = {
            "actual_query": query,
            "ranks_on_same_fixed_generation": ranks,
            "diagnostic_only": True,
            "production_changed": False,
            "model_calls": 0,
        }
        result["l02_call_start_times"] = times
    finally:
        database.close()
    (directory / "diagnostics.json").write_bytes(
        (json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    )
    print(json.dumps({"direct_shipment_http": status, "ranks": ranks, "model_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
