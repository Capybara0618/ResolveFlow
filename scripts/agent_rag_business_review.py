"""Review a private read-only snapshot of an existing Java-backed run; never access a live API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

import yaml  # noqa: E402
from scripts.agent_rag_source_review import (  # noqa: E402
    digest,
    match_searches,
    object_hash,
    policy_rows,
    read,
    verify_hits,
)


def audit_snapshot(snapshot: dict, bundle: dict, retained: dict) -> dict:
    if (
        snapshot["mode"] != "READ_ONLY_EXISTING_RUN"
        or snapshot["run_id"] != retained["run_id"]
        or snapshot["case_id"] != retained["case_id"]
    ):
        raise ValueError("existing business source identity differs")
    models = snapshot["models"]
    if not models or len(models) != retained["model_calls"] or any(m["state"] != "SAVED" for m in models):
        raise ValueError("saved model denominator/state differs")
    if any(m["response"]["mode"] != "live" for m in models):
        raise ValueError("existing source is not real model output")
    requests = [{"messages": m["request_body"]["messages"], "decision": m["response"]["decision"]} for m in models]
    observations = [t["observation"] for t in snapshot["tools"]]
    searches = match_searches({"requests": requests, "observations": observations})
    executed = [s for s in searches if s["execution"] == "EXECUTED"]
    if not executed:
        raise ValueError("zero executed policies is not a successful source audit")
    if [s["query"] for s in executed] != retained["policy_queries"]:
        raise ValueError("saved query/retained acceptance differs")
    if not retained["policy_refs"] or any(
        r["bundle_id"] != bundle["bundle_id"] or r["version"] != bundle["version"] for r in retained["policy_refs"]
    ):
        raise ValueError("accepted policy scope differs")
    rows, observed_refs = [], set()
    for search in executed:
        rules = verify_hits(search["observation"], bundle)
        if len(rules) > search["original_top_k"]:
            raise ValueError("business source top_k differs")
        if search["turn"] >= len(requests):
            raise ValueError("no saved model request after policy observation")
        next_policies = policy_rows(requests[search["turn"]])
        expected = {r["rule_id"]: r["text"] for r in bundle["rules"]}
        if any(
            p["bundle_id"] != bundle["bundle_id"]
            or p["version"] != bundle["version"]
            or p["text"] != expected.get(p["rule_id"])
            for p in next_policies
        ):
            raise ValueError("business P2 full body differs")
        visible = [p["rule_id"] for p in next_policies]
        if len(set(visible)) != len(visible) or not set(rules) <= set(visible):
            raise ValueError("business P2 source is missing or duplicated")
        fields = ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")
        observed_refs.update(tuple(h[k] for k in fields) for h in search["observation"]["result"]["hits"])
        rows.append(
            {
                "turn": search["turn"],
                "query": search["query"],
                "top_k": search["original_top_k"],
                "ranked_rules": rules,
                "full_policy_visible_next_turn": True,
                "duplicate_source_body_chars": 0,
                "observation_sha256": object_hash(search["observation"]),
            }
        )
    if any(tuple(r.get(k) for k in fields) not in observed_refs for r in retained["policy_refs"]):
        raise ValueError("accepted complete policy reference was not retrieved")
    return {
        "version": "agent-rag-business-source-v2",
        "origin": "CODEX_SOURCE_CHECK",
        "new_model_calls": 0,
        "production_writes": 0,
        "cases": 1,
        "run_id": snapshot["run_id"],
        "case_id": snapshot["case_id"],
        "source": "SAVED_JAVA_BACKED_SYNTHETIC_BUSINESS_RUN",
        "bundle_id": bundle["bundle_id"],
        "version_scope": bundle["version"],
        "rule_count": len(bundle["rules"]),
        "saved_models": len(models),
        "saved_tools": len(observations),
        "searches": rows,
        "accepted_action": retained["recommended_action"],
        "scope": "one source roundtrip, not quality accuracy",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, default=ROOT / "reports/rag-deployment/verification.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("business source audit is immutable")
    if not args.snapshot.resolve().is_relative_to((ROOT / "tmp").resolve()):
        raise ValueError("full business request snapshot must stay in ignored tmp")
    report = audit_snapshot(
        read(args.snapshot), yaml.safe_load(args.policy.read_text(encoding="utf-8")), read(args.acceptance)
    )
    report["source_inputs"] = {str(p): digest(p.read_bytes()) for p in (args.snapshot, args.policy, args.acceptance)}
    report["runner_sha256"] = digest(Path(__file__).read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps({k: report[k] for k in ("cases", "rule_count", "searches", "accepted_action")}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
