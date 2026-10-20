"""The experiment must rerank the untruncated union and refuse incomplete model inputs."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from scripts.evaluation.customer_rerank import LocalReranker, candidate_union

from tests.unit.test_support_retrieval import hit


def test_union_keeps_dense_tail_without_rank_fusion_or_duplicate_boost():
    dense = [hit(str(i)) for i in range(5)]
    lexical = [hit("new"), dense[0], dense[0]]
    result = candidate_union([dense, lexical])
    assert {h.rule_id for h in result} == {"0", "1", "2", "3", "4", "new"}
    assert len(result) == 6
    assert dense[-1] in result
    with pytest.raises(ValueError, match="original"):
        candidate_union([dense, [replace(dense[0], text="different conditions")]])
    with pytest.raises(ValueError, match="scope"):
        candidate_union([dense, [hit("other", merchant="M-B")]])


class Model:
    def __init__(self, length=10, scores=None):
        self.length = length
        self.scores = scores or [0.1, 0.9]
        self.calls = []

    def tokenizer(self, query, text, **kwargs):
        assert kwargs == {"truncation": False}
        return {"input_ids": [0] * self.length}

    def predict(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        return self.scores


def test_reranker_preserves_full_inputs_source_and_returns_stable_scores():
    model = Model()
    scorer = LocalReranker(model)
    a, b = hit("A"), hit("B")
    result, profile = scorer.rank("query", [a, b])
    assert [h.rule_id for h in result] == ["B", "A"]
    assert model.calls[0][0] == [("query", a.text), ("query", b.text)]
    assert model.calls[0][1] == {"batch_size": 8, "show_progress_bar": False}
    assert result[0].content_hash == b.content_hash and b.score == 0.5
    assert profile["pairs"] == 2 and profile["max_pair_tokens"] == 10
    assert profile["elapsed_ms"] >= 0
    tied, _ = LocalReranker(Model(scores=[0.5, 0.5])).rank("query", [b, a])
    assert [h.rule_id for h in tied] == ["A", "B"]


def test_oversize_or_bad_model_outputs_never_silently_change_candidates():
    model = Model(length=513)
    with pytest.raises(ValueError, match="window"):
        LocalReranker(model).rank("query", [hit("A")])
    assert model.calls == []
    for scores in [[0.5], [float("nan"), 1.0], [0.5, float("inf")]]:
        with pytest.raises(ValueError):
            LocalReranker(Model(scores=scores)).rank("query", [hit("A"), hit("B")])
    empty = LocalReranker(SimpleNamespace())
    assert empty.rank("query", [])[0] == []


def test_accelerator_timing_waits_before_start_and_after_forward():
    events = []

    class AsyncModel(Model):
        def predict(self, pairs, **kwargs):
            events.append("forward")
            return super().predict(pairs, **kwargs)

    LocalReranker(AsyncModel(), synchronize=lambda: events.append("synchronize")).rank("query", [hit("A"), hit("B")])
    assert events == ["synchronize", "forward", "synchronize"]
