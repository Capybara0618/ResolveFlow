from scripts.resume_rag_benchmark import evidence_scores, summarize


def atom(block):
    return dict(source_id="s", raw_sha256="r", block_id=block, table_row=None, text_range=[0, 10])


def chunk(block, end=10):
    return dict(
        id=block, source_id="s", raw_sha256="r", fragments=[dict(block_id=block, table_row=None, text_range=[0, end])]
    )


def test_alternative_sets_and_partial_span():
    ranked = [(chunk("a", 5), 3), (chunk("b"), 2), (chunk("c"), 1)]
    result = evidence_scores(ranked, [[atom("a"), atom("b")], [atom("c")]], 3)
    assert result == dict(recall=1.0, complete=True, mrr=0.5)
    assert evidence_scores(ranked, [[atom("a"), atom("b")]], 3)["recall"] == 0.5
    assert not evidence_scores(ranked, [[atom("a"), atom("b")]], 3)["complete"]


def test_summary_does_not_count_nonanswerable_or_timing_repetitions():
    rows = [
        dict(
            variant="A",
            cohort="original",
            answerability="ANSWERABLE",
            scores={"3": dict(recall=0.5, complete=False, mrr=0.5), "5": dict(recall=1.0, complete=True, mrr=0.5)},
        )
    ]
    rows.append(dict(variant="A", cohort="original", answerability="NOT_IN_CORPUS", scores={}))
    timings = [dict(variant="A", cohort="original", elapsed_ms=n) for n in [1, 2, 3, 4]]
    result = summarize(rows, timings)["A:original"]
    assert result["answerable_n"] == 1
    assert result["query_n"] == 2
    assert result["timing_n"] == 4
    assert result["recall_at_3"] == 0.5
    assert result["complete_at_3_n"] == 0
    assert result["complete_at_5_n"] == 1
