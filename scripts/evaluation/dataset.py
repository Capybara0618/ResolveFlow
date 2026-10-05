"""Load frozen inputs and separate gold; validate scope, pairs and file identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "evals/current"
ALIGNED_DATA = ROOT / "evals/aligned-v2"
GOLD_KEYS = frozenset(
    {
        "allowed_actions",
        "forbidden_actions",
        "must_tools",
        "must_rules",
        "gold",
        "expected_action",
        "review_status",
        "allowed_terminal_actions",
        "must_cite",
        "support_requirements",
    }
)


def read(name: str, directory: Path = DATA) -> Any:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def check_input(value: Any) -> None:
    if isinstance(value, dict):
        leaked = GOLD_KEYS.intersection(value)
        if leaked:
            raise ValueError(f"Gold-only fields in input: {sorted(leaked)}")
        for child in value.values():
            check_input(child)
    elif isinstance(value, list):
        for child in value:
            check_input(child)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(directory: Path = DATA) -> dict[str, int]:
    manifest = read("manifest.json", directory)
    required_files = {
        "agent/cases.json",
        "gold/agent.json",
        "gold/rag.json",
        "policies/bundles.json",
        "rag/queries.json",
        "harness/checks.json",
        "harness/context.json",
    }
    if not required_files <= set(manifest["files"]):
        raise ValueError("Frozen manifest omits required inputs/Gold")
    for name, expected in manifest["files"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file() or digest(path) != expected:
            raise ValueError(f"Frozen file mismatch: {name}")
    if manifest.get("input_profile"):
        replay = read("replay/manifest.json", directory)
        if replay["dataset_manifest_sha256"] != digest(directory / "manifest.json") or len(replay["files"]) != 10:
            raise ValueError("Replay calibration manifest mismatch")
        for name, expected in replay["files"].items():
            path = (directory / name).resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file() or digest(path) != expected:
                raise ValueError(f"Frozen replay mismatch: {name}")
    cases = read("agent/cases.json", directory)
    gold = read("gold/agent.json", directory)
    if len(cases) != 32 or len(gold) != len(cases):
        raise ValueError("Expected 32 cases and corresponding Gold")
    case_ids = {case["id"] for case in cases}
    if len(case_ids) != len(cases) or case_ids != set(gold):
        raise ValueError("Case ids and Gold differ")
    check_input(cases)
    families: dict[str, str] = {}
    pairs: dict[str, list[dict]] = {}
    for case in cases:
        if case["split"] not in {"dev", "test"}:
            raise ValueError("Unknown split")
        if families.setdefault(case["family"], case["split"]) != case["split"]:
            raise ValueError("Semantic family crosses split")
        pairs.setdefault(case["pair_id"], []).append(case)
        for key in ("merchant_id", "customer_id", "line_id"):
            if case["backend"]["order"].get(key) != case["scope"][key]:
                raise ValueError("Backend order subject differs from scope")
        if not gold[case["id"]]["allowed_actions"]:
            raise ValueError("Empty allowed actions")
        if set(gold[case["id"]]["allowed_actions"]) & set(gold[case["id"]]["forbidden_actions"]):
            raise ValueError("Contradictory Gold")
        if manifest.get("input_profile"):
            _validate_aligned_case(case, gold[case["id"]])
    for members in pairs.values():
        if len(members) != 2:
            raise ValueError("Incomplete pair")
        first, second = members
        for field in ("scope", "description", "family", "split"):
            if first[field] != second[field]:
                raise ValueError("Pair scope or request differs")
        if first["backend"] == second["backend"]:
            raise ValueError("Pair facts do not differ")
        a, b = gold[first["id"]], gold[second["id"]]
        if not (
            set(a["allowed_actions"]) & set(b["forbidden_actions"])
            or set(b["allowed_actions"]) & set(a["forbidden_actions"])
        ):
            raise ValueError("Pair lacks discriminating Gold")
    queries = read("rag/queries.json", directory)
    rag_gold = read("gold/rag.json", directory)
    if len(queries) != 60 or len({q["id"] for q in queries}) != 60 or set(rag_gold) != {q["id"] for q in queries}:
        raise ValueError("Expected 60 unique RAG queries and Gold")
    check_input(queries)
    families = {}
    policies = read("policies/bundles.json", directory)
    bundles = {p["bundle_id"]: p for p in policies}
    if len(bundles) != 6 or len({p["merchant_id"] for p in policies}) != 3:
        raise ValueError("Expected three merchants with six unique bundles")
    known = {p["bundle_id"]: {r["rule_id"] for r in p["rules"]} for p in policies}
    for bundle in policies:
        if len(known[bundle["bundle_id"]]) != 9 or not all(r["text"].strip() for r in bundle["rules"]):
            raise ValueError("Expected nine unique nonempty policy rules per bundle")
    for case in cases:
        bundle = bundles.get(case["bundle_id"])
        if bundle is None or bundle["merchant_id"] != case["scope"]["merchant_id"]:
            raise ValueError("Agent policy subject differs from case")
        answer = gold[case["id"]]
        if not set(answer["must_rules"]) <= known[bundle["bundle_id"]]:
            raise ValueError("Agent Gold refers to absent policy")
        if not set(answer["allowed_actions"] + answer["forbidden_actions"]) <= {
            "REFUND",
            "REJECT",
            "REQUEST_INFO",
            "MANUAL_REVIEW",
        }:
            raise ValueError("Unknown Gold action")
        if not set(answer["must_tools"]) <= {
            "get_order_context",
            "get_shipment_trace",
            "get_case_evidence",
            "get_policy_manifest",
            "get_refund_status",
        }:
            raise ValueError("Unknown Gold read tool")
    for query in queries:
        if query["split"] not in {"dev", "test"}:
            raise ValueError("Unknown RAG split")
        if families.setdefault(query["family"], query["split"]) != query["split"]:
            raise ValueError("RAG semantic family crosses split")
        if query["bundle_id"] not in known or not set(rag_gold[query["id"]]["must_rules"]) <= known[query["bundle_id"]]:
            raise ValueError("RAG Gold refers to absent policy")
        if bundles[query["bundle_id"]]["merchant_id"] != query["merchant_id"]:
            raise ValueError("RAG policy subject differs from query")
    for filename, expected in (("harness/checks.json", 20), ("harness/context.json", 8)):
        checks = read(filename, directory)
        if len(checks) != expected or len({c["id"] for c in checks}) != expected:
            raise ValueError("Incomplete or duplicate executable check list")
    return {
        "merchants": len({p["merchant_id"] for p in policies}),
        "bundles": len(policies),
        "agent_cases": len(cases),
        "pairs": len(pairs),
        "rag_queries": len(queries),
    }


def export_case(case_id: str, directory: Path = DATA) -> dict:
    cases = read("agent/cases.json", directory)
    found = next(case for case in cases if case["id"] == case_id)
    check_input(found)
    return found


def _validate_aligned_case(case, answer):
    from resolveflow.contracts.reviewer_input import ReviewerInput

    snapshot = ReviewerInput.model_validate(case["review_context"])
    wire = case["backend"]["evidence"]
    if (
        set(wire) != {"case_id", "input_revision", "evidence"}
        or wire["case_id"] != case["case_id"]
        or wire["input_revision"] != case["input_revision"]
    ):
        raise ValueError("Evidence list differs from dispatch binding")
    expected = [
        {
            "observation_id": m.evidence_id,
            "source_ref": m.source_ref,
            "source_version": m.source_version,
            "content_hash": m.content_hash,
        }
        for m in snapshot.materials
    ]
    if wire["evidence"] != expected or len({m.evidence_id for m in snapshot.materials}) != len(snapshot.materials):
        raise ValueError("Evidence references differ from snapshot")
    for item in [*snapshot.materials, *snapshot.questions]:
        if item.input_revision > case["input_revision"]:
            raise ValueError("Future revision in dispatch snapshot")
    for item in snapshot.materials:
        if item.content_hash != hashlib.sha256(item.content.encode()).hexdigest():
            raise ValueError("Synthetic material content hash mismatch")
    requirements = answer.get("support_requirements", [])
    if len({r["id"] for r in requirements}) != len(requirements):
        raise ValueError("Duplicate support requirement")
    for requirement in requirements:
        if set(requirement) != {"id", "any_of"} or not requirement["any_of"]:
            raise ValueError("Invalid support requirement")
        for option in requirement["any_of"]:
            if (
                not set(option) <= {"tool", "fields", "verification"}
                or option.get("tool") not in {"get_order_context", "get_shipment_trace", "get_case_evidence"}
                or not (option.get("fields") or option.get("verification"))
            ):
                raise ValueError("Invalid support alternative")
            if "verification" in option and (
                option["tool"] != "get_case_evidence" or option["verification"] != "CONFIRMED"
            ):
                raise ValueError("Invalid verification support")
