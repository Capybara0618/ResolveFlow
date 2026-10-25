"""Raw external fixtures and provider accounting; no production Agent imports."""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path

import httpx

from scripts.evaluation.basic_customer_workflow import ModelReply

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def wire_tokenizer():
    from tokenizers import Tokenizer
    compressed = (ROOT / "agent/src/resolveflow/assets/deepseek-v41/tokenizer.json.gz").read_bytes()
    if hashlib.sha256(compressed).hexdigest() != "a06de40d7aa5f5f2486dea7d0d516420edfe07e1d946b5ad2c57e73851de3008":
        raise ValueError("shared tokenizer asset differs")
    tokenizer = Tokenizer.from_str(gzip.decompress(compressed).decode("utf-8"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def wire_tokens(body):
    tokenizer = wire_tokenizer()
    wire = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return max(len(tokenizer.encode(wire, add_special_tokens=False).ids),
        sum(len(tokenizer.encode(m['content'], add_special_tokens=False).ids) for m in body['messages']))


class RequestAllowance:
    def __init__(self, ledger, start, limit):
        if limit < 0 or start < 0 or ledger["used"] < start:
            raise ValueError("invalid request allowance")
        self.ledger, self.start, self.limit = ledger, start, limit

    def consume(self):
        if self.ledger["used"] - self.start >= self.limit:
            raise RuntimeError("BUDGET_EXHAUSTED")
        self.ledger["used"] += 1
        self.ledger["save"]()


def text_prefix(raw):
    """Decode the top-level text string only; JSON/progress characters are not body text."""
    decoder, at = json.JSONDecoder(), 0
    raw = raw.lstrip()
    if not raw.startswith("{"):
        return None
    at = 1
    try:
        while at < len(raw):
            while at < len(raw) and raw[at] in " \r\n\t,":
                at += 1
            key, at = decoder.raw_decode(raw, at)
            while at < len(raw) and raw[at].isspace():
                at += 1
            if at >= len(raw) or raw[at] != ":":
                return None
            at += 1
            while at < len(raw) and raw[at].isspace():
                at += 1
            if key != "text":
                _, at = decoder.raw_decode(raw, at)
                continue
            if at >= len(raw) or raw[at] != '"':
                return None
            try:
                value, _ = decoder.raw_decode(raw, at)
                return value if isinstance(value, str) and value.strip() else None
            except ValueError:
                # At most an incomplete escape (backslash or six-character unicode escape).
                partial = raw[at:]
                for trim in range(min(7, len(partial))):
                    try:
                        value = json.loads((partial[:-trim] if trim else partial) + '"')
                        if value.strip():
                            return value
                    except ValueError:
                        pass
                return None
    except ValueError:
        return None
    return None


class PlainChatClient:
    def __init__(self, client, endpoint, api_key, allowance):
        self.client, self.endpoint, self.api_key, self.allowance = client, endpoint, api_key, allowance
        self.last_sent, self.last_request = False, None

    def complete(self, *, stage, messages, max_output_tokens):
        self.last_sent = False
        body = {"model": "deepseek-flash", "messages": messages, "max_tokens": max_output_tokens,
            "temperature": 0, "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
            "stream": True, "stream_options": {"include_usage": True}}
        self.last_request = body
        if wire_tokens(body) > 8192:
            raise ValueError("INPUT_WINDOW_EXCEEDED")
        self.allowance.consume()
        self.last_sent = True
        started, text, usage, first, finished, done = time.monotonic(), "", None, None, False, False
        with self.client.stream("POST", self.endpoint, json=body,
                headers={"Authorization": "Bearer " + self.api_key}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    done = True
                    break
                packet = json.loads(value)
                provider_usage = packet.get("usage")
                if provider_usage is not None:
                    input_count, output_count = (provider_usage.get(k) for k in ("prompt_tokens", "completion_tokens"))
                    if all(type(n) is int and n >= 0 for n in (input_count, output_count)):
                        usage = {"input_tokens": input_count, "output_tokens": output_count, "estimated": False}
                choices = packet.get("choices") or []
                if choices:
                    text += choices[0].get("delta", {}).get("content") or ""
                    finished = finished or choices[0].get("finish_reason") == "stop"
                if stage == "ANSWER" and first is None and text_prefix(text):
                    first = (time.monotonic() - started) * 1000
        if not done or not finished or not text:
            raise ValueError("provider stream has no complete finished response")
        return ModelReply(text, usage, "live", first_text_ms=first)


def guide_data():
    raw = (ROOT / "agent/src/resolveflow/assets/support-guide-v3.json").read_bytes()
    value = json.loads(raw)
    if (value["version"] != "2026.10.23-v3" or value["authority"] != "APPLICATION_GUIDE"
            or hashlib.sha256(value["text"].encode()).hexdigest() != value["text_sha256"]):
        raise ValueError("public guide version/text differs")
    return {"source_type": "KNOWLEDGE", "version": value["version"], "title": "售后咨询使用指南",
        "data": {**{k: v for k, v in value.items() if k != "version"},
            "knowledge_sha256": hashlib.sha256(raw).hexdigest()}}


def transport_for(snapshot, identity, archive, paths):
    prefix = "/internal/v1/support/turns/" + identity["run_id"]

    def respond(request):
        path = request.url.path
        paths.append({"method": request.method, "path": path, "query": str(request.url.query, "ascii")})
        if request.method != "GET" or not path.startswith(prefix + "/"):
            return httpx.Response(403, json={"error": "FORBIDDEN"})
        suffix = path[len(prefix):]
        if suffix == "/current":
            return httpx.Response(200, json={k: identity[k] for k in ("conversation_id", "input_version")})
        if suffix == "/facts/history":
            try:
                before, limit = (int(request.url.params[k]) for k in ("before_sequence", "limit"))
                if before <= 0 or not 1 <= limit <= 20:
                    raise ValueError("invalid history range")
            except (ValueError, KeyError):
                return httpx.Response(400, json={"error": "INVALID_HISTORY_RANGE"})
            messages = [m for m in archive if m["sequence"] < before][-limit:]
            return httpx.Response(200, json={"version": identity["input_version"], "messages": messages})
        name = {"/facts/order": "get_order_context", "/facts/shipment": "get_shipment_trace"}.get(suffix)
        if name is None:
            return httpx.Response(403, json={"error": "FORBIDDEN"})
        return httpx.Response(snapshot.get("http_status", {}).get(name, 200), json=snapshot["facts"][name])

    return respond


class RawPolicyService:
    """This cohort binds tiny complete sets; fail instead of changing retrieval algorithms."""
    def __init__(self, index):
        self.index = index

    def search(self, merchant_id, manifest, pinned_generations, query):
        if manifest.get("merchant_id") != merchant_id:
            raise ValueError("policy scope mismatch")
        ready = self.index.require_ready(manifest["bundle_ids"], manifest["manifest_hash"])
        if any(g.merchant_id != merchant_id for g in ready):
            raise ValueError("policy scope mismatch")
        if {g.bundle_id: g.generation_id for g in ready} != pinned_generations:
            raise ValueError("pinned policy generation mismatch")
        hits = self.index.small_context(merchant_id=merchant_id, bundle_ids=manifest["bundle_ids"],
            manifest_hash=manifest["manifest_hash"], generation_ids=pinned_generations)
        if hits is None:
            raise ValueError("cohort requires a complete small policy set")
        if any(h.merchant_id != merchant_id or h.bundle_id not in pinned_generations
                or h.manifest_hash != manifest["manifest_hash"] for h in hits):
            raise ValueError("policy result scope mismatch")
        return [{"source_type": "POLICY", "version": h.version, "title": h.title,
            "retrieval_context": {"mode": "COMPLETE_SMALL_SET", "count": len(hits)},
            "data": {k: getattr(h, k) for k in ("bundle_id", "merchant_id", "manifest_hash", "rule_id", "chunk_id",
                "content_hash", "text")}} for h in hits]
