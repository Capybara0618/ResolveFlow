"""Load new source-aware inputs and resolve evidence without exposing labels to models."""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from scripts.policy_chunks import representations
from scripts.policy_codex_review import resolve_atom, validate_fragments
from scripts.policy_context_packet_eval import catalog

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "evals/customer-quantification-v1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def agent_cases():
    raw = read(DATA / "agent-cases.json")
    cases = raw["cases"]
    counts = Counter(c["family"] for c in cases)
    if len(cases) != 32 or counts != {"ordinary": 8, **{key: 4 for key in (
        "correction", "interrupt_resume", "goal_switch", "conflict_missing", "tool_failure", "compound")}}:
        raise ValueError("fixed family denominator differs")
    snapshots = {c["id"]: c for c in read(ROOT / raw["snapshot_source"])["cases"]}
    for case in cases:
        case["snapshot"] = deepcopy(snapshots[case["snapshot_id"]])
        override = case.get("snapshot_override")
        if override:
            case["snapshot"]["http_status"][override["tool"]] = override["status"]
            case["snapshot"]["facts"][override["tool"]] = override["body"]
        if case["complex"] != (case["family"] != "ordinary"):
            raise ValueError("complex partition differs")
        for turn in case["turns"]:
            if not turn["text"].strip() or not turn["criteria"] or turn["artifact"] not in {"NONE", "REFUND", "HANDOFF"}:
                raise ValueError("missing actual input or review criteria")
    return cases


def rag_data():
    data = read(DATA / "rag-queries.json")
    draft = read(ROOT / "tmp/policy-documents-v1/drafts-audited.json")
    children = read(ROOT / data["corpus"])
    index = catalog(draft)
    index["representations"] = {(d["source_id"], d["raw_sha256"], b["id"]): representations(b)
                                for d in draft["documents"] for b in d["blocks"]}
    validate_fragments(children["chunks"], index)
    queries = data["queries"]
    if len(queries) != 40 or Counter(q["answerability"] for q in queries) != {"ANSWERABLE": 32, "NOT_IN_CORPUS": 8}:
        raise ValueError("frozen RAG denominator differs")
    if len({q["id"] for q in queries}) != 40 or len({q["query"] for q in queries}) != 40:
        raise ValueError("duplicate RAG question")
    atoms = {}
    for query in queries:
        if not query["expected"].strip() or bool(query["evidence_sets"]) != (query["answerability"] == "ANSWERABLE"):
            raise ValueError("answerability and source label differ")
        atoms[query["id"]] = [[resolve_atom(ref, query, index) for ref in group] for group in query["evidence_sets"]]
    return queries, atoms, children, index


def audit():
    cases = agent_cases()
    queries, atoms, children, _ = rag_data()
    return {"conversations": len(cases), "customer_turns": sum(len(c["turns"]) for c in cases),
        "complex_conversations": sum(c["complex"] for c in cases), "groups": 2, "repeats": 2,
        "planned_conversation_runs": len(cases) * 4, "planned_customer_turn_runs": sum(len(c["turns"]) for c in cases) * 4,
        "rag_queries": len(queries), "rag_answerable": len([q for q in queries if atoms[q["id"]]]),
        "rag_chunks": len(children["chunks"]), "new_provider_requests": 0,
        "scope": "source-aware synthetic, old facts/corpus reused; no independent holdout or measured quality"}
