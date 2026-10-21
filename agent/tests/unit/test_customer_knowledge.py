"""Business corpus provenance, semantic-family splits and scoped retrieval."""

from copy import deepcopy
from pathlib import Path

import pytest
from scripts.evaluation.customer_knowledge import load_dataset, make_packet, route_rankings, validate

ROOT = Path(__file__).resolve().parents[3]


def test_corpus_is_source_bound_and_reuses_exact_existing_policy_text():
    knowledge, queries = load_dataset(ROOT)
    assert len(knowledge["documents"]) == 16
    assert len(queries["cases"]) == 60
    assert len([d for d in knowledge["documents"] if d["kind"] == "EXISTING_SYNTHETIC_POLICY"]) == 6
    assert {q["split"] for q in queries["cases"]} == {"dev", "acceptance"}
    assert not (
        {q["family"] for q in queries["cases"] if q["split"] == "dev"}
        & {q["family"] for q in queries["cases"] if q["split"] == "acceptance"}
    )


def test_bad_provenance_gold_and_cross_split_paraphrases_fail():
    knowledge, queries = load_dataset(ROOT)
    corrupt = deepcopy(knowledge)
    corrupt["documents"][0]["text"] += " invented refund guarantee"
    with pytest.raises(ValueError):
        validate(ROOT, corrupt, queries)
    corrupt = deepcopy(queries)
    corrupt["cases"][0]["evidence_sets"] = [["DOES_NOT_EXIST"]]
    with pytest.raises(ValueError):
        validate(ROOT, knowledge, corrupt)
    corrupt = deepcopy(queries)
    corrupt["cases"][1]["split"] = "acceptance"
    with pytest.raises(ValueError):
        validate(ROOT, knowledge, corrupt)


def test_scope_checked_before_ranking_and_packet_uses_whole_text():
    knowledge, _ = load_dataset(ROOT)
    docs = knowledge["documents"]
    vectors = [[1.0, 0.0] for _ in docs]
    routes = route_rankings(knowledge, "M-1001", "2026.10", "签收没收到", vectors, [1.0, 0.0])
    assert len(routes) == 3
    assert all(h.merchant_id == "M-1001" and h.version == "2026.10" for r in routes for h in r)
    assert all(h.score > 0 for r in routes[1:] for h in r)
    packet = make_packet(knowledge, "M-1001", "2026.10", [docs[0]["id"]])
    assert packet["blocks"][0]["text"] == docs[0]["text"]
    with pytest.raises(ValueError):
        route_rankings(knowledge, "OTHER", "2026.10", "退款", vectors, [1.0, 0.0])
    with pytest.raises(ValueError):
        make_packet(knowledge, "M-1001", "2025.01", [docs[0]["id"]])


def test_packet_deduplicates_identity_not_text_and_missing_ids_fail():
    knowledge, _ = load_dataset(ROOT)
    rule = knowledge["documents"][0]["id"]
    packet = make_packet(knowledge, "M-1002", "2026.10", [rule, rule])
    assert len(packet["blocks"]) == 1
    assert packet["sources"][0]["merchant_id"] == "M-1002"
    assert "m1002" in packet["sources"][0]["name"]
    with pytest.raises(ValueError):
        make_packet(knowledge, "M-1002", "2026.10", ["forged"])


def test_all_read_has_no_embedding_or_gpu_dependency_and_nonanswers_are_not_scored():
    from scripts.customer_rag_benchmark import Search

    class Tokenizer:
        def encode(self, text):
            return type("Encoded", (), {"ids": list(text)})()

    knowledge, queries = load_dataset(ROOT)
    search = Search(knowledge, None, None, None, Tokenizer())
    case = next(q for q in queries["cases"] if q["answerability"] == "NEEDS_LIVE_TOOL")
    row = search.run(case, "all-read")
    assert row["packet_complete"] is None
    assert row["complete_at_3"] is None
    assert len(row["selected_ids"]) == len(knowledge["documents"])
    assert "query_encoding_ms" not in row["stages"]


def test_bm25_does_not_load_embedding_and_percentile_uses_real_samples():
    from scripts.customer_rag_benchmark import Search, percentile

    class Tokenizer:
        def encode(self, text):
            return type("Encoded", (), {"ids": list(text)})()

    knowledge, queries = load_dataset(ROOT)
    row = Search(knowledge, None, None, None, Tokenizer()).run(queries["cases"][0], "bm25")
    assert row["total_ms"] >= row["stages"]["lexical_ms"] >= 0
    assert len(row["selected_ids"]) <= 5
    assert percentile([10, 20, 30], 0.5) == 20
    assert percentile([10, 20, 30], 0.95) == 29
