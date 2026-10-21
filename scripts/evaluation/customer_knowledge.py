"""Source-bound, offline project knowledge. No policy publication or business writes."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import replace

import yaml
from resolveflow.policies.index import PolicyHit
from resolveflow.policies.retrieval import bm25_scores, cosine_similarity


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_dataset(root):
    directory = root / "evals/customer-rag-v5"
    knowledge, queries = [
        json.loads((directory / name).read_text(encoding="utf-8")) for name in ["knowledge.json", "queries.json"]
    ]
    validate(root, knowledge, queries)
    return knowledge, queries


def validate(root, knowledge, queries):
    docs = knowledge["documents"]
    ids = {d["id"] for d in docs}
    if len(ids) != len(docs) or knowledge["unique_documents"] != len(docs):
        raise ValueError("duplicate knowledge identity")
    for merchant, source in knowledge["policy_sources"].items():
        path = root / source["path"]
        original = yaml.safe_load(path.read_text(encoding="utf-8"))
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"] or original["merchant_id"] != merchant:
            raise ValueError("merchant policy provenance differs")
        actual = {r["rule_id"]: r["text"] for r in original["rules"]}
        if actual != {d["id"]: d["text"] for d in docs if d["kind"] == "EXISTING_SYNTHETIC_POLICY"}:
            raise ValueError("merchant rules differ from shared template")
    for d in docs:
        source = root / d["source_path"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != d["source_sha256"]:
            raise ValueError("source fingerprint differs")
        if sha(d["text"]) != d["content_sha256"] or not set(d["related_ids"]) <= ids:
            raise ValueError("source body or relations differ")
        if d["kind"] == "EXISTING_SYNTHETIC_POLICY":
            original = yaml.safe_load(source.read_text(encoding="utf-8"))
            matches = [r for r in original["rules"] if r["rule_id"] == d["id"]]
            if len(matches) != 1 or matches[0]["text"] != d["text"] or matches[0]["title"] != d["title"]:
                raise ValueError("policy source changed")
    cases = queries["cases"]
    if len({q["id"] for q in cases}) != len(cases):
        raise ValueError("duplicate query identity")
    families = defaultdict(set)
    for q in cases:
        scoped(knowledge, q["merchant_id"], q["version"])
        families[q["family"]].add(q["split"])
        if q["split"] not in {"dev", "acceptance"}:
            raise ValueError("unknown split")
        if q["answerability"] not in {"ANSWERABLE", "NEEDS_LIVE_TOOL", "NOT_IN_KNOWLEDGE"}:
            raise ValueError("unknown answerability")
        if bool(q["evidence_sets"]) != (q["answerability"] == "ANSWERABLE"):
            raise ValueError("answerability/evidence mismatch")
        if any(not group or not set(group) <= ids for group in q["evidence_sets"]):
            raise ValueError("unknown or empty evidence set")
    if any(len(splits) != 1 for splits in families.values()):
        raise ValueError("semantic family crossed splits")


def scoped(knowledge, merchant, version):
    if merchant not in knowledge["merchant_scopes"] or version != knowledge["version_pin"]:
        raise ValueError("unbound merchant/version")
    return knowledge["documents"]


def hits(knowledge, merchant, version):
    docs = scoped(knowledge, merchant, version)
    manifest = sha(
        json.dumps(
            {"merchant": merchant, "version": version, "documents": [(d["id"], d["content_sha256"]) for d in docs]},
            sort_keys=True,
        )
    )
    return [
        PolicyHit(
            "offline-knowledge:" + merchant,
            merchant,
            version,
            manifest,
            d["id"],
            d["id"],
            d["content_sha256"],
            d["title"],
            d["text"],
            0.0,
            "dense",
        )
        for d in docs
    ]


def route_rankings(knowledge, merchant, version, query, vectors, query_vector):
    documents = hits(knowledge, merchant, version)
    if len(vectors) != len(documents):
        raise ValueError("vector/document count differs")
    dense_scores = [cosine_similarity(v, query_vector) for v in vectors]
    body_scores = bm25_scores([d.text for d in documents], query)
    title_scores = bm25_scores([d.title for d in documents], query)
    routes = []
    for scores, positive in [(dense_scores, False), (body_scores, True), (title_scores, True)]:
        ranked = [replace(d, score=float(s)) for d, s in zip(documents, scores, strict=True) if not positive or s > 0]
        routes.append(sorted(ranked, key=lambda h: (-h.score, h.chunk_id))[:5])
    return routes


def make_packet(knowledge, merchant, version, selected):
    docs = {d["id"]: d for d in scoped(knowledge, merchant, version)}
    if not set(selected) <= set(docs):
        raise ValueError("unknown source identity")
    sources, blocks, source_refs = [], [], {}
    for key in dict.fromkeys(selected):
        d = docs[key]
        source_key = (d["source_path"], d["source_sha256"])
        if d["kind"] == "EXISTING_SYNTHETIC_POLICY":
            source = knowledge["policy_sources"][merchant]
            source_key = (source["path"], source["sha256"])
        if source_key not in source_refs:
            ref = "s" + str(len(sources))
            source_refs[source_key] = ref
            sources.append(
                {
                    "ref": ref,
                    "merchant_id": merchant,
                    "version": version,
                    "kind": "SYNTHETIC_PROJECT_KNOWLEDGE",
                    "name": source_key[0],
                }
            )
        blocks.append(
            {
                "ref": "b" + str(len(blocks)),
                "source_ref": source_refs[source_key],
                "knowledge_id": key,
                "title": d["title"],
                "text": d["text"],
            }
        )
    return {"version": "offline-project-knowledge-packet-v1", "sources": sources, "blocks": blocks}
