"""Independent workflow / production Agent paired runner. No live execution by default."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.runtime.db import Database, create_schema, drop_schema
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.progress import ProgressReporter
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.service import SupportRuntime
from resolveflow.support.sources import BoundSources

from scripts import customer_current_eval as current
from scripts.agent_eval import allowance
from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot
from scripts.customer_workflow_comparison_prepare import (
    DATA,
    ROOT,
    VARIANTS,
    digest,
    load_dataset,
    read,
)
from scripts.evaluation.basic_customer_workflow import run_turn
from scripts.evaluation.customer_comparison_environment import (
    PlainChatClient,
    RawPolicyService,
    RequestAllowance,
    guide_data,
    transport_for,
    wire_tokenizer,
)
from scripts.evaluation.models import live_guard

VERSION = "customer-workflow-comparison-v2"
PLAN = DATA.with_name("execution-manifest.json")
USAGE = ROOT / "tmp/evaluation-live-budget.json"
DSN = "postgresql://agent:agent@127.0.0.1:55433/agent_db"
ENDPOINT = "https://api.deepseek.com/chat/completions"
NAMESPACE = uuid.UUID("a8ab8258-5bdd-44cc-990a-6cc68891bc6a")
PARAMETERS = {"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}, "temperature": 0}


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(value, out, ensure_ascii=False, indent=2, default=str)
        out.write("\n")


def persist(path, value):
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def cases():
    data = load_dataset()
    snapshots = {c["id"]: c for c in read(ROOT / data["snapshot_source"]["path"])["cases"]}
    result = []
    for item in data["cases"]:
        # Rubrics never travel into either system's turn preparation or prompts.
        case = {k: deepcopy(item[k]) for k in ("id", "family", "complex", "snapshot_id")}
        case["turns"] = [{"text": t["text"]} for t in item["turns"]]
        case["snapshot"] = deepcopy(snapshots[item["snapshot_id"]])
        override = item.get("snapshot_override")
        if override:
            case["snapshot"]["http_status"][override["tool"]] = override["status"]
            case["snapshot"]["facts"][override["tool"]] = override["body"]
        result.append(case)
    return result


def scoped_id(case, variant):
    return VERSION + ":" + variant + ":" + case["id"]


def identity_name(case, variant):
    # Match the retained production evaluation's accepted-state adapter namespace.
    return current.VERSION + ":" + scoped_id(case, variant)


def visible_text(answer):
    return "\n\n".join(answer[k] for k in ("text", "refund_summary", "handoff_summary")
        if isinstance(answer.get(k), str) and answer[k].strip())


def plain_turn(case, variant, index, completed):
    if len(completed) != index or not 0 <= index < len(case["turns"]):
        raise ValueError("completed turns must equal the preceding prefix")
    history = []
    name = identity_name(case, variant)
    conversation = str(uuid.uuid5(NAMESPACE, name))
    for n in range(index + 1):
        sequence = len(history) + 1
        history.append({"message_id": str(uuid.uuid5(NAMESPACE, f"{name}:{sequence}:customer")),
            "sequence": sequence, "author": "CUSTOMER", "recipient": "ASSISTANT", "text": case["turns"][n]["text"]})
        if n < index:
            row = completed[n]
            if row["run_id"] != str(uuid.uuid5(NAMESPACE, f"{name}:{n}")):
                raise ValueError("completed prefix belongs to another conversation")
            if row["status"] == "SUCCEEDED":
                history.append({"message_id": str(uuid.uuid5(NAMESPACE, f"{name}:{sequence+1}:assistant")),
                    "sequence": sequence + 1, "author": "ASSISTANT", "recipient": "CUSTOMER",
                    "text": visible_text(row["answer"])})
    base = deepcopy(case["snapshot"]["input_without_deadline"])
    return {**{k: base[k] for k in ("merchant_id", "customer_id", "line_id")},
        "run_id": str(uuid.uuid5(NAMESPACE, f"{name}:{index}")), "conversation_id": conversation,
        "input_version": history[-1]["sequence"], "deadline_at": datetime.now(UTC) + timedelta(seconds=120),
        "context": {"product": base["context"]["product"], "policy_manifest": base["context"]["policy_manifest"],
            "current_request": case["turns"][index]["text"], "history": deepcopy(history[-20:])}}, history


def agent_turn(case, index, completed):
    previous = []
    for row in completed:
        result = deepcopy(row["raw_result"])
        if result["status"] == "SUCCEEDED":
            result["answer"]["text"] = visible_text(result["answer"])
        previous.append(result)
    return current.prepare_turn({**case, "id": scoped_id(case, "agent")}, index, previous)


def empty_row(case, variant, index):
    return {"case_id": case["id"], "variant": variant, "turn": index + 1,
        "run_id": str(uuid.uuid5(NAMESPACE, f"{identity_name(case, variant)}:{index}")),
        "status": "NOT_RUN", "answer": None, "models": [], "tools": [], "paths": [], "events": [],
        "elapsed_ms": None, "first_body_ms": None}


def run_matrix(selected, report, execute_turn, save):
    stopped = False
    for number, case in enumerate(selected):
        order = VARIANTS if number % 2 == 0 else VARIANTS[::-1]
        for variant in order:
            completed = []
            for index in range(len(case["turns"])):
                row = empty_row(case, variant, index)
                report["rows"].append(row)
                save()
                if not stopped:
                    row.update(execute_turn(case, variant, index, completed))
                    stopped = row.get("allowance_exhausted", False) or row.get("reason") == "EVALUATION_ALLOWANCE_EXHAUSTED"
                else:
                    row["reason"] = "EVALUATION_STOPPED"
                completed.append(deepcopy(row))
                save()
    report["state"] = "FINISHED"
    save()


class RecordedAgentModel(StreamingLiveModelClient):
    def __init__(self, *, budget, records, save, **kwargs):
        super().__init__(**kwargs)
        self.budget, self.records, self.save = budget, records, save

    def _send(self, payload, headers):
        try:
            self.budget.consume()
        except RuntimeError:
            raise SupportFailure("EVALUATION_ALLOWANCE_EXHAUSTED") from None
        self.records[-1]["provider_sent"] = True
        self.save()
        return super()._send(payload, headers)

    def decide(self, **kwargs):
        record = {"body": self.prepare_request(system=kwargs["system"], messages=kwargs["messages"],
            max_output_tokens=kwargs["max_output_tokens"]), "state": "STARTED", "provider_sent": False, "usage": None}
        self.records.append(record)
        self.last_stream = None
        started = time.perf_counter()
        previous_requests = len(self.requests)
        self.save()
        try:
            reply = super().decide(**kwargs)
            record.update(state="COMPLETE", decision=reply.decision, usage=asdict(reply.usage),
                mode=reply.mode, served_model=reply.model_alias)
            return reply
        except Exception as error:
            record.update(state="ERROR", error_type=type(error).__name__)
            raise
        finally:
            record.update(elapsed_ms=(time.perf_counter() - started) * 1000, stream=self.last_stream)
            if len(self.requests) > previous_requests:
                record['provider_http_status'] = self.requests[-1]['status']
            self.save()


class AgentSources(BoundSources):
    def __init__(self, *args, row, save, **kwargs):
        super().__init__(*args, **kwargs)
        self.row, self.save = row, save

    def measured(self, category, operation, **metadata):
        record = {"category": category, **metadata}
        self.row["tools"].append(record)
        started = time.perf_counter()
        try:
            value = operation()
            record["result"] = deepcopy(value)
            return value
        finally:
            record["elapsed_ms"] = (time.perf_counter() - started) * 1000
            self.save()

    def read(self, name, arguments):
        category = {"get_order_context": "ORDER", "get_shipment_trace": "SHIPMENT",
            "get_support_guide": "GUIDE", "read_history": "HISTORY"}[name]
        return self.measured(category, lambda: super(AgentSources, self).read(name, arguments),
            name=name, arguments=arguments)

    def search(self, query, top_k, *, sub_queries=None):
        return self.measured("POLICY", lambda: super(AgentSources, self).search(query, top_k, sub_queries=sub_queries),
            query=query, top_k=top_k, sub_queries=sub_queries)


def execute_agent(case, index, completed, row, *, db, index_service, model, save):
    request, archive = agent_turn(case, index, completed)
    if request.run_id != row["run_id"]:
        raise ValueError("Agent run identity differs")
    row["input"] = request.model_dump(mode="json")
    started = time.perf_counter()
    with httpx.Client(transport=httpx.MockTransport(transport_for(case["snapshot"],
            request.model_dump(), archive, row["paths"]))) as client:
        def sources(bound, token, journal):
            journal.pin_generations(case["snapshot"]["pinned_generations"])
            return AgentSources(bound, token=token, case_url="http://frozen-case.local", index=index_service,
                journal=journal, client=client, row=row, save=save)
        config = DeploymentConfig(mode="live", provider="deepseek", model_id="deepseek-flash", endpoint=ENDPOINT,
            api_key="", context_window_tokens=32768, case_base_url="http://frozen-case.local")
        runtime = SupportRuntime(db, config, model_factory=lambda: model, sources_factory=sources,
            architecture="orchestrated-v1")
        reporters = []
        def receive(call):
            if call.url.path != "/internal/v1/support/turns/" + request.run_id + "/stream-events" or call.method != "POST":
                return httpx.Response(403)
            body = json.loads(call.content)
            row["events"].extend({**e, "batch_sequence": body["batch_sequence"],
                "elapsed_ms": (time.perf_counter() - started) * 1000} for e in body["events"])
            return httpx.Response(200, json={})
        def progress(url, run, token):
            reporter = ProgressReporter(url, run, token, transport=httpx.MockTransport(receive))
            reporters.append(reporter)
            return reporter
        with patch("resolveflow.support.service.ProgressReporter", progress):
            result = runtime.run(request, "frozen-read-token", progress_token="frozen-progress-token")
    row.update(raw_result=result, status=result["status"], reason=result.get("reason"),
        answer={k: result["answer"][k] for k in ("text", "refund_summary", "handoff_summary")
            if k in result.get("answer", {})} if result.get("answer") else None,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        progress_failure=reporters[0].failure if reporters else None)
    times = current.stream_times(row["events"], result["status"] == "SUCCEEDED")
    row.update(first_body_ms=times["first_retained_ms"], stream_times=times, first_body_scope="SERVER_RETAINED_JSON_TEXT")
    if result["status"] != "SUCCEEDED":
        reason = result.get("reason", "")
        row["status"] = "TIMEOUT" if "DEADLINE" in reason or "TIMEOUT" in reason else (
            "BUDGET_EXHAUSTED" if "BUDGET" in reason or "ALLOWANCE" in reason else "FAILED")
    return row


def execute_basic(case, index, completed, row, *, policy, model, save):
    packet, archive = plain_turn(case, "basic_workflow", index, completed)
    row["input"] = packet
    with httpx.Client(transport=httpx.MockTransport(transport_for(case["snapshot"], packet, archive, row["paths"]))) as client:
        def read_source(category, *, query=None):
            if category == "GUIDE":
                return {"status_code": 200, "body": guide_data()}
            if category == "POLICY":
                return {"status_code": 200, "body": policy.search(packet["merchant_id"],
                    packet["context"]["policy_manifest"], case["snapshot"]["pinned_generations"], query)}
            path = {"ORDER": "order", "SHIPMENT": "shipment"}[category]
            response = client.get("http://frozen-case.local/internal/v1/support/turns/" + packet["run_id"] + "/facts/" + path)
            return {"status_code": response.status_code, "body": response.json()}
        def record(value):
            row.update(value)
            save()
        result = run_turn(current_request=packet["context"]["current_request"], history=[
            {"role": "user" if m["author"] == "CUSTOMER" else "assistant", "content": m["text"]}
            for m in packet["context"]["history"]], subject={**packet, "product": packet["context"]["product"]},
            model=model, read=read_source, max_output_tokens=1024, on_record=record)
    row.update(result, raw_result=deepcopy(result))
    return row


def check_sources(selected, dsn=DSN):
    from resolveflow.policies.index import PolicyIndex
    database = ReadOnlyDatabase(dsn)
    try:
        before, counts = snapshot(database), []
        index, policy = PolicyIndex(database), RawPolicyService(PolicyIndex(database))
        for case in selected:
            request, archive = agent_turn(case, 0, [])
            raw = policy.search(request.merchant_id, request.context["policy_manifest"],
                case["snapshot"]["pinned_generations"], case["turns"][0]["text"])
            with httpx.Client(transport=httpx.MockTransport(transport_for(case["snapshot"],
                    request.model_dump(), archive, []))) as client:
                bound = BoundSources(request, token="check", case_url="http://frozen-case.local", index=index, client=client)
                if raw != bound.search(case["turns"][0]["text"], 3) or guide_data() != bound.read("get_support_guide", {}):
                    raise ValueError("shared raw source parity differs")
            counts.append(len(raw))
        after = snapshot(database)
        if before != after:
            raise ValueError("retained data changed")
        return {"cases": len(counts), "policy_counts": counts, "raw_source_parity": True,
            "public_before": before, "public_after": after, "equal": True}
    finally:
        database.close()


def source_files():
    names = {"docs/customer-workflow-comparison-v2.md", DATA.relative_to(ROOT).as_posix(),
        "scripts/customer_workflow_comparison_live.py", "scripts/customer_workflow_comparison_prepare.py",
        "scripts/evaluation/basic_customer_workflow.py", "scripts/evaluation/customer_comparison_environment.py",
        "scripts/customer_current_eval.py", "scripts/customer_agent_readiness.py", "scripts/customer_rag_diagnostic.py",
        "scripts/customer_rag_live_v2.py", "scripts/customer_agent_eval_v2.py", "scripts/agent_eval.py",
        "scripts/evaluation/models.py", "agent/uv.lock",
        "agent/tests/unit/test_basic_customer_workflow.py", "agent/tests/unit/test_customer_comparison_environment.py",
        "agent/tests/unit/test_customer_workflow_comparison_prepare.py",
        "agent/tests/unit/test_customer_workflow_comparison_live.py",
        "agent/tests/integration/test_customer_workflow_comparison_live.py"}
    data = load_dataset()
    names.update(data[k]["path"] for k in ("source_cases", "snapshot_source"))
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "agent/src/resolveflow").rglob("*.py"))
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "agent/src/resolveflow/assets").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts)
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "agent/src/resolveflow/runtime/migrations").glob("*.sql"))
    return {n: digest(ROOT / n) for n in sorted(names)}


def manifest():
    return {"version": VERSION, "dataset_sha256": digest(DATA), "files": source_files(),
        "architecture": "orchestrated-v1", "conversations": 64, "turns": 100, "repeats": 1,
        "model": "deepseek-flash", "parameters": PARAMETERS, "context_window_tokens": 32768,
        "step_input_tokens": 8192, "step_output_tokens": 1024, "model_calls": 12, "deadline_seconds": 120,
        "source_visible_regression": True, "independent_holdout": False, "policy": "COMPLETE_SMALL_SET_ONLY",
        "baseline": "independent router/fixed branch/answer; no production Agent internals"}


def freeze(path=PLAN):
    write_new(path, manifest())


def load_plan(path=PLAN):
    plan = read(path)
    if plan != manifest():
        raise ValueError("frozen sources/dataset differ")
    return plan


def execute(output, limit):
    from resolveflow.policies.index import PolicyIndex
    if type(limit) is not int or limit <= 0:
        raise ValueError("positive explicit request allowance required")
    plan = load_plan()
    key = (os.getenv("RESOLVEFLOW_MODEL_API_KEY") or os.getenv("Deepseek_API_KEY") or "").strip()
    if not key:
        raise ValueError("missing model key")
    report = {"version": VERSION, "dataset_sha256": digest(DATA), "manifest_sha256": digest(PLAN),
        "state": "PREPARING", "rows": [], "real_generation": True, "synthetic_http_facts": True,
        "business_end_to_end": False, "parameters": plan["parameters"]}
    write_new(output, report)
    schema = "t_support_comparison_v2_" + uuid.uuid4().hex[:12]
    private = ROOT / "tmp" / VERSION / schema
    write_new(private / "ownership.json", {"schema": schema, "output": str(output.resolve())})
    retained, db = ReadOnlyDatabase(DSN), Database(DSN, schema=schema)
    created = exported = False
    save = lambda: persist(output, report)
    try:
        report["preflight"] = check_sources(cases())
        report["public_before"] = snapshot(retained)
        from resolveflow.harness.token_counting import prewarm_counter
        started = time.perf_counter()
        wire_tokenizer()
        report['baseline_tokenizer_prewarm_ms'] = (time.perf_counter() - started) * 1000
        report['agent_tokenizer_prewarm_ms'] = prewarm_counter(provider='deepseek', model_id='deepseek-flash')
        create_schema(DSN, schema)
        created = True
        db.migrations()
        index_service = PolicyIndex(retained)
        policy = RawPolicyService(index_service)
        with live_guard(USAGE):
            ledger = allowance(USAGE)
            budget = RequestAllowance(ledger, ledger["used"], limit)
            report.update(state="RUNNING", usage_before=ledger["used"], max_new_provider_requests=limit)
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as http:
                def turn(case, variant, number, completed):
                    row = report["rows"][-1]
                    def checkpoint():
                        persist(private / (row["run_id"] + ".json"), row)
                    try:
                        if variant == "basic_workflow":
                            model = PlainChatClient(http, ENDPOINT, key, budget)
                            execute_basic(case, number, completed, row, policy=policy, model=model, save=checkpoint)
                        else:
                            model = RecordedAgentModel(budget=budget, records=row["models"], save=checkpoint,
                                provider="deepseek", model_id="deepseek-flash", endpoint=ENDPOINT, api_key=key,
                                timeout_seconds=30, parameters=PARAMETERS)
                            execute_agent(case, number, completed, row, db=db, index_service=index_service,
                                model=model, save=checkpoint)
                    finally:
                        row["allowance_exhausted"] = ledger["used"] - budget.start >= limit
                        report["usage_after"] = ledger["used"]
                        save()
                    print(json.dumps({"case": case["id"], "variant": variant, "turn": number + 1,
                        "status": row["status"], "models": len(row["models"])}), flush=True)
                    return row
                run_matrix(cases(), report, turn, save)
        report["public_after"] = snapshot(retained)
        if report["public_before"] != report["public_after"]:
            raise ValueError("retained public data changed")
        load_plan()
    except BaseException as error:
        report.update(state="ERROR", error_type=type(error).__name__)
        raise
    finally:
        try:
            if created:
                with db.connection() as connection:
                    report["all_runs"] = connection.execute("SELECT * FROM support_agent_run ORDER BY run_id").fetchall()
                    report["all_calls"] = connection.execute("SELECT * FROM support_agent_call ORDER BY run_id,kind,position").fetchall()
            save()
            exported = True
        finally:
            db.close()
            if created and exported:
                drop_schema(DSN, schema)
            retained.close()
        report["isolated_schema_dropped"] = created and exported
        save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "check", "execute"])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-provider-requests", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "freeze":
        freeze()
    elif args.mode == "check":
        report = {"version": VERSION, "database": check_sources(cases()), "new_provider_requests": 0,
            "manifest_checked": False, "quality_measured": False}
        if PLAN.exists():
            load_plan()
            report["manifest_checked"] = True
        if args.output:
            write_new(args.output, report)
        print({k: v for k, v in report.items() if k != "database"})
    else:
        if not args.live or not args.max_provider_requests or args.max_provider_requests <= 0 or not args.output:
            parser.error("execute requires --live, positive --max-provider-requests and new --output")
        execute(args.output, args.max_provider_requests)


if __name__ == "__main__":
    main()
