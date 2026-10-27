from types import SimpleNamespace

import pytest

from resolveflow.policies.segments import split_for_encoder
from tests.tokenizers import CharacterTokenizer


def test_segments_preserve_full_rule_including_trailing_exception():
    text = "退款规则。" * 80 + "例外：已退款不得再退。"
    pieces = split_for_encoder(text, CharacterTokenizer(), 32, 64)
    assert len(pieces) > 1
    assert "".join(p["text"] for p in pieces) == text
    assert pieces[-1]["text"].endswith("已退款不得再退。")
    assert all(p["encoder_tokens"] <= 32 for p in pieces)
    assert pieces[0]["start"] == 0 and pieces[-1]["end"] == len(text)
    assert all(a["end"] == b["start"] for a, b in zip(pieces, pieces[1:], strict=False))


@pytest.mark.parametrize("target,limit", [(0, 64), (True, 64), (65, 64), (20, False)])
def test_invalid_encoder_configuration_cannot_truncate(target, limit):
    with pytest.raises(ValueError):
        split_for_encoder("正文", CharacterTokenizer(), target, limit)


def test_embedding_guard_rejects_oversize_query_before_encode():
    from resolveflow.policies.retrieval import SentenceTransformerEmbedder

    calls = []
    encoder = SimpleNamespace(
        tokenizer=CharacterTokenizer(), max_seq_length=10,
        encode=lambda *args, **kwargs: calls.append(args),
    )
    wrapper = SentenceTransformerEmbedder("unused", _model=encoder)
    with pytest.raises(ValueError, match="no truncation"):
        wrapper.embed(["过长查询" * 10])
    assert calls == []
