"""Offline, synthetic actual ContextPacket audit; never touches business DB or model APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent" / "src"))

from resolveflow.contracts.core_models import (
    CoreToolError,
    ToolObservation,
)
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.context import ContextBuilder, extract_facts
from resolveflow.harness.facts import FactsView
from resolveflow.harness.verifier import ProposalVerifier
from resolveflow.harness.vocabulary import HARNESS_SYSTEM_PROMPT


def observation(name: str, identifier: str, result: dict, *, failed: bool = False) -> ToolObservation:
    content = json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
    fields = {"observation_id": identifier, "tool_name": name, "source_type": EvidenceSourceType.ORDER_LINE,
                  "source_ref": f"order:{identifier}", "observed_at": "2026-10-04T00:00:00Z"}
    if failed:
        return ToolObservation(**fields, error=CoreToolError(code="NOT_FOUND", message="合成读取失败",
                                                            retryable=False, source_ref=fields["source_ref"]))
    return ToolObservation(**fields, result=result, source_version="1", content_hash=hashlib.sha256(content).hexdigest())


def scenario(case: dict) -> tuple[list[ToolObservation], list[dict]]:
    order = observation("get_order_context", "order-1", {
        "status": case["state"], "line_paid_amount": case.get("amount", 69900), "currency": "CNY", "quantity": 1,
        "paid_at": "2026-10-03T01:00:00Z", "product_name": "合成显示器", "sku": "SYNTHETIC-01",
    }, failed=case.get("read_failed", False))
    shipment = observation("get_shipment_trace", "shipment-1", {
        "carrier_conclusion": case["carrier"], "status": "IN_TRANSIT", "scan_count": 1,
        "last_scan_at": "2026-10-03T02:00:00Z", "events": [{"text": "明确标注的合成物流记录"}],
    })
    rules = [{"bundle_id": "synthetic-policy", "version": "v1", "rule_id": "R-LOST", "chunk_id": "c-1",
                  "content_hash": "a" * 64, "title": "丢失退款", "text": "承运商确认丢失且无有效签收，可整行退款。"},
             {"bundle_id": "synthetic-policy", "version": "v1", "rule_id": "R-EXCEPTION", "chunk_id": "c-2",
                  "content_hash": "b" * 64, "title": "金额例外", "text": "例外：超过500000分必须人工核验，不能忽略例外。"}]
    if case.get("no_hits"):
        rules = []
    searches = [observation("search_policy", f"search-{i}", {"hits": rules, "hit_count": len(rules),
                                                             "query": f"退款条件查询{i}"})
                for i in range(case["searches"])]
    return [order, shipment, *searches], rules


def audit(case: dict) -> dict:
    observations, rules = scenario(case)
    view = FactsView()
    for item in observations:
        extract_facts(view, item)
    packet = ContextBuilder(system_prompt=HARNESS_SYSTEM_PROMPT, provider_capacity=32768).build(
        run_id="audit-run", case_id="audit-case", line_id="audit-line", input_revision=1,
        step=len(observations) + 1, description=case["description"], manifest_id="synthetic-audit",
        observations=observations, view=view, tool_schema={})
    text = "\n".join(message["content"] for message in packet.messages)
    refs = [{"observation_id": item.observation_id, "source_ref": item.source_ref,
                 "source_version": item.source_version, "content_hash": item.content_hash}
            for item in observations[:2] if item.error is None] if case["citations"] else []
    policies = [{key: rule[key] for key in ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")}
                for rule in rules] if case["citations"] else []
    result = ProposalVerifier(observations, frozenset({"synthetic-policy"})).verify_citations(
        recommended_action=case["action"], evidence_refs=refs, policy_refs=policies)
    return {"id": case["id"], "input_tokens": packet.input_tokens, "token_count_mode": packet.token_count_mode,
                "protected_fact_hash": packet.protected_fact_hash,
                "policy_text_occurrences": {rule["rule_id"]: text.count(rule["text"]) for rule in rules},
                "proposed_action": case["action"], "verifier_ok": result.ok, "refusal_codes": list(result.reason_codes),
                "messages": list(packet.messages), "context_hash": packet.context_hash}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    fixture = ROOT / "agent/tests/fixtures/context_quality.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
    rows = [audit(case) for case in cases]
    document = {"mode": "synthetic-offline-no-model-no-db", "fixture_hash": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                    "cases": rows, "total_estimated_input_tokens": sum(row["input_tokens"] for row in rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in document.items() if key != "cases"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
