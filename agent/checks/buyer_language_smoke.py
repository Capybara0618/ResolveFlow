"""Opt-in, at most 30 paid requests through the production support SDK loop.

Only the model is live. Facts/policies/history are explicit synthetic fixtures;
no business service, database, refund endpoint or ordinary worker is started.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml

from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guide import guide_source
from resolveflow.support.progress import ProgressReporter
from resolveflow.support.protocol import SupportFailure, SupportInput

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 30
POLICY = ROOT / "fixtures/policies/bundles/policy-logistics-2026.10.yaml"
DEFAULT_OUTPUT = ROOT / "tmp/buyer-language-smoke-v1/runtime-results.json"
LEDGER = ROOT / "tmp/evaluation-live-budget.json"
CASES = [
    {"id": "signed", "shipment": "DELIVERED", "turns": [
        "物流显示签收了，但我没收到，家人和代收点也没找到，现在怎么办？"]},
    {"id": "transit", "shipment": "IN_TRANSIT", "turns": ["耳机怎么还没到？帮我看看现在到哪了，要怎么处理？"]},
    {"id": "policy", "shipment": "DELIVERED", "turns": ["耳机外壳裂了能退吗？我先问一下条件，暂时不申请。"]},
    {"id": "refund", "shipment": "LOST", "turns": ["耳机物流确认丢了，我想退款，帮我整理申请原因，我确认后再提交。"]},
    {"id": "failure-correction", "shipment": "UNKNOWN", "fail_shipment": True, "turns": [
        "帮我看看耳机的物流，包裹一直没收到。",
        "更正一下，包裹刚找到了，之前说没收到已经不准确了，先不用查，也不用退款。"]},
]
CASES_V2 = [
    {"id": "signed-v2", "shipment": "DELIVERED", "turns": [
        "耳机显示送到了，可我和家里人都没拿到，驿站也说没有。接下来我该找谁处理？"]},
    {"id": "transit-v2", "shipment": "IN_TRANSIT", "turns": [
        "这副耳机还没送到，能看出运到哪里、什么时候能到吗？"]},
    {"id": "policy-v2", "shipment": "DELIVERED", "turns": [
        "我先了解一下：如果收到耳机发现外壳开裂，通常能申请退款吗？现在先别申请。"]},
    {"id": "refund-v2", "shipment": "LOST", "turns": [
        "耳机一直没收到，物流说丢了。请帮我准备退款原因，等我核对后再提交。"]},
    {"id": "failure-correction-v2", "shipment": "UNKNOWN", "fail_shipment": True, "turns": [
        "我的耳机还没收到，查查最新配送情况。",
        "找到了，刚才邻居送过来了。更正之前没收到的情况，别再查了，也不用退款。"]},
]
CASES_BUYER_VIEW = [
    {"id": "buyer-view-signed", "shipment": "DELIVERED", "turns": [
        "耳机标着已经送达，我本人没拿到，家里和快递站都问过了也没有。现在应该找谁帮我？"]},
    {"id": "buyer-view-transit", "shipment": "IN_TRANSIT", "turns": [
        "能帮我看下这副耳机现在到哪个地方了，大概哪天送到？"]},
    {"id": "buyer-view-policy", "shipment": "DELIVERED", "turns": [
        "假如耳机送来时外壳就是裂的，能不能退款？我只是提前了解，不要替我办理。"]},
    {"id": "buyer-view-refund", "shipment": "LOST", "turns": [
        "耳机没收到，快递那边说弄丢了。先帮我写退款原因，我自己看过再确认。"]},
    {"id": "buyer-view-failure-correction", "shipment": "UNKNOWN", "fail_shipment": True, "turns": [
        "查一下我这副耳机的配送进展，一直没见到包裹。",
        "不用继续查了，楼下邻居刚把耳机拿给我，之前说没收到的情况更正一下，也不退款了。"]},
    {"id": "buyer-view-multiple", "shipment": "LOST", "turns": [
        "耳机没送到，快递说包裹丢了，帮我准备退款原因，先不提交。另外问一下：把问题交给商家时，我能自己选哪些聊天原文给商家看吗，具体怎么选？"]},
]


def persist(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


@contextmanager
def ledger_lock(path: Path):
    lock = path.with_suffix(path.suffix + ".lock")
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, str(os.getpid()).encode())
        yield
    finally:
        os.close(descriptor)
        lock.unlink()


class Allowance:
    def __init__(self, path: Path, limit: int = LIMIT, *, batch_start: int | None = None):
        self.path, self.limit = path, limit
        self.value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"used": 0}
        used = self.value["used"]
        self.start = used if batch_start is None else batch_start
        if (type(used) is not int or type(self.start) is not int or not 0 <= self.start <= used
                or used - self.start > limit or not 0 <= limit <= LIMIT):
            raise ValueError("invalid request allowance")

    def consume(self) -> None:
        if self.value["used"] - self.start >= self.limit:
            raise SupportFailure("SMOKE_REQUEST_LIMIT")
        self.value["used"] += 1
        persist(self.path, self.value)  # Count before transmission, including failed requests.


class RecordedModel(StreamingLiveModelClient):
    def __init__(self, allowance: Allowance, row: dict[str, Any], save: Any, **kwargs: Any):
        super().__init__(**kwargs)
        self.allowance, self.row, self.save = allowance, row, save

    def _send(self, payload: bytes, headers: dict[str, str]):
        self.allowance.consume()
        entry = {"request": json.loads(payload), "state": "STARTED"}
        self.row["models"].append(entry)
        self.save()
        start = time.monotonic()
        try:
            response = super()._send(payload, headers)
            entry.update(state="RETURNED", status=response.status)
            try:
                entry["response"] = json.loads(response.body)
            except ValueError:
                entry["response_text"] = response.body.decode("utf-8", errors="replace")
            return response
        except Exception as error:
            entry.update(state="ERROR", error_type=type(error).__name__)
            raise
        finally:
            entry.update(elapsed_ms=round((time.monotonic() - start) * 1000), stream=self.last_stream)
            self.save()


class SyntheticSources:
    def __init__(self, case: dict[str, Any], request: SupportInput, row: dict[str, Any]):
        self.case, self.request, self.row = case, request, row

    def read(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.row["tools"].append({"name": name, "arguments": arguments})
        if name == "get_support_guide":
            return guide_source()
        if name == "get_order_context":
            return {"source_type": "ORDER", "version": 2, "data": {"synthetic": True, "order_line": {
                "line_id": self.request.line_id, "product_name": "无线降噪耳机", "quantity": 1,
                "status": "PAID", "line_paid_amount": 32900, "currency": "CNY"}}}
        if name == "get_shipment_trace":
            if self.case.get("fail_shipment"):
                return {"error": "SOURCE_UNAVAILABLE", "retryable": False}
            return {"source_type": "SHIPMENT", "version": 3, "data": {"synthetic": True,
                "line_id": self.request.line_id, "status": self.case["shipment"],
                "carrier_conclusion": self.case["shipment"], "events": []}}
        if name == "read_history":
            history = self.request.context["history"]
            return {"source_type": "CONVERSATION", "version": self.request.input_version,
                    "data": {"messages": history[-arguments.get("limit", 5):]}}
        raise ValueError("unsupported read")

    def search(self, query: str, top_k: int, *, sub_queries: list[str] | None = None) -> list[dict[str, Any]]:
        self.row["tools"].append({"name": "search_policy", "query": query, "top_k": top_k,
                                  "sub_queries": sub_queries})
        policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
        # Complete small synthetic policy bundle, like production small_context; not a retrieval benchmark.
        return [{"source_type": "POLICY", "version": policy["version"], "title": rule["title"],
                 "data": {"rule_id": rule["rule_id"], "text": rule["text"], "synthetic": True}}
                for rule in policy["rules"]]


def request_for(case: dict[str, Any], index: int, history: list[dict[str, Any]], previous: Any) -> SupportInput:
    conversation = str(uuid.uuid5(uuid.NAMESPACE_URL, "buyer-language-smoke-v1:" + case["id"]))
    sequence = max((m["sequence"] for m in history), default=0) + 1
    text = case["turns"][index]
    history.append({"message_id": str(uuid.uuid4()), "sequence": sequence, "author": "CUSTOMER",
                    "recipient": "ASSISTANT", "text": text})
    context = {"product": {"name": "无线降噪耳机", "quantity": 1, "amount_minor": 32900, "currency": "CNY"},
        "policy_manifest": {"merchant_id": "M-1001", "bundle_ids": ["policy-logistics-2026.10"],
                            "manifest_hash": hashlib.sha256(POLICY.read_bytes()).hexdigest()},
        "current_request": text, "history": deepcopy(history),
        "conversation_state": {"has_ticket": False, "ticket_status": "NONE",
                               "current_recipient": "ASSISTANT", "default_recipient": "ASSISTANT"}}
    if previous:
        accepted = previous.get("conversation_update") or previous.get("answer") or {}
        if accepted.get("task_state", {}).get("tasks"):
            context["previous_tasks"] = {"origin": "MODEL_PREVIOUS_TURN", "input_version": previous["input_version"],
                                         "tasks": accepted["task_state"]["tasks"]}
        if accepted.get("customer_memory"):
            context["previous_customer_memory"] = accepted["customer_memory"]
    return SupportInput(run_id=str(uuid.uuid4()), conversation_id=conversation, input_version=sequence,
        merchant_id="M-1001", customer_id="C-SYNTHETIC-SMOKE", line_id="buyer-language-synthetic-line",
        deadline_at=datetime.now(UTC) + timedelta(seconds=120), context=context)


def execute(output: Path, *, cases: list[dict[str, Any]] | None = None, batch_start: int | None = None,
            limit: int = LIMIT) -> None:
    if output.exists():
        raise FileExistsError("existing run retained; never automatically repeat paid checks")
    key = os.environ.get("RESOLVEFLOW_MODEL_API_KEY") or os.environ.get("Deepseek_API_KEY")
    if not key:
        raise ValueError("model key missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [Path(__file__), POLICY, *sorted((ROOT / "agent/src/resolveflow/support").glob("*.py")),
             *sorted((ROOT / "agent/src/resolveflow/harness").glob("*.py"))]
    selected = CASES if cases is None else cases
    report: dict[str, Any] = {"scope": "real model + production SDK loop; synthetic sources; no business writes",
        "limit": limit, "cases": selected, "rows": [], "state": "PREPARED",
        "files": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    persist(output, report)
    with ledger_lock(LEDGER):
        allowance = Allowance(LEDGER, limit=limit, batch_start=batch_start)
        report.update(state="RUNNING", usage_before=allowance.value["used"], batch_start=allowance.start)
        try:
            for case in selected:
                history: list[dict[str, Any]] = []
                previous = None
                for index in range(len(case["turns"])):
                    if allowance.value["used"] - allowance.start >= allowance.limit:
                        report["stopped_at_limit"] = True
                        break
                    request = request_for(case, index, history, previous)
                    row: dict[str, Any] = {"case": case["id"], "turn": index + 1,
                        "input": request.model_dump(mode="json"), "models": [], "tools": [], "events": []}
                    report["rows"].append(row)
                    def save():
                        persist(output, report)
                    model = RecordedModel(allowance, row, save, provider="deepseek", model_id="deepseek-flash",
                        endpoint="https://api.deepseek.com/chat/completions", api_key=key, timeout_seconds=30,
                        parameters={"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
                                    "temperature": 0})

                    def receive(call: httpx.Request, row=row):
                        row["events"].extend(json.loads(call.content)["events"])
                        return httpx.Response(200)

                    progress = ProgressReporter("http://synthetic.invalid", request.run_id, "synthetic-only",
                                                transport=httpx.MockTransport(receive))
                    model.on_content = progress.content
                    try:
                        start = time.monotonic()
                        result = SupportAgent(request, model, SyntheticSources(case, request, row),
                            architecture="orchestrated-v1", provider_capacity=32768, progress=progress).run()
                        row.update(result=result, elapsed_ms=round((time.monotonic() - start) * 1000))
                    finally:
                        progress.close()
                    row["progress_failure"] = progress.failure
                    previous = result
                    if result.get("answer"):
                        history.append({"message_id": str(uuid.uuid4()), "sequence": request.input_version + 1,
                            "author": "ASSISTANT", "recipient": "CUSTOMER", "text": result["answer"]["text"]})
                    save()
                    print(json.dumps({"case": case["id"], "turn": index + 1, "status": result["status"],
                        "reason": result["reason"], "attempts": len(row["models"])}, ensure_ascii=False), flush=True)
            report["state"] = "FINISHED"
        finally:
            report["usage_after"] = allowance.value["used"]
            report["new_attempts"] = allowance.value["used"] - report["usage_before"]
            report["batch_attempts"] = allowance.value["used"] - allowance.start
            persist(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="explicitly permit at most 30 paid model requests")
    parser.add_argument("--profile", choices=["v1", "v2", "buyer-view"], default="v1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append", dest="case_ids", help="explicit named subset; no implicit reruns")
    parser.add_argument("--batch-start", type=int, help="preserve the original batch's absolute request ceiling")
    parser.add_argument("--max-requests", type=int, default=LIMIT, help="authorized request ceiling, at most 30")
    arguments = parser.parse_args()
    if not 1 <= arguments.max_requests <= LIMIT:
        parser.error("max-requests must be between 1 and 30")
    selected = {"v1": CASES, "v2": CASES_V2, "buyer-view": CASES_BUYER_VIEW}[arguments.profile]
    if arguments.case_ids:
        if len(set(arguments.case_ids)) != len(arguments.case_ids) or not set(arguments.case_ids) <= {
            case["id"] for case in selected
        }:
            parser.error("unknown or repeated case")
        selected = [case for case in selected if case["id"] in arguments.case_ids]
    output = arguments.output or {"v1": DEFAULT_OUTPUT,
        "v2": ROOT / "tmp/buyer-language-smoke-v2/runtime-results.json",
        "buyer-view": ROOT / "tmp/buyer-view-live-v1/runtime-results.json"}[arguments.profile]
    if arguments.execute:
        execute(output, cases=selected, batch_start=arguments.batch_start, limit=arguments.max_requests)
    else:
        print(json.dumps({"cases": len(selected), "turns": sum(len(c["turns"]) for c in selected),
                          "max_paid_requests": arguments.max_requests, "paid_requests_sent": 0}))
