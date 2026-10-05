"""Current evaluation entry. No production database writes or callback delivery."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import nullcontext
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.contracts.core_models import ToolObservation  # noqa: E402
from resolveflow.harness.actions import ModelDecision  # noqa: E402
from resolveflow.harness.budget import RunBudget  # noqa: E402
from resolveflow.harness.live_model import LiveModelClient  # noqa: E402
from resolveflow.harness.sdk_runner import AgentScopeRunner  # noqa: E402
from resolveflow.policies import EMBEDDING_DIMENSION, EMBEDDING_MODEL, EMBEDDING_REVISION  # noqa: E402
from scripts.evaluation.dataset import DATA, digest, read, validate  # noqa: E402
from scripts.evaluation.environment import business_tools, dispatch_facts, environment  # noqa: E402
from scripts.evaluation.models import CaptureModel, FixtureModel, live_guard  # noqa: E402
from scripts.evaluation.reporting import compare_reports, describe, load_report  # noqa: E402
from scripts.evaluation.review import make_review, score_review  # noqa: E402
from scripts.evaluation.scoring import score_agent, score_rag  # noqa: E402


def dependency_versions():
    result = {}
    for name in ("agentscope", "mcp", "psycopg", "sentence-transformers"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = "NOT_INSTALLED"
    return result


def metadata(mode, dataset=DATA):
    return {
        "dataset_version": read("manifest.json", dataset)["version"],
        "manifest_hash": digest(dataset / "manifest.json"),
        "replay_manifest_hash": digest(dataset / "replay/manifest.json")
        if (dataset / "replay/manifest.json").is_file() else None,
        "mode": mode,
        "synthetic": True,
        "backend_profile": read("manifest.json", dataset).get(
            "input_profile", "loopback synthetic sources; materials with text, not Java EvidenceListResponse"
        ),
        "business_end_to_end": False,
        "scoring_scope": "automatic action/read/citation checks; semantic explanation and question review pending",
        "gold_review": read("manifest.json", dataset)["review_status"],
        "embedding": {"model": EMBEDDING_MODEL, "revision": EMBEDDING_REVISION, "dimension": EMBEDDING_DIMENSION},
        "dependencies": dependency_versions(),
        "entry_hash": digest(ROOT / "scripts/agent_eval.py"),
        "dependency_lock_hash": digest(ROOT / "agent/uv.lock"),
        "code_commit": subprocess.check_output(  # noqa: S603 - fixed git read, no user command
            [shutil.which("git"), "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "code_hashes": {
            str(p.relative_to(ROOT)).replace("\\", "/"): digest(p)
            for area in (
                ROOT / "agent/src/resolveflow/harness",
                ROOT / "agent/src/resolveflow/policies",
                ROOT / "agent/src/resolveflow/tools",
                ROOT / "scripts/evaluation",
            )
            for p in sorted(area.glob("*.py"))
        },
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": [],
    }


def persist(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8",
                         newline="\n")
    # Windows readers/indexers may briefly hold the destination without delete-sharing.
    # Retry only this local atomic rename, never a provider call or the investigation.
    for attempt in range(4):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(0.05 * (2 ** attempt))


def rag(report, index, encoder, pins, *, split, bm25_only=False, dataset=DATA):
    gold = read("gold/rag.json", dataset)
    for query in read("rag/queries.json", dataset):
        if split != "all" and query["split"] != split:
            continue
        for path in ("bm25",) if bm25_only else ("dense", "bm25"):
            started = time.perf_counter()
            entry = {"id": query["id"], "split": query["split"], "path": path, "query": query["query"]}
            try:
                pin = pins[query["bundle_id"]]
                hits = index.search(
                    **{k: pin[k] for k in ("merchant_id", "bundle_ids", "manifest_hash")},
                    query=query["query"],
                    path=path,
                    top_k=5,
                    embedder=encoder if path == "dense" else None,
                )
                entry.update(score_rag(hits, query, gold[query["id"]], pin))
                entry["scores"] = [hit.score for hit in hits]
            except Exception as error:
                entry["error"] = f"{type(error).__name__}: {error}"
            entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
            report["results"].append(entry)
    report["summary"] = {}
    for path in ("dense", "bm25"):
        for part in ("dev", "test", "all"):
            entries = [e for e in report["results"] if e["path"] == path and (part == "all" or e["split"] == part)]
            if not entries:
                continue
            positives = [e for e in entries if gold[e["id"]]["must_rules"]]
            negatives = [e for e in entries if not gold[e["id"]]["must_rules"]]
            report["summary"][f"{path}/{part}"] = {
                "n": len(entries),
                "positive_n": len(positives),
                "errors": sum("error" in e for e in entries),
                "filter_violations": sum(e.get("violations", 0) for e in entries),
                **{
                    f"coverage_at_{k}": round(
                        sum(e.get(f"coverage_at_{k}", 0) or 0 for e in positives) / max(1, len(positives)), 4
                    )
                    for k in (1, 2, 5)
                },
                "all_required_at_5": sum(bool(e.get("all_required_at_5")) for e in positives),
                "negative_n": len(negatives),
                "negative_candidates": sum(bool(e.get("negative_returned_candidates")) for e in negatives),
            }


def allowance(path):
    """Read a usage ledger, including legacy budget files, without enforcing expense limits."""
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"used": 0}
    if type(value.get("used")) is not int or value["used"] < 0:
        raise ValueError("Invalid persisted live request count")
    reserved = value.get("reserved_usd", 0)
    if type(reserved) not in (float, int) or not math.isfinite(reserved) or reserved < 0:
        raise ValueError("Invalid persisted monetary reservation")
    if value.get("limit") is not None:
        value.setdefault("historical_limit", value["limit"])
    value["limit"] = None
    value["accounting_policy"] = "usage-only-v1"

    def save():
        persist(path, {key: item for key, item in value.items() if key != "save"})

    value["save"] = save
    return value


def agents(report, index, encoder, pins, *, mode, split, selected, output, live_budget, dataset=DATA, model_calls=6):
    if type(model_calls) is not int or not 1 <= model_calls <= RunBudget().model_calls:
        raise ValueError("model_calls must be between 1 and the production default (12)")
    report["evaluation_config"] = asdict(RunBudget(model_calls=model_calls))
    gold = read("gold/agent.json", dataset)
    cases = [
        c
        for c in read("agent/cases.json", dataset)
        if (split == "all" or c["split"] == split) and (not selected or c["id"] in selected)
    ]
    if selected and set(selected) != {c["id"] for c in cases}:
        raise ValueError("Unknown case id or split mismatch")
    if not cases:
        raise ValueError("Zero cases is not a successful evaluation")
    cap = None
    if mode == "live":
        if not selected or live_budget is None:
            raise ValueError("Live requires explicit --case selections and a usage ledger")
        key = os.environ.get("RESOLVEFLOW_MODEL_API_KEY") or os.environ.get("Deepseek_API_KEY")
        if not key:
            raise ValueError("Live API key missing; no mock fallback")
        cap = allowance(live_budget)
        report["provider"] = {
            "endpoint": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-flash",
            "parameters": {
                "temperature": 0,
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"},
            },
            "per_case_calls": model_calls,
            "total_transmission_cap": cap["limit"],
            "max_output_tokens": 1024,
            "reservation_cap_usd": None,
            "accounting_policy": "usage-only-v1",
        }
    report["results"] = [
        {
            "id": c["id"],
            "split": c["split"],
            "pair_id": c["pair_id"],
            "status": "NOT_RUN",
            "completed": False,
            "joint_correct": False,
            "action_correct": False,
            "model_calls": 0,
        }
        for c in cases
    ]
    report["state"] = "RUNNING"
    persist(output, report)
    for case, entry in zip(cases, report["results"], strict=True):
        started = time.perf_counter()
        entry["status"] = "RUNNING"
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "resolveflow-eval-run:" + case["id"]))
        case_id = case.get("case_id") or str(uuid.uuid5(uuid.NAMESPACE_URL, "resolveflow-eval-case:" + case["id"]))
        pin = pins[case["bundle_id"]]
        client = (
            FixtureModel()
            if mode == "mock"
            else LiveModelClient(
                endpoint=report["provider"]["endpoint"],
                model_id="deepseek-flash",
                provider="deepseek",
                api_key=key,
                parameters=report["provider"]["parameters"],
            )
        )

        def checkpoint(records, entry=entry):
            entry["requests"] = records
            entry["model_calls"] = len(records)
            persist(output, report)

        model = CaptureModel(client, cap, on_record=checkpoint)
        try:
            with business_tools(case, pin, run_id=run_id, case_id=case_id) as (tools, http_reads):
                facts = dispatch_facts(case, pin, run_id=run_id, case_id=case_id)
                runner = AgentScopeRunner(
                    model=model,
                    tools=tools,
                    facts=facts,
                    policy_index=index,
                    policy_embedder=encoder,
                    budget=RunBudget(model_calls=model_calls),
                )
                entry["harness_manifest"] = runner.manifest()
                entry["budget_config"] = asdict(runner.budget)
                result = runner.run()
                entry.update(score_agent(result, gold[case["id"]], case=case))
                entry.update(
                    status="COMPLETED" if result.completed else "INCOMPLETE",
                    completed=result.completed,
                    reason_code=result.reason_code,
                    decision=result.decision.model_dump(mode="json") if result.decision else None,
                    spend=asdict(result.spend),
                    trajectory=result.trajectory,
                    notices=result.notices,
                    context_diagnostics=[
                        json.loads(n.split("=", 1)[1]) for n in result.notices if n.startswith("CONTEXT_DIAGNOSTICS=")
                    ],
                    observations=[o.model_dump(mode="json") for o in result.observations],
                    http_reads=http_reads,
                )
        except Exception as error:
            entry.update(
                error=f"{type(error).__name__}: {error}", joint_correct=False, action_correct=False, status="ERROR"
            )
        entry["requests"] = model.records
        entry["model_calls"] = len(model.records)
        entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        report["summary"] = {
            "n": len(report["results"]),
            "joint_correct": sum(e["joint_correct"] for e in report["results"]),
            "action_correct": sum(e["action_correct"] for e in report["results"]),
            "forbidden_actions": sum(bool(e.get("forbidden_action")) for e in report["results"]),
            "errors": sum("error" in e for e in report["results"]),
            "incomplete": sum(not e.get("completed", False) for e in report["results"]),
            "model_calls": sum(e["model_calls"] for e in report["results"]),
        }
        if cap:
            report["live_usage"] = {
                "used": cap["used"],
                "limit": cap["limit"],
                "reserved_usd": cap.get("reserved_usd", 0),
                "reservation_kind": "historical_only_not_updated",
            }
        persist(output, report)
        print(
            json.dumps(
                {
                    "case": case["id"],
                    "action": entry.get("action"),
                    "correct": entry["joint_correct"],
                    "calls": entry["model_calls"],
                    "error": entry.get("error"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


def rescore(source, source_path, dataset=DATA):
    if source["mode"] not in {"mock", "live"} or source["manifest_hash"] != digest(dataset / "manifest.json"):
        raise ValueError("Only current frozen Agent reports can be rescored without rerunning")
    gold = read("gold/agent.json", dataset)
    cases = {c["id"]: c for c in read("agent/cases.json", dataset)}
    for entry in source["results"]:
        if entry["id"] not in gold:
            raise ValueError("Unknown saved case id")
        if not entry.get("completed", False):
            continue
        result = SimpleNamespace(
            completed=True,
            decision=ModelDecision.model_validate(entry["decision"]) if entry.get("decision") else None,
            observations=[
                ToolObservation.model_validate_json(json.dumps(item)) for item in entry.get("observations", [])
            ],
        )
        entry.update(score_agent(result, gold[entry["id"]], case=cases[entry["id"]]))
    source["summary"]["joint_correct"] = sum(bool(e.get("joint_correct")) for e in source["results"])
    source["summary"]["action_correct"] = sum(bool(e.get("action_correct")) for e in source["results"])
    source["scoring_hashes"] = {
        name: digest(ROOT / name) for name in ("scripts/evaluation/scoring.py", "scripts/evaluation/dataset.py")
    }
    source["scored_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    source["rescored_from"] = {"path": str(source_path), "sha256": digest(source_path)}
    source["new_model_requests"] = 0
    return source


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=(
            "validate",
            "rag",
            "mock",
            "live",
            "harness",
            "replay",
            "report",
            "compare",
            "rescore",
            "review-template",
            "review-score",
        ),
    )
    parser.add_argument("--split", choices=("dev", "test", "all"), default="all")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "evals/calibrated-v3",
        help="frozen version directory; default calibrated-v3, earlier versions remain available",
    )
    parser.add_argument("--replay-dir", type=Path, default=ROOT / "evals/replay/harness-v10",
                        help="current code replay profile; frozen dataset/Gold are independent")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--model-calls", type=int, choices=range(1, RunBudget().model_calls + 1), default=6,
                        help="per-case safety limit; historical default 6, production parity requires explicit 12")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live-usage", "--live-budget", dest="live_budget", type=Path,
                        default=ROOT / "tmp/evaluation-live-budget.json",
                        help="usage ledger only, no expense cap; --live-budget is a compatibility alias")
    parser.add_argument("--bm25-only", action="store_true", help="rag only, explicitly do not run dense")
    parser.add_argument("--input-report", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args(argv)
    if args.bm25_only and args.mode != "rag":
        parser.error("--bm25-only is available only in rag mode")
    if args.mode == "live" and not args.case:
        parser.error("live requires explicit --case selections; no automatic paid sweep")
    counts = validate(args.dataset)
    if args.mode == "validate":
        print(json.dumps(counts))
        return 0
    output = args.output or ROOT / "reports/current-evaluation" / f"{args.mode}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    if output.exists():
        raise ValueError("Existing report is immutable; choose a new output")
    if args.mode in {"report", "compare", "rescore", "review-template", "review-score"}:
        if args.input_report is None:
            parser.error("--input-report is required")
        source = load_report(args.input_report)
        if args.mode == "review-template":
            persist(output, make_review(source, args.input_report))
            print(json.dumps({"n": len(source["results"]), "reviewed_n": 0, "status": "PENDING"}))
            return 0
        if args.mode == "review-score":
            if args.review is None:
                parser.error("--review is required")
            result = score_review(source, args.input_report, json.loads(args.review.read_text(encoding="utf-8")))
            persist(output, result)
            print(json.dumps({key: value for key, value in result.items() if key != "results"}, ensure_ascii=False))
            return int(result["status"] != "COMPLETE" or result["combined_pass"] != result["n"])
        if args.mode == "rescore":
            persist(output, rescore(source, args.input_report, args.dataset))
            print(json.dumps({"n": len(source["results"]), "new_model_requests": 0}))
            return 0
        if args.mode == "compare":
            if args.baseline is None:
                parser.error("--baseline is required")
            comparison = compare_reports(load_report(args.baseline), source)
            persist(output, comparison)
            print(json.dumps(comparison, ensure_ascii=False))
            return 0
        output = args.output or args.input_report.with_suffix(".md")
        if output.exists():
            raise ValueError("Existing report is immutable; choose a new output")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(describe(source), encoding="utf-8")
        print(str(output))
        return 0
    report = metadata(args.mode, args.dataset)
    if args.mode == "harness":
        from scripts.evaluation.harness_checks import run_checks

        report["results"] = run_checks()
        report["summary"] = {"n": len(report["results"]), "passed": sum(e["passed"] for e in report["results"])}
        persist(output, report)
        print(json.dumps(report["summary"]))
        return int(any(not entry["passed"] for entry in report["results"]))
    if args.mode == "replay":
        from resolveflow.replay.strict import strict_replay

        report["replay_profile"] = str(args.replay_dir)
        directories = sorted(args.replay_dir.glob("*/pack.json"))
        profile_path = args.replay_dir / "manifest.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}
        expected = {"resolveflow-replay-context-v4": 6, "resolveflow-replay-investigation-v5": 7,
                    "resolveflow-replay-usage-v6": 7, "resolveflow-replay-correction-v7": 13,
                    "resolveflow-replay-rag-v8": 13,
                    "resolveflow-replay-calibration-v9": 13,
                    "resolveflow-replay-harness-v10": 14}.get(
            profile.get("profile_version"), 5)
        if len(directories) != expected:
            raise ValueError(f"Expected {expected} replay packs; zero or incomplete steps cannot pass")
        for pack in directories:
            try:
                entry = {"id": pack.parent.name, **strict_replay(pack.parent)}
            except Exception as error:
                entry = {"id": pack.parent.name, "error": f"{type(error).__name__}: {error}"}
            report["results"].append(entry)
        report["summary"] = {
            "n": len(directories),
            "matched": sum(e.get("status") == "MATCH" for e in report["results"]),
        }
        persist(output, report)
        print(json.dumps(report["summary"]))
        return int(any("error" in e for e in report["results"]))
    guard = live_guard(args.live_budget) if args.mode == "live" else nullcontext()
    with guard, environment(dense=not args.bm25_only, dataset=args.dataset) as (_, index, encoder, pins):
        if args.mode == "rag":
            rag(report, index, encoder, pins, split=args.split, bm25_only=args.bm25_only, dataset=args.dataset)
        else:
            agents(
                report,
                index,
                encoder,
                pins,
                mode=args.mode,
                split=args.split,
                selected=args.case,
                output=output,
                live_budget=args.live_budget,
                dataset=args.dataset,
                model_calls=args.model_calls,
            )
    report["state"] = "FINISHED"
    persist(output, report)
    print(json.dumps(report["summary"], ensure_ascii=False))
    if args.mode in {"mock", "live"}:
        return int(report["summary"]["joint_correct"] != report["summary"]["n"])
    return int(any("error" in entry or entry.get("violations", 0) > 0 for entry in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
