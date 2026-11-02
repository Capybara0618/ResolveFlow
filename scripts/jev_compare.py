"""Bounded paired study: current Agent, Jev-gated single repair, and an always-self-check control."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import uuid
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.harness.context import canonical_json
from resolveflow.harness.live_model import LiveModelClient
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_adapter import raw_text_message
from resolveflow.runtime.db import DEFAULT_DSN, Database, create_schema
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guide import guide_source
from resolveflow.support.jev import JevClient, JevConfig, load_local_env
from resolveflow.support.protocol import SupportFailure, SupportInput
from resolveflow.support.service import SupportRuntime

FIXTURE = ROOT / "agent/tests/fixtures/jev-comparison-v1.json"
REPAIR = (
    "重新核对刚才的候选答复与本轮已读取来源，必要时修正一次。保留所有有依据的内容、政策前提、"
    "客户假设和不确定性；不要为了通过检查而删除对用户问题的实质回答。不得编造新事实、"
    "新增引用或改写实际业务状态，不执行任何操作。不重新选择目标或工具。"
    "保持原RESPOND协议、任务覆盖和程序要求的原因字段，只输出完整修正后的单个JSON。"
)


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8", newline="\n")


class Allowance:
    """Create a durable reservation before every transmission; never reset or retry a paid attempt."""
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.calls = 0
        self.reserved_usd = 0.0

    def reserve(self, role: str, body: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        size = len(canonical_json(body).encode()) + 256
        # Upper estimates: UTF-8 bytes, cache-miss peak Flash price, full reserved output.
        rate = .042 if role == "jev" else .3
        output = 1024 * 1.2 / 1_000_000 if role != "jev" else 0
        cost = size * rate / 1_000_000 + output
        if self.calls >= 300 or self.reserved_usd + cost > 1:
            raise SupportFailure("STUDY_ALLOWANCE_EXHAUSTED")
        self.calls += 1
        self.reserved_usd += cost
        path = self.directory / f"attempt-{self.calls:03d}.json"
        record = {"role": role, "status": "STARTED", "request": body,
                  "reserved_usd": cost, "request_sha256": hashlib.sha256(canonical_json(body).encode()).hexdigest()}
        with path.open("x", encoding="utf-8", newline="\n") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        return path, record


class RecordedModel(LiveModelClient):
    def __init__(self, key: str, allowance: Allowance, role: str) -> None:
        super().__init__(endpoint="https://api.deepseek.com/chat/completions", model_id="deepseek-flash",
                         provider="deepseek", api_key=key, timeout_seconds=30,
                         parameters={"thinking": {"type": "disabled"},
                                     "response_format": {"type": "json_object"}, "temperature": 0})
        self.allowance, self.role = allowance, role
        self.records: list[dict[str, Any]] = []

    def decide(self, **kwargs: Any) -> Any:
        body = self.prepare_request(system=kwargs["system"], messages=kwargs["messages"],
                                    max_output_tokens=kwargs["max_output_tokens"])
        path, record = self.allowance.reserve(self.role, body)
        started = time.monotonic()
        try:
            reply = super().decide(**kwargs)
        except Exception as error:
            record.update(status="ERROR", error=type(error).__name__)
            write(path, record)
            raise
        record.update(status="COMPLETE", decision=deepcopy(reply.decision), usage=asdict(reply.usage),
                      served_model=reply.model_alias, elapsed_ms=(time.monotonic() - started) * 1000)
        write(path, record)
        self.records.append(record)
        return reply


class RecordedJev(JevClient):
    def __init__(self, config: JevConfig, allowance: Allowance) -> None:
        super().__init__(config)
        self.allowance = allowance

    def evaluate(self, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        path, record = self.allowance.reserve("jev", body)
        try:
            result = super().evaluate(body, **kwargs)
        except Exception as error:
            record.update(status="ERROR", error=type(error).__name__)
            write(path, record)
            raise
        record.update(status="COMPLETE", result=result)
        write(path, record)
        return result


class FrozenSources:
    """Business facts are synthetic frozen records. Current public guide; fixed complete policy pool."""
    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case

    def read(self, name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_support_guide":
            return cast(dict[str, Any], guide_source())
        status = self.case["http_status"].get(name, 404)
        if status != 200:
            return {"error": "NOT_FOUND" if status == 404 else "SOURCE_UNAVAILABLE", "retryable": status >= 500}
        value = deepcopy(self.case["facts"].get(name))
        if value is None:
            return {"error": "SOURCE_UNAVAILABLE", "retryable": False}
        return {"source_type": "ORDER" if name == "get_order_context" else "SHIPMENT",
                "version": value.get("version", 1), "data": value}

    def search(self, _query: str, _top_k: int, **_kwargs: Any) -> list[dict[str, Any]]:
        bundles = self.case["request"]["context"]["policy_manifest"]["bundle_ids"]
        values = deepcopy(self.case["policies"])
        if any(p["data"]["bundle_id"] not in bundles for p in values):
            raise SupportFailure("POLICY_SCOPE_MISMATCH")
        return cast(list[dict[str, Any]], values)


def validate_revision(request: SupportInput, case: dict[str, Any], originals: list[dict[str, Any]],
                      candidate: dict[str, Any]) -> dict[str, Any]:
    """Revalidate once with the actual current harness; no new network or business writes."""
    script = [deepcopy(r["decision"]) for r in originals[:-1]] + [candidate]
    class RecordedReplay(MockModelClient):
        provider = "deepseek"
        model_id = "deepseek-flash"

    replay = RecordedReplay(mode="live", script=script)
    result = SupportAgent(request, replay, FrozenSources(case), architecture="orchestrated-v1",
                          provider_capacity=32768).run()
    return {"validation": "recorded-live-decisions-offline", "status": result["status"],
            "reason": result["reason"], "answer": result["answer"]}


def revise(key: str, allowance: Allowance, role: str, request: SupportInput, case: dict[str, Any],
           originals: list[dict[str, Any]], verdict: str | None) -> dict[str, Any]:
    messages = [raw_text_message(m["content"], role=m["role"]) for m in originals[-1]["request"]["messages"]]
    messages.append(raw_text_message(json.dumps(originals[-1]["decision"], ensure_ascii=False), role="assistant"))
    feedback = REPAIR + ("\nJev辅助判断：" + verdict if verdict is not None else "")
    messages.append(raw_text_message(feedback, role="user"))
    model = RecordedModel(key, allowance, role)
    started = time.monotonic()
    try:
        reply = model.decide(system="", messages=messages, max_output_tokens=1024)
        validated = validate_revision(request, case, originals, reply.decision)
        return {**validated, "candidate": reply.decision, "calls": model.records,
                "elapsed_ms": (time.monotonic() - started) * 1000}
    except Exception as error:  # noqa: BLE001 - retain a failed one-shot candidate; never retry or publish it
        return {"status": "FAILED", "reason": type(error).__name__, "answer": None,
                "calls": model.records, "elapsed_ms": (time.monotonic() - started) * 1000}


def freeze(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    files = [FIXTURE, Path(__file__), ROOT / "agent/uv.lock"]
    for folder in ("support", "harness"):
        files.extend(sorted((ROOT / "agent/src/resolveflow" / folder).glob("*.py")))
    manifest = {"version": "jev-comparison-v1", "selection": "all-19-existing-single-turn",
                "primary": "live deepseek-flash, current AgentScope/SupportRuntime",
                "judge": "live jev-1.14.0, unchanged audit-only configuration",
                "arms": ["original", "jev-gated-one-repair", "always-one-self-check"],
                "max_provider_calls": 300, "max_reserved_usd": 1, "max_repairs_per_arm_per_case": 1,
                "no_retries": True, "synthetic_facts": True, "independent_holdout": False,
                "production_repair_enabled": False, "review": "Codex source review, not independent human labels",
                "files": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    write(output / "manifest.json", manifest)
    return manifest


def execute(output: Path) -> None:
    manifest = json.loads((output / "manifest.json").read_bytes())
    for name, digest in manifest["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError("frozen source changed: " + name)
    if (output / "results.json").exists() or list(output.glob("attempt-*.json")):
        raise ValueError("existing paid study cannot be overwritten or retried")
    load_local_env(ROOT / ".env")
    jev = JevConfig.from_environ()
    key = os.environ.get("RESOLVEFLOW_MODEL_API_KEY", "").strip()
    if not jev.enabled or not key:
        raise ValueError("both model credentials and enabled Jev are required")
    schema = "jev_compare_" + uuid.uuid4().hex[:12]
    dsn = os.environ.get("RESOLVEFLOW_AGENT_DB", DEFAULT_DSN)
    create_schema(dsn, schema)
    database, allowance = Database(dsn, schema=schema), Allowance(output)
    results: dict[str, Any] = {"version": manifest["version"], "schema": schema, "rows": []}
    write(output / "results.json", results)
    try:
        database.migrations()
        for index, case in enumerate(json.loads(FIXTURE.read_bytes())["cases"]):
            value = deepcopy(case["request"])
            value.update(run_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()), input_version=1,
                         deadline_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120))
            request = SupportInput.model_validate(value)
            primary = RecordedModel(key, allowance, "baseline")
            runtime = SupportRuntime(database,
                DeploymentConfig(mode="live", provider="deepseek", endpoint=primary.endpoint,
                                 model_id="deepseek-flash", context_window_tokens=32768),
                architecture="orchestrated-v1", model_factory=lambda primary=primary: primary,
                sources_factory=lambda *_, case=case: FrozenSources(case),
                jev_config=jev, jev_client=RecordedJev(jev, allowance))
            started = time.monotonic()
            original = runtime.run(request, "frozen-synthetic-no-network-business-token")
            elapsed = (time.monotonic() - started) * 1000
            with database.connection() as c:
                calls = c.execute("SELECT kind,position,request_json,response_json,status FROM support_agent_call "
                                  "WHERE run_id=%s ORDER BY kind,position", (request.run_id,)).fetchall()
            check = next((c["response_json"] for c in calls if c["kind"] == "jev"), None)
            verdict = check.get("verdict") if check else None
            row: dict[str, Any] = {"id": case["id"], "run_id": request.run_id,
                                  "request": request.model_dump(mode="json"), "baseline": original,
                                  "baseline_including_audit_ms": elapsed, "primary_calls": primary.records,
                                  "saved_calls": calls, "jev_check": check, "repairs": {}}
            results["rows"].append(row)
            write(output / "results.json", results)
            if original["status"] == "SUCCEEDED":
                # Alternate order to reduce systematic warm-cache/order differences.
                roles = ["jev-repair", "self-check"] if index % 2 else ["self-check", "jev-repair"]
                for role in roles:
                    if role == "jev-repair" and verdict not in {"contradicted", "insufficient_evidence"}:
                        continue
                    row["repairs"][role] = revise(key, allowance, role, request, case, primary.records,
                                                  verdict if role == "jev-repair" else None)
                    write(output / "results.json", results)
            print(json.dumps({"id": case["id"], "baseline": original["status"],
                              "jev": verdict or (check or {}).get("reason"),
                              "repairs": {k: v["status"] for k, v in row["repairs"].items()},
                              "total_attempts": allowance.calls}, ensure_ascii=False), flush=True)
        results["provider_attempts"] = allowance.calls
        results["conservative_reserved_usd"] = allowance.reserved_usd
        write(output / "results.json", results)
    finally:
        database.close()


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "execute"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze(args.output)
    elif not args.live:
        parser.error("execute requires explicit --live")
    else:
        execute(args.output)


if __name__ == "__main__":
    main()
