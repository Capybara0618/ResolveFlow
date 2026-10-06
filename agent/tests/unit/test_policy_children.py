import copy
import struct
from types import SimpleNamespace

import pytest
from agent.tests.conftest import StubEmbedder
from agent.tests.unit.test_policy_chunks import CharacterTokenizer
from resolveflow.policies.child_index import fingerprint, prepare, validate_children
from resolveflow.policies.chunking import chunk_of
from resolveflow.policies.segments import split_for_encoder


class Segmented(StubEmbedder):
    def policy_segments(self, text):
        return split_for_encoder(text, CharacterTokenizer(), 32, 64)


def data():
    parent = chunk_of("bundle", 0, "R", "Conditions", "完整条款。" * 30 + "例外不可删。")
    children = prepare((parent,), Segmented())
    generation = SimpleNamespace(
        child_count=len(children), embedding_dimension=8, retrieval_fingerprint=fingerprint(children)
    )
    return parent, children, generation


def test_index_children_reconstruct_parent_and_preserve_citation_identity():
    parent, children, generation = data()
    validate_children([parent], children, generation)
    assert "".join(c["text"] for c in children) == parent.text
    assert all(c["parent_chunk_id"] == parent.chunk_id for c in children)
    assert parent.chunk_id == "c-01"


def test_vector_fingerprint_matches_postgres_float32_roundtrip():
    parent, children, generation = data()
    stored = copy.deepcopy(children)
    for c in stored:
        c["embedding"] = list(struct.unpack("!8f", struct.pack("!8f", *c["embedding"])))
    assert fingerprint(stored) == generation.retrieval_fingerprint
    validate_children([parent], stored, generation)


@pytest.mark.parametrize("change", ["count", "text", "span", "vector", "parent", "duplicate"])
def test_index_integrity_rejects_lost_or_forged_child(change):
    parent, children, generation = data()
    if change == "count":
        children.pop()
    elif change == "text":
        children[0]["text"] = "伪造内容"
    elif change == "span":
        children[0]["end_offset"] -= 1
    elif change == "vector":
        children[0]["embedding"][0] += 0.01
    elif change == "parent":
        children[0]["parent_chunk_id"] = "unknown"
    else:
        children.append(children[0])
    with pytest.raises(ValueError):
        validate_children([parent], children, generation)


def test_legacy_encoder_does_not_claim_token_splitting():
    parent, _, _ = data()
    assert prepare((parent,), StubEmbedder()) is None
