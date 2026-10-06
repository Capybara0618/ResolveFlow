"""Generic representation and whole-context source-block deduplication invariants."""

import copy

import pytest
from scripts.policy_documents import digest
from scripts.policy_representation_eval import build_block_index, pack_contexts, represented_text


def fixture():
    blocks = [
        {"id": f"b{i}", "text": letter * 4, "text_sha256": digest((letter * 4).encode())}
        for i, letter in enumerate("ABC", 1)
    ]
    doc = {"source_id": "s", "raw_sha256": "v", "subject": "EXTERNAL:T", "blocks": blocks}
    contexts = {}
    chunks = []
    for index, ids in enumerate((["b1", "b2"], ["b2", "b3"]), 1):
        text = "\n\n".join(b["text"] for b in blocks if b["id"] in ids)
        contexts[f"ctx{index}"] = {
            "source_id": "s",
            "raw_sha256": "v",
            "subject": "EXTERNAL:T",
            "required_block_ids": ids,
            "text": text,
            "text_sha256": digest(text.encode()),
        }
        chunks.append(
            {
                "id": f"c{index}",
                "source_id": "s",
                "raw_sha256": "v",
                "subject": "EXTERNAL:T",
                "context_id": f"ctx{index}",
                "section_path": ["Doc", "Conditions"],
                "retrieval_text": "body",
            }
        )
    return {"documents": [doc]}, {"contexts": contexts, "chunks": chunks}


def test_block_union_preserves_both_contexts_without_repeating_overlap():
    draft, bundle = fixture()
    result = pack_contexts(bundle["chunks"], bundle, build_block_index(draft), 16)
    assert result["text"] == "AAAA\n\nBBBB\n\nCCCC"
    assert result["exported_chars"] == 16
    assert len(result["accepted_context_ids"]) == 2
    assert len(result["block_keys"]) == 3


def test_oversized_addition_is_atomic_and_cannot_drop_exception():
    draft, bundle = fixture()
    result = pack_contexts(bundle["chunks"], bundle, build_block_index(draft), 15)
    assert result["text"] == "AAAA\n\nBBBB"
    assert result["blocked_context_ids"] == ["ctx2"]
    assert ("s", "v", "b3") not in result["block_keys"]


def test_exact_duplicate_context_is_free_and_does_not_repeat_text():
    draft, bundle = fixture()
    result = pack_contexts([bundle["chunks"][0]] * 2, bundle, build_block_index(draft), 10)
    assert result["exported_chars"] == 10
    assert result["accepted_context_ids"] == ["ctx1"]


@pytest.mark.parametrize("mutation", ["unknown_block", "source", "snapshot", "text", "duplicate_ref"])
def test_forged_context_binding_or_source_blocks_are_rejected(mutation):
    draft, bundle = fixture()
    context = bundle["contexts"]["ctx1"]
    if mutation == "unknown_block":
        context["required_block_ids"] = ["missing"]
    if mutation == "source":
        context["source_id"] = "other"
    if mutation == "snapshot":
        context["raw_sha256"] = "old"
    if mutation == "text":
        context["text"] = "changed"
    if mutation == "duplicate_ref":
        context["required_block_ids"].append("b2")
    with pytest.raises(ValueError):
        pack_contexts(bundle["chunks"], bundle, build_block_index(draft), 100)


def test_duplicate_block_identity_and_changed_block_hash_fail():
    draft, _ = fixture()
    changed = copy.deepcopy(draft)
    changed["documents"][0]["blocks"][0]["text"] = "other"
    with pytest.raises(ValueError):
        build_block_index(changed)
    draft["documents"][0]["blocks"].append(draft["documents"][0]["blocks"][0])
    with pytest.raises(ValueError):
        build_block_index(draft)


def test_title_representation_preserves_body_and_does_not_modify_chunk():
    _, bundle = fixture()
    chunk = bundle["chunks"][0]
    before = copy.deepcopy(chunk)
    assert represented_text(chunk, "body") == "body"
    assert represented_text(chunk, "title_path") == "章节：Doc > Conditions\n\nbody"
    assert chunk == before


def test_unknown_representation_is_not_a_fallback():
    _, bundle = fixture()
    with pytest.raises(ValueError):
        represented_text(bundle["chunks"][0], "unknown")


def test_union_keeps_original_document_order_after_reversed_hits():
    draft, bundle = fixture()
    result = pack_contexts(list(reversed(bundle["chunks"])), bundle, build_block_index(draft), 16)
    assert result["text"] == "AAAA\n\nBBBB\n\nCCCC"


@pytest.mark.parametrize("limit", [False, 0, -1, "8000"])
def test_invalid_export_budget_fails(limit):
    draft, bundle = fixture()
    with pytest.raises(ValueError, match="limit"):
        pack_contexts(bundle["chunks"], bundle, build_block_index(draft), limit)


def test_actual_source_text_cannot_be_changed_even_with_a_matching_context_hash():
    draft, bundle = fixture()
    context = bundle["contexts"]["ctx1"]
    context["text"] = "fake text"
    context["text_sha256"] = digest(context["text"].encode())
    with pytest.raises(ValueError, match="complete source"):
        pack_contexts(bundle["chunks"], bundle, build_block_index(draft), 100)


def test_representation_overflow_is_rejected_before_embedding():
    from agent.tests.unit.test_policy_chunks import CharacterTokenizer
    from scripts.policy_representation_eval import make_variant

    _, bundle = fixture()

    class Local:
        dimension = 2

        def _encoder(self):
            class Encoder:
                tokenizer = CharacterTokenizer()
                max_seq_length = 10

            return Encoder()

        def embed(self, _):
            pytest.fail("overflow must be checked before embedding")

    with pytest.raises(ValueError, match="truncate"):
        make_variant(bundle, "title_path", Local())


def test_body_variant_keeps_original_spans_and_does_not_mutate_frozen_bundle():
    from agent.tests.unit.test_policy_chunks import CharacterTokenizer
    from scripts.policy_representation_eval import make_variant

    _, bundle = fixture()
    for chunk in bundle["chunks"]:
        chunk.update(
            content_sha256=digest(b"body"), fragments=[{"text_range": [0, 4], "text": "body"}], embedding=[1.0, 0.0]
        )
    before = copy.deepcopy(bundle)

    class Local:
        dimension = 2

        def _encoder(self):
            class Encoder:
                tokenizer = CharacterTokenizer()
                max_seq_length = 64

            return Encoder()

    variant, audit = make_variant(bundle, "body", Local())
    assert bundle == before and variant["chunks"][0]["fragments"] == before["chunks"][0]["fragments"]
    assert audit["max_encoder_tokens"] == 6


def test_reproduction_gate_refuses_different_ranking():
    from scripts.policy_representation_eval import check_body_reproduction

    original = {
        "at_k": {
            k: {
                "hits": [{"chunk_id": "a", "score": 0.5}],
                "exported_chars": 1,
                "blocked_context_ids": [],
                "draft_direct_missing": [],
                "draft_context_missing": [],
            }
            for k in ("2", "5")
        }
    }
    check_body_reproduction(original, original)
    changed = copy.deepcopy(original)
    changed["at_k"]["2"]["hits"][0]["chunk_id"] = "other"
    with pytest.raises(ValueError, match="ranking"):
        check_body_reproduction(changed, original)


def test_same_block_id_at_different_snapshots_is_not_deduplicated():
    draft, bundle = fixture()
    second_doc = copy.deepcopy(draft["documents"][0])
    second_doc["raw_sha256"] = "v2"
    draft["documents"].append(second_doc)
    context = copy.deepcopy(bundle["contexts"]["ctx1"])
    context["raw_sha256"] = "v2"
    bundle["contexts"]["ctx3"] = context
    chunk = copy.deepcopy(bundle["chunks"][0])
    chunk.update(id="c3", raw_sha256="v2", context_id="ctx3")
    bundle["chunks"].append(chunk)
    result = pack_contexts([bundle["chunks"][0], chunk], bundle, build_block_index(draft), 22)
    assert len(result["block_keys"]) == 4 and result["exported_chars"] == 22


def test_greedy_union_can_admit_an_earlier_context_and_block_a_later_one():
    draft, bundle = fixture()
    doc = draft["documents"][0]
    doc["blocks"].append({"id": "b4", "text": "DDDD", "text_sha256": digest(b"DDDD")})
    context = {
        "source_id": "s",
        "raw_sha256": "v",
        "subject": "EXTERNAL:T",
        "required_block_ids": ["b4"],
        "text": "DDDD",
        "text_sha256": digest(b"DDDD"),
    }
    bundle["contexts"]["ctx3"] = context
    third = copy.deepcopy(bundle["chunks"][0])
    third.update(id="c3", context_id="ctx3")
    bundle["chunks"].append(third)
    result = pack_contexts(bundle["chunks"], bundle, build_block_index(draft), 20)
    assert result["accepted_context_ids"] == ["ctx1", "ctx2"]
    assert result["blocked_context_ids"] == ["ctx3"]
    # Original whole-context packing would skip ctx2 and have room for ctx3.
    # Dedup saves text, but greedy admission is not a universal coverage theorem.
    assert ("s", "v", "b4") not in result["block_keys"]
