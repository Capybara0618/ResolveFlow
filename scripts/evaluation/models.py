"""Capture actual requests and bound the combined live experiment, without storing credentials."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import asdict

from resolveflow.harness.live_model import ModelRefusedError
from resolveflow.harness.model import MODEL_MODE_MOCK, ModelReply, ModelUsage


@contextmanager
def live_guard(path):
    """One live process per shared budget; crashes leave a visible lock, never reset spend."""
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError("Live budget is locked; confirm its process stopped before removing the lock") from error
    try:
        os.write(descriptor, str(os.getpid()).encode())
        yield
    finally:
        os.close(descriptor)
        lock.unlink()


class CaptureModel:
    def __init__(self, client, allowance=None, on_record=None):
        self.client = client
        self.records = []
        self.allowance = allowance
        self.on_record = on_record

    def __getattr__(self, name):
        return getattr(self.client, name)

    def decide(self, **kwargs):
        if self.allowance is not None:
            if self.allowance["used"] >= self.allowance["limit"]:
                raise ModelRefusedError("Evaluation total transmission cap reached")
            rendered_bytes = sum(
                len(block.text.encode())
                for message in kwargs["messages"]
                for block in message.get_content_blocks()
                if hasattr(block, "text")
            )
            if kwargs["max_output_tokens"] > 1024 or rendered_bytes > 11000:
                raise ModelRefusedError("Evaluation monetary reservation input/output bound exceeded")
            # Peak non-cache prices verified on official docs 2026-10-04. UTF8 bytes plus 1K wrapper
            # is a conservative input-token estimate, not the provider's invoice or tokenizer guarantee.
            reserved = ((rendered_bytes + 1024) * 0.30 + kwargs["max_output_tokens"] * 1.20) / 1_000_000
            if self.allowance.get("reserved_usd", 0) + reserved > 0.50:
                raise ModelRefusedError("Evaluation USD 0.50 conservative reservation cap reached")
            self.allowance["used"] += 1
            self.allowance["reserved_usd"] = self.allowance.get("reserved_usd", 0) + reserved
            if "save" in self.allowance:
                self.allowance["save"]()
        messages = [
            {
                "role": str(message.role),
                "content": "\n".join(block.text for block in message.get_content_blocks() if hasattr(block, "text")),
            }
            for message in kwargs["messages"]
        ]
        record = {"messages": messages, "system": kwargs["system"], "max_output_tokens": kwargs["max_output_tokens"]}
        packet = kwargs.get("sent_context")
        if packet is not None:
            record["context_measurement"] = {
                "input_estimate": packet.input_tokens,
                "cap": packet.input_cap,
                "token_count_mode": "ESTIMATED_UTF8_BYTES",
                "layers": packet.layers,
            }
        self.records.append(record)
        if self.on_record:
            self.on_record(self.records)
        try:
            reply = self.client.decide(**kwargs)
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
            if self.on_record:
                self.on_record(self.records)
            raise
        record.update(
            decision=reply.decision, usage=asdict(reply.usage), mode=reply.mode, model_alias=reply.model_alias
        )
        if self.on_record:
            self.on_record(self.records)
        return reply


class FixtureModel:
    """Explicit mock control-flow probe, reads observed facts; never claims LLM quality."""

    mode = MODEL_MODE_MOCK
    model_alias = "synthetic-control-flow-probe"

    def __init__(self):
        self.calls = 0

    def decide(self, **kwargs):
        self.calls += 1
        observed = kwargs["context"]["observations"]
        by_tool = {item["tool_name"]: item for item in observed}

        def read(name):
            return {"kind": "READ_TOOL", "tool_name": name, "arguments": {}}

        if "get_order_context" not in by_tool:
            decision = read("get_order_context")
        else:
            order = by_tool["get_order_context"].get("result") or {}
            unshipped = order.get("fulfillment_status") == "NOT_SHIPPED"
            if not unshipped and "get_shipment_trace" not in by_tool:
                decision = read("get_shipment_trace")
            elif not unshipped and "get_case_evidence" not in by_tool:
                decision = read("get_case_evidence")
            elif "search_policy" not in by_tool:
                shipment = (by_tool.get("get_shipment_trace") or {}).get("result") or {}
                query = "商品质量问题 人工核验" if shipment.get("status") == "DELIVERED" else "运输丢失 人工确认"
                decision = {
                    "kind": "SEARCH_POLICY",
                    "query": "已付款未发货" if unshipped else query,
                    "arguments": {"top_k": 2},
                }
            else:
                shipment = (by_tool.get("get_shipment_trace") or {}).get("result") or {}
                materials = kwargs["context"]["run"].get("review_context", {}).get("materials")
                if materials is None:  # Explicit legacy v1 fixture profile, not a live input channel.
                    materials = ((by_tool.get("get_case_evidence") or {}).get("result") or {}).get("materials", [])
                verified = any(
                    m.get("source_type") == "REVIEWER_VERIFICATION" and m.get("verification_result") == "CONFIRMED"
                    for m in materials
                )
                free = order.get("line_refund_state") == "FREE"
                paid = order.get("order_status") == "PAID" and bool(order.get("paid_at"))
                eligible = (
                    free
                    and paid
                    and (
                        (unshipped and order.get("fulfillment_version") == 1)
                        or (verified and shipment.get("status") in {"LOST", "DELIVERED"})
                    )
                )
                rid = (
                    "R-UNSHIPPED-001"
                    if unshipped
                    else ("R-LOST-001" if shipment.get("status") == "LOST" else "R-DMG-001")
                )
                hits = by_tool["search_policy"].get("result", {}).get("hits", [])
                hit = next((value for value in hits if value["rule_id"] == rid), None)
                eligible = eligible and hit is not None
                citations = [
                    {key: item[key] for key in ("observation_id", "source_ref", "source_version", "content_hash")}
                    for name, item in by_tool.items()
                    if name != "search_policy" and not item.get("error")
                ]
                decision = {
                    "kind": "PROPOSE",
                    "case_type": "DAMAGED" if rid == "R-DMG-001" else "LOGISTICS",
                    "recommended_action": "REFUND" if eligible else "MANUAL_REVIEW",
                    "reason_codes": ["SYNTHETIC_PROBE"],
                    "summary": "合成流程核对，最终仍须商家审批。",
                    "evidence_refs": citations,
                    "policy_refs": [
                        {key: hit[key] for key in ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")}
                    ]
                    if eligible
                    else [],
                }
        return ModelReply(
            decision=decision,
            usage=ModelUsage(input_tokens=1, output_tokens=1),
            mode=self.mode,
            model_alias=self.model_alias,
        )
