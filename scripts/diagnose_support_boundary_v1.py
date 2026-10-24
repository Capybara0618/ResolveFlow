"""Offline publication diagnostics on saved candidates, never a new model-quality score."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from resolveflow.harness.context import canonical_json
from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import SupportInput

ROOT = Path(__file__).resolve().parents[1]
SAVED = ROOT / "reports/customer-current-evaluation-v1/agent-runtime.json"
CASES = {("D03", 1), ("D06", 2), ("D08", 1), ("D10", 2)}


class SavedModel(MockModelClient):
    provider = "deepseek"
    model_id = "deepseek-flash"


class SavedSources:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self.responses: dict[str, list[Any]] = {}
        self.calls: list[dict[str, Any]] = []
        for call in calls:
            if call["kind"] == "tool":
                key = canonical_json(call["request_json"])
                self.responses.setdefault(key, []).append(deepcopy(call["response_json"]))

    def invoke(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        key = canonical_json({"name": name, "arguments": arguments})
        responses = self.responses.get(key, [])
        if responses:
            result = responses.pop(0)
            origin = "SAVED_TOOL_RESULT"
        elif name == "get_support_guide" and not arguments:
            result, origin = [guide_source()], "CURRENT_PUBLIC_GUIDE_PRELOAD"
        else:
            raise AssertionError(f"offline record missing: {key}")
        self.calls.append({"name": name, "arguments": arguments, "origin": origin})
        return deepcopy(result)

    def read(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self.invoke(name, arguments)
        assert len(result) == 1
        return result[0]

    def search(self, query: str, top_k: int, **options: Any) -> list[Any]:
        return self.invoke("search_policy", {"query": query, "top_k": top_k, **options})


def diagnose() -> dict[str, Any]:
    before = hashlib.sha256(SAVED.read_bytes()).hexdigest()
    original = json.loads(SAVED.read_text(encoding="utf-8"))
    rows = []
    connect = socket.socket.connect
    for row in original["rows"]:
        if (row["id"], row["turn"]) not in CASES:
            continue
        calls = sorted((c for c in original["all_calls"] if c["run_id"] == row["input"]["run_id"]),
                       key=lambda c: c["position"])
        decisions = [c["response_json"]["decision"] for c in calls if c["kind"] == "model"]
        request = SupportInput.model_validate({**row["input"],
            "deadline_at": datetime.now(UTC) + timedelta(seconds=120)})
        model = SavedModel(script=deepcopy(decisions), mode="live")
        sources = SavedSources(calls)
        def internal_only(sock: socket.socket, address: Any) -> None:
            # Windows asyncio creates a loopback socketpair for its own wakeup pipe.
            if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
                raise AssertionError("offline external network forbidden")
            connect(sock, address)

        with (patch.object(socket.socket, "connect", internal_only),
              patch.object(httpx.Client, "send", side_effect=AssertionError("offline HTTP forbidden")),
              patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("offline HTTP forbidden"))):
            agent = SupportAgent(request, model, sources, architecture="orchestrated-v1")
            result = agent.run()
        composed = [d for d in decisions[:model.calls] if d.get("kind") == "RESPOND"]
        accepted_texts = [p["text"] for p in composed[-1]["parts"]] if composed else []
        final_text = (result.get("answer") or {}).get("text", "")
        rows.append({"id": row["id"], "turn": row["turn"], "original_status": row["result"]["status"],
                     "diagnostic_status": result["status"], "diagnostic_reason": result["reason"],
                     "scripted_decisions_consumed": model.calls, "repair_count": agent.repairs,
                     "direct_explanations_preserved": bool(accepted_texts)
                         and all(text in final_text for text in accepted_texts),
                     "has_unrequested_summary": any((result.get("answer") or {}).get(k)
                         for k in ("refund_summary", "handoff_summary")),
                     "tool_results": sources.calls, "diagnostic_answer": result.get("answer")})
    assert hashlib.sha256(SAVED.read_bytes()).hexdigest() == before
    return {"version": "support-boundary-offline-candidate-v1", "source_sha256": before,
            "network": "HTTP and external socket connects forbidden; Windows asyncio internal loopback allowed",
            "provider_requests": 0, "business_writes": 0,
            "transformations": ["Only deadline advanced for offline execution",
                "Saved model decisions reused verbatim", "Current public guide may be preloaded before triage",
                "No new generation, old manifest replay or historical score update"],
            "limits": "Checks publication and text preservation only; not semantic quality or new-model adoption",
            "passed": len(rows) == len(CASES) and all(r["diagnostic_status"] == "SUCCEEDED"
                and r["direct_explanations_preserved"] and not r["has_unrequested_summary"] for r in rows),
            "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = diagnose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": result["passed"], "cases": len(result["rows"]), "provider_requests": 0}))
    raise SystemExit(0 if result["passed"] else 1)
