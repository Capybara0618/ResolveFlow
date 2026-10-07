"""Paired live investigations: fixed workflow and the production AgentScope loop."""

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.live_model import LiveModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner

from scripts.agent_eval import allowance, metadata, persist
from scripts.evaluation.dataset import digest, read, validate
from scripts.evaluation.environment import business_tools, dispatch_facts, environment
from scripts.evaluation.fixed_workflow import run_fixed
from scripts.evaluation.models import CaptureModel, live_guard
from scripts.evaluation.resume_retrieval import ExperimentalPolicyIndex
from scripts.evaluation.scoring import score_agent


def classify(case):
    backend = case["backend"]
    order = backend["order"]
    materials = case.get("review_context", {}).get("materials", [])
    reasons = []
    if (
        order.get("reserved_refund_amount", 0)
        or order.get("refunded_amount", 0)
        or order.get("line_refund_state") == "UNKNOWN"
    ):
        reasons.append("资金已占用或退款状态需核查")
    if backend.get("errors"):
        reasons.append("上游读取失败")
    if any(m.get("source_type") == "REVIEWER_VERIFICATION" for m in materials):
        reasons.append("人工核验或客户陈述需交叉核对")
    if any(
        word in case["description"]
        for word in ("破", "损", "缺", "签收", "未收到", "开封", "拆", "使用", "赠品")
    ):
        reasons.append("物流冲突或政策条件/例外")
    if case.get("family") in ("signed", "quality"):
        reasons.append("资料充分性或政策适用")
    return {
        "id": case["id"],
        "family": case["family"],
        "complex": bool(reasons),
        "reasons": reasons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=["A", "B", "C", "D", "E"], required=True)
    parser.add_argument("--reranker", type=Path, required=True)
    parser.add_argument("--trial", action="store_true")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "evals/resume-quantification-v1/business-v1",
    )
    parser.add_argument(
        "--ledger", type=Path, default=ROOT / "tmp/evaluation-live-budget.json"
    )
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("immutable live comparison")
    key = os.environ.get("RESOLVEFLOW_MODEL_API_KEY")
    if not key:
        raise ValueError("live credential missing")
    import torch

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    reranker = None
    if args.variant in ("C", "E"):
        from sentence_transformers import CrossEncoder

        reranker = CrossEncoder(str(args.reranker), device="cpu", max_length=512)
    data = args.dataset
    validate(data)
    cases, gold = read("agent/cases.json", data), read("gold/agent.json", data)
    if args.trial:
        cases = [
            next(c for c in cases if c["family"] == family)
            for family in dict.fromkeys(c["family"] for c in cases)
        ]
    report = metadata("live", data)
    report.update(
        state="RUNNING",
        expected_investigations=len(cases) * (2 if args.trial else 4),
        trial=args.trial,
        business_variant=args.variant,
        classifications=[classify(c) for c in cases],
        runner_sha256=digest(Path(__file__)),
        scoring_scope="automatic Gold; semantic source review follows",
        provider={
            "model": "deepseek-flash",
            "temperature": 0,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_output_tokens": 1024,
        },
    )
    with (
        live_guard(args.ledger),
        environment(dataset=data) as (db, original, encoder, pins),
    ):
        cap = allowance(args.ledger)
        index = (
            original
            if args.variant == "B"
            else ExperimentalPolicyIndex(db, args.variant, reranker)
        )
        for repeat in range(1 if args.trial else 2):
            for case in cases:
                for group in (
                    ["fixed", "dynamic"] if repeat == 0 else ["dynamic", "fixed"]
                ):
                    entry = {
                        "id": case["id"],
                        "group": group,
                        "repeat": repeat,
                        "family": case["family"],
                        "status": "RUNNING",
                        "joint_correct": False,
                        "completed": False,
                    }
                    report["results"].append(entry)

                    def checkpoint(records, entry=entry):
                        entry["requests"] = records
                        entry["model_calls"] = len(records)
                        persist(args.output, report)

                    model = CaptureModel(
                        LiveModelClient(
                            endpoint="https://api.deepseek.com/chat/completions",
                            model_id="deepseek-flash",
                            provider="deepseek",
                            api_key=key,
                            parameters={
                                k: report["provider"][k]
                                for k in ("temperature", "thinking", "response_format")
                            },
                        ),
                        cap,
                        on_record=checkpoint,
                    )
                    started = time.perf_counter()
                    try:
                        run_id = str(uuid.uuid4())
                        pin, case_id = pins[case["bundle_id"]], case["case_id"]
                        with business_tools(
                            case, pin, run_id=run_id, case_id=case_id
                        ) as (tools, reads):
                            runner = AgentScopeRunner(
                                model=model,
                                tools=tools,
                                facts=dispatch_facts(
                                    case, pin, run_id=run_id, case_id=case_id
                                ),
                                policy_index=index,
                                policy_embedder=encoder,
                                budget=RunBudget(model_calls=12),
                            )
                            entry["harness_manifest"] = runner.manifest()
                            result = (
                                run_fixed(runner) if group == "fixed" else runner.run()
                            )
                            entry.update(
                                score_agent(result, gold[case["id"]], case=case)
                            )
                            entry.update(
                                status="COMPLETED"
                                if result.completed
                                else "INCOMPLETE",
                                completed=result.completed,
                                reason_code=result.reason_code,
                                decision=result.decision.model_dump(mode="json")
                                if result.decision
                                else None,
                                spend=asdict(result.spend),
                                trajectory=result.trajectory,
                                notices=result.notices,
                                http_reads=reads,
                                observations=[
                                    o.model_dump(mode="json")
                                    for o in result.observations
                                ],
                            )
                    except Exception as error:  # noqa: BLE001 - retain every measured failure in its denominator
                        entry.update(
                            status="ERROR", error=f"{type(error).__name__}: {error}"
                        )
                    entry.update(
                        requests=model.records,
                        model_calls=len(model.records),
                        elapsed_ms=(time.perf_counter() - started) * 1000,
                    )
                    report["live_usage"] = {"used": cap["used"], "limit": None}
                    persist(args.output, report)
                    print(
                        json.dumps(
                            {
                                k: entry.get(k)
                                for k in (
                                    "id",
                                    "group",
                                    "repeat",
                                    "status",
                                    "model_calls",
                                    "joint_correct",
                                    "error",
                                )
                            }
                        ),
                        flush=True,
                    )
    if len(report["results"]) != report["expected_investigations"]:
        raise ValueError("incomplete investigation population")
    report["state"] = "COMPLETED"
    persist(args.output, report)


if __name__ == "__main__":
    main()
