"""RAG scoring measures all required source spans; no-label ranking and scope remain separate."""

from copy import deepcopy

import pytest
from scripts.customer_quantification_rag import fuse, score
from scripts.evaluation.customer_quantification_data import rag_data


def test_rrf_deduplicates_source_chunks_and_uses_rank_not_incomparable_scores():
    first, second = {"id": "a"}, {"id": "b"}
    result = fuse([[(first, .01), (second, 999)], [(second, .99), (first, 0)], [(first, -10)]])
    assert len(result) == 2 and result[0][0] == first


def test_complete_evidence_requires_all_blocks_and_never_awards_unknown_query_a_hit():
    queries, atoms, children, index = rag_data()
    query = queries[1]  # Intro plus both exception blocks, not just a related fragment.
    scope = {(s["source_id"], s["raw_sha256"]) for s in query["scope"]}
    candidates = [(c, 1.) for c in children["chunks"] if (c["source_id"], c["raw_sha256"]) in scope]
    empty = score(query, [], atoms[query["id"]], children, index)
    assert empty["at_k"]["3"]["direct_complete"] is False
    assert empty["at_k"]["3"]["direct_recall"] == 0
    wrong = deepcopy(query)
    wrong["subject"] = "EXTERNAL:FOREIGN"
    with pytest.raises(ValueError, match="scope"):
        score(wrong, candidates[:3], atoms[query["id"]], children, index)
    unknown = score(queries[-1], [], [], children, index)
    assert unknown["at_k"]["3"]["direct_complete"] is None


def test_all_runs_have_unique_scoped_identities_and_keep_criteria_out_of_context():
    from scripts.customer_current_eval import prepare_turn
    from scripts.customer_quantification_agent import runs

    cases = runs()
    assert len(cases) == 128 and len({c["id"] for c in cases}) == 128
    requests = [prepare_turn(c, 0, [])[0] for c in cases]
    assert len({r.conversation_id for r in requests}) == 128
    assert all("criteria" not in str(r.context) and "required_sources" not in str(r.context) for r in requests)
