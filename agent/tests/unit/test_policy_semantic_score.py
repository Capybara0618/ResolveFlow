from scripts.policy_semantic_score import score


def test_unassessed_and_empty_evidence_do_not_count_as_perfect_recall():
    judgments = {"results": [
        {"id": "good", "status": "VALIDATED_MODEL_JUDGMENT", "judgment": {
            "answerability": "ANSWERABLE", "required": [{"source_id": "s", "block_id": "missing"}],
        }},
        {"id": "missing", "status": "ERROR", "judgment": None},
        {"id": "clarify", "status": "VALIDATED_MODEL_JUDGMENT", "judgment": {
            "answerability": "NEEDS_CLARIFICATION", "required": [],
        }},
    ]}
    full = {"sources": [{"ref": "s0", "source_id": "s"}], "blocks": [{"source_ref": "s0", "block_id": "other"}]}
    cache = {"results": [{
        "query_id": q, "method": "dense", "k": 2, "selection_sha256": "fixed",
        "ledger": {"full_packet": full},
    } for q in ("good", "missing", "clarify")]}
    report = score(judgments, cache)
    summary = report["summaries"][0]
    assert summary["all_queries"] == 3 and summary["model_evidence_denominator"] == 1
    assert summary["all_required_covered"] == 0 and summary["unassessed_protocol_errors"] == 1
    assert report["official_human_recall"] is None
    assert report["results"][1]["all_required_covered"] is None
    assert report["results"][2]["all_required_covered"] is None
