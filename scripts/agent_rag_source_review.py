"""Offline audit of saved model search attempts, executed evidence and Codex source labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.contracts.core_models import ToolObservation  # noqa: E402
from resolveflow.harness.actions import ActionRefusedError, ModelDecision, validate_decision  # noqa: E402
from resolveflow.harness.local_reads import _search_digest  # noqa: E402
from resolveflow.policies.chunking import chunks_of_bundle  # noqa: E402
from scripts.evaluation.dataset import validate  # noqa: E402
from scripts.evaluation.scoring import score_agent  # noqa: E402


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def object_hash(value) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def saved_observation(value: dict) -> ToolObservation:
    """Archived model_dump includes optional defaults; it is not the core wire response."""
    payload = dict(value)
    if (
        payload.get("error") is not None
        and payload.get("source_version") is None
        and payload.get("content_hash") is None
    ):
        payload.pop("source_version", None)
        payload.pop("content_hash", None)
    return ToolObservation.model_validate_json(json.dumps(payload))


def sections(request: dict) -> list[tuple[str, str]]:
    result = []
    for message in request.get("messages", []):
        if message.get("role") != "user":
            continue
        content = message["content"]
        matches = list(re.finditer(r"【(P[0-4]·[^】]+)】", content))
        for i, match in enumerate(matches):
            result.append((match[1], content[match.end() : matches[i + 1].start() if i + 1 < len(matches) else None]))
    return result


def section_json(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        raise ValueError("saved structured section has no object")
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValueError("saved section is not an object")
    return value


def policy_rows(request: dict) -> list[dict]:
    rows = []
    for label, text in sections(request):
        if label == "P2·policy_table":
            table = section_json(text)
            fields = table["fields"]
            if (
                not fields
                or len(fields) != len(set(fields))
                or {"bundle_id", "version"} & set(fields)
                or not {"ref", "rule_id", "text"} <= set(fields)
            ):
                raise ValueError("invalid policy table fields")
            for values in table["rows"]:
                if len(values) != len(fields):
                    raise ValueError("invalid policy table row")
                rows.append(
                    {
                        "bundle_id": table["bundle_id"],
                        "version": table["version"],
                        **dict(zip(fields, values, strict=True)),
                    }
                )
        elif label.startswith("P2·policy:"):
            rows.append(section_json(text))
    if len({row["ref"] for row in rows}) != len(rows):
        raise ValueError("duplicate policy alias in saved frame")
    return rows


def match_searches(entry: dict) -> list[dict]:
    """Only unambiguous valid request/observed-query pairs; never infer rejected actions executed."""
    observations = [o for o in entry["observations"] if o["tool_name"] == "search_policy"]
    rows, valid_queries = [], []
    for turn, request in enumerate(entry["requests"], 1):
        action = request.get("decision") or {}
        if action.get("kind") != "SEARCH_POLICY":
            continue
        row = {
            "turn": turn,
            "query": action.get("query"),
            "request_sha256": object_hash(request),
            "original_top_k": action.get("arguments", {}).get("top_k", 5),
            "observation": None,
        }
        try:
            validate_decision(action)
        except ActionRefusedError as error:
            row.update(execution="ACTION_REFUSED", refusal=str(error))
        else:
            if "error" in request:
                row.update(execution="MODEL_REQUEST_ERROR")
            else:
                row.update(execution="NO_EXECUTION_RECORD")
                valid_queries.append(row["query"])
        rows.append(row)
    if any(n > 1 for n in Counter(valid_queries).values()):
        raise ValueError("repeated valid query is ambiguous without per-turn execution records")
    remaining = list(observations)
    for row in rows:
        if row["execution"] != "NO_EXECUTION_RECORD":
            continue
        matches = [o for o in remaining if (o.get("result") or {}).get("query") == row["query"]]
        if len(matches) > 1:
            raise ValueError("multiple observations for one query")
        if matches:
            if matches[0] is not remaining[0]:
                raise ValueError("saved query/observation order differs")
            row.update(execution="EXECUTED", observation=remaining.pop(0))
    if remaining:
        raise ValueError("unmatched executed policy observation")
    return rows


def verify_hits(observation: dict, bundle: dict) -> list[str]:
    result = observation["result"]
    hits = result["hits"]
    if observation.get("error") or type(result["hit_count"]) is not int or result["hit_count"] != len(hits):
        raise ValueError("failed policy observation or hit count differs")
    chunks = {c.rule_id: c for c in chunks_of_bundle(bundle["bundle_id"], bundle["rules"])}
    ids = []
    for hit in hits:
        chunk = chunks.get(hit["rule_id"])
        if chunk is None or any(
            hit.get(k) != v
            for k, v in {
                **chunk.citation,
                "bundle_id": bundle["bundle_id"],
                "version": bundle["version"],
                "title": chunk.title,
                "text": chunk.text,
                "source_ref": f"policy:{bundle['bundle_id']}/{chunk.chunk_id}",
            }.items()
        ):
            raise ValueError("policy hit source/version/full body differs")
        if hit["rule_id"] in ids:
            raise ValueError("duplicate policy identity in one search")
        ids.append(hit["rule_id"])
    return ids


def validate_labels(labels: dict, case_ids: set[str], query_ids: set[str]) -> tuple[dict, dict]:
    queries, cases = labels.get("queries", []), labels.get("cases", [])
    if (
        not queries
        or not cases
        or len(queries) != len(query_ids)
        or len(cases) != len(case_ids)
        or {q["id"] for q in queries} != query_ids
        or {c["id"] for c in cases} != case_ids
    ):
        raise ValueError("review labels empty, duplicate or missing; case Gold is not per-query evidence")
    for q in queries:
        if not q.get("evidence_sets") or not q.get("notes") or not q.get("request_sha256"):
            raise ValueError("query label has no explicit source basis")
    for c in cases:
        if not c.get("notes") or not c.get("case_sha256") or not c.get("entry_sha256"):
            raise ValueError("case source basis absent")
        for field in ("factual_support", "policy_application", "action_reason_alignment", "merchant_readability"):
            if c.get(field) not in {"PASS", "WARN", "FAIL", "NOT_COMPLETED"}:
                raise ValueError("unknown source review dimension")
    return {q["id"]: q for q in queries}, {c["id"]: c for c in cases}


def audit(manifest: dict) -> dict:
    for name, expected in manifest["inputs"].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or digest(path.read_bytes()) != expected:
            raise ValueError("frozen source input differs: " + name)
    dataset = ROOT / manifest["dataset"]
    validate(dataset)
    candidate = read(ROOT / manifest["candidate"])
    baseline = read(ROOT / manifest["baseline"])
    for report in (candidate, baseline):
        if report["mode"] != "live" or report["state"] != "FINISHED" or report["synthetic"] is not True:
            raise ValueError("finished synthetic live source required")
        if report["manifest_hash"] != digest((dataset / "manifest.json").read_bytes()):
            raise ValueError("saved report/data identity differs")
    cases = {c["id"]: c for c in read(dataset / "agent/cases.json")}
    bundles = {b["bundle_id"]: b for b in read(dataset / "policies/bundles.json")}
    if not cases or any(
        len(r["results"]) != len(cases) or {e["id"] for e in r["results"]} != set(cases) for r in (candidate, baseline)
    ):
        raise ValueError("nonzero complete case denominator required")
    entries = {e["id"]: e for e in candidate["results"]}
    attempts = {key: match_searches(e) for key, e in entries.items()}
    query_ids = {f"{key}:{a['turn']}" for key, rows in attempts.items() for a in rows}
    qlabels, clabels = validate_labels(read(ROOT / manifest["labels"]), set(cases), query_ids)
    query_rows, case_rows, all_frames = [], [], []
    gold = read(dataset / "gold/agent.json")
    for key, entry in entries.items():
        case, review = cases[key], clabels[key]
        if review["case_sha256"] != object_hash(case) or review["entry_sha256"] != object_hash(entry):
            raise ValueError("case review source binding differs")
        bundle = bundles[case["bundle_id"]]
        if bundle["merchant_id"] != case["scope"]["merchant_id"]:
            raise ValueError("case/bundle subject differs")
        chunks = {c.rule_id: c for c in chunks_of_bundle(bundle["bundle_id"], bundle["rules"])}
        pin_payload = {k: bundle[k] for k in ("bundle_id", "merchant_id", "version", "rules")}
        pin = digest(json.dumps(pin_payload, sort_keys=True, ensure_ascii=False).encode())
        if entry["harness_manifest"]["policy_manifest_hash"] != pin:
            raise ValueError("runtime policy pin differs")
        frames = [policy_rows(r) for r in entry["requests"]]
        for frame in frames:
            for row in frame:
                if (
                    row["bundle_id"] != bundle["bundle_id"]
                    or row["version"] != bundle["version"]
                    or row["rule_id"] not in chunks
                    or row["text"] != chunks[row["rule_id"]].text
                ):
                    raise ValueError("P2 full policy source differs")
            if len({r["rule_id"] for r in frame}) != len(frame):
                raise ValueError("duplicate source rule in P2 frame")
            all_frames.append(
                {"policies": len(frame), "body_chars": sum(len(r["text"]) for r in frame), "duplicate_body_chars": 0}
            )
        for attempt in attempts[key]:
            qid = f"{key}:{attempt['turn']}"
            label = qlabels[qid]
            if label["request_sha256"] != attempt["request_sha256"]:
                raise ValueError("query review source binding differs")
            if any(not group or not set(group) <= set(chunks) for group in label["evidence_sets"]):
                raise ValueError("reviewed query rule outside scoped source")
            observed = attempt["observation"]
            row = {k: v for k, v in attempt.items() if k != "observation"}
            row.update(
                id=qid,
                case_id=key,
                bundle_id=bundle["bundle_id"],
                merchant_id=bundle["merchant_id"],
                version=bundle["version"],
                review=label,
            )
            if observed:
                rules = verify_hits(observed, bundle)
                if len(rules) > attempt["original_top_k"]:
                    raise ValueError("actual hit count exceeds original top_k")
                expected = _search_digest([bundle["bundle_id"]], pin, attempt["query"])
                if (
                    observed["content_hash"] != expected
                    or observed["observation_id"] != f"policy-search-{expected[:32]}"
                    or observed["source_ref"] != f"policy:{bundle['bundle_id']}"
                    or observed["source_version"] != f"{bundle['bundle_id']}@{pin[:16]}"
                ):
                    raise ValueError("policy observation query/pin source differs")
                next_frame = frames[attempt["turn"]] if attempt["turn"] < len(frames) else []
                visible = {r["rule_id"] for r in next_frame}
                if not set(rules) <= visible:
                    raise ValueError("observed complete policy absent from next model request")
                row.update(
                    observation_id=observed["observation_id"],
                    observation_sha256=object_hash(observed),
                    ranked_rules=rules,
                    visible_next_turn=sorted(visible),
                    all_required_at_actual_k=any(set(g) <= set(rules) for g in label["evidence_sets"]),
                    all_required_at_2=any(set(g) <= set(rules[:2]) for g in label["evidence_sets"]),
                )
            query_rows.append(row)
        decision = entry.get("decision")
        parsed = ModelDecision.model_validate(decision) if decision else None
        observed_sources = [saved_observation(o) for o in entry["observations"]]
        result = SimpleNamespace(completed=entry["completed"], decision=parsed, observations=observed_sources)
        score = score_agent(result, gold[key], case=case)
        # Keep archived automatic scoring, including incomplete results; never rewrite the old report.
        for field, value in score.items():
            if entry.get(field) != value:
                raise ValueError(f"archived automatic score differs: {key}/{field}")
        policy_refs = (decision or {}).get("policy_refs", [])
        cited_rules = [r["rule_id"] for r in policy_refs]
        case_rows.append(
            {
                "id": key,
                "completed": entry["completed"],
                "kind": (decision or {}).get("kind"),
                "action": score["action"],
                "joint_correct": score["joint_correct"],
                "reason_code": entry["reason_code"],
                "cited_rules": cited_rules,
                "source_review": review,
                "old_automatic_score_reproduced": True,
                "policy_body_dedup_already_present": True,
            }
        )
    executed = [r for r in query_rows if r["execution"] == "EXECUTED"]
    completed = [r for r in case_rows if r["completed"]]
    baseline_counts = Counter(a["execution"] for e in baseline["results"] for a in match_searches(e))
    return {
        "version": "agent-rag-source-review-v1",
        "origin": "CODEX_REVIEW",
        "blind": False,
        "new_model_calls": 0,
        "production_writes": 0,
        "source_inputs": manifest["inputs"],
        "data_kind": "SYNTHETIC_BUSINESS_REAL_LLM_SAVED_REPORTS_NOT_JAVA_E2E",
        "query_results": query_rows,
        "case_results": case_rows,
        "summary": {
            "cases": len(cases),
            "completed": len(completed),
            "automatic_joint_correct": sum(r["joint_correct"] for r in case_rows),
            "search_attempts": len(query_rows),
            "search_execution": dict(Counter(r["execution"] for r in query_rows)),
            "baseline_search_execution_only": dict(baseline_counts),
            "executed_query_required_at_2": sum(r["all_required_at_2"] for r in executed),
            "executed_query_required_at_actual_k": sum(r["all_required_at_actual_k"] for r in executed),
            "executed_query_denominator": len(executed),
            "actual_top_k_values": sorted({r["original_top_k"] for r in executed}),
            "saved_request_frames": len(all_frames),
            "policy_frames": sum(f["policies"] > 0 for f in all_frames),
            "p2_duplicate_source_body_chars": sum(f["duplicate_body_chars"] for f in all_frames),
            "review_dimensions_completed_only": {
                field: dict(Counter(r["source_review"][field] for r in completed))
                for field in (
                    "factual_support",
                    "policy_application",
                    "action_reason_alignment",
                    "merchant_readability",
                )
            },
            "label_origin": "CODEX_SOURCE_REVIEW_NONBLIND_NOT_CUSTOMER_ACCURACY",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "evals/agent-rag-source-v1/manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("source audit output is immutable; use a new filename")
    report = audit(read(args.manifest))
    report.update(runner_sha256=digest(Path(__file__).read_bytes()), manifest_sha256=digest(args.manifest.read_bytes()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
