"""Generic length, provenance, table structure and complete-context invariants."""

from __future__ import annotations

import copy
import hashlib

import pytest
from scripts.policy_chunks import build_chunks, complete_context, representations, split_text
from scripts.policy_drafts import build_draft


class CharacterTokenizer:
    def __call__(self, text, *, truncation=False, add_special_tokens=True, return_offsets_mapping=False):
        assert truncation is False and add_special_tokens is True
        output = {"input_ids": [0] + [ord(c) for c in text] + [1]}
        if return_offsets_mapping:
            output["offset_mapping"] = [(0, 0)] + [(i, i + 1) for i in range(len(text))] + [(0, 0)]
        return output


def block(index, text, **extra):
    return {
        "id": f"doc:b{index:04d}",
        "kind": "paragraph",
        "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "raw_fragment_sha256": hashlib.sha256(f"<p>{text}</p>".encode()).hexdigest(),
        "inline_heading_candidate": False,
        "locator": {"start_char": index, "end_char": index + 1},
        **extra,
    }


def bundle(body="Allowed under conditions."):
    blocks = [
        block(1, "Policy"),
        block(2, "Conditions"),
        block(3, body),
        block(4, "Exceptions"),
        block(5, "Customized items excluded."),
    ]
    document = {
        "source_id": "doc",
        "subject": "EXTERNAL:TEST",
        "source_url": "https://example.org/policy",
        "raw_sha256": "a" * 64,
        "status": "PENDING_REVIEW",
        "blocks": blocks,
        "warnings": [],
    }

    def ref(b, level):
        return {k: b[k] for k in ("id", "text_sha256", "raw_fragment_sha256")} | {"level": level}

    profile = {
        "source_id": "doc",
        "raw_sha256": "a" * 64,
        "annotation_origin": "CODEX_STRUCTURE_DRAFT",
        "headings": [ref(blocks[0], 1), ref(blocks[1], 2), ref(blocks[3], 2)],
        "table_headers": [],
        "relations": [{"from": blocks[1]["id"], "to": blocks[3]["id"], "kind": "CONTEXT_REQUIRED"}],
    }
    return {"documents": [build_draft(document, profile)], "status": "PENDING_HUMAN_REVIEW"}


@pytest.mark.parametrize(
    "text",
    ["长句没有任何标点" * 12, "One sentence. Another sentence! " * 8, "条件。例外：不能使用。\nA😀B\tC" * 5, " " * 80],
)
def test_split_preserves_every_character_without_truncation(text):
    pieces = split_text(text, CharacterTokenizer(), 17)
    assert "".join(p["text"] for p in pieces) == text
    assert all(len(CharacterTokenizer()(p["text"])["input_ids"]) <= 17 for p in pieces)
    for piece in pieces:
        start, end = piece["text_range"]
        assert text[start:end] == piece["text"]


def test_sentence_boundary_is_preferred_when_it_fits():
    text = "First sentence. Second sentence is long."
    pieces = split_text(text, CharacterTokenizer(), 25)
    assert pieces[0]["text"] == "First sentence."


def test_small_paragraph_is_not_split():
    assert len(split_text("Small.", CharacterTokenizer(), 16)) == 1


@pytest.mark.parametrize("limit", [True, 0, 2, "384"])
def test_invalid_token_budget_is_rejected(limit):
    with pytest.raises(ValueError, match="limit"):
        split_text("text", CharacterTokenizer(), limit)


def test_chunk_encoder_limit_cannot_be_overridden_by_target():
    with pytest.raises(ValueError, match="encoder"):
        build_chunks(bundle(), CharacterTokenizer(), 60, 50)


def test_direct_blocks_are_indexed_once_and_parent_text_is_not_duplicated():
    source = bundle("Long text " * 30)
    result = build_chunks(source, CharacterTokenizer(), 40, 64)
    fragments = [f for c in result["chunks"] for f in c["fragments"]]
    for b in source["documents"][0]["blocks"]:
        spans = [f for f in fragments if f["block_id"] == b["id"]]
        assert "".join(f["text"] for f in spans) == b["text"]
    assert all(c["encoder_tokens"] <= 40 for c in result["chunks"])
    assert result["publishable"] is False and result["indexable"] is False


def test_child_can_resolve_whole_condition_and_sibling_exception():
    result = build_chunks(bundle("Long condition " * 10), CharacterTokenizer(), 40, 64)
    chunk = next(c for c in result["chunks"] if any(f["block_id"] == "doc:b0003" for f in c["fragments"]))
    context = complete_context(result, chunk["id"], 2000)
    assert context["complete"] is True
    assert "Customized items excluded." in context["text"]
    assert "Long condition " * 10 in context["text"]


def test_context_overflow_is_explicit_and_does_not_return_a_cut_policy():
    result = build_chunks(bundle("Long condition " * 10), CharacterTokenizer(), 40, 64)
    chunk = next(c for c in result["chunks"] if any(f["block_id"] == "doc:b0003" for f in c["fragments"]))
    context = complete_context(result, chunk["id"], 20)
    assert context["status"] == "CONTEXT_TOO_LARGE" and context["complete"] is False
    assert context["text"] is None
    assert "doc:b0005" in context["required_block_ids"]


def test_table_rows_repeat_column_labels_and_keep_table_reference():
    source = bundle()
    table = block(
        6,
        "Reason | Fee\nDamage | Free",
        kind="table",
        rows=[
            [
                {"text": "Reason", "header": True, "rowspan": 1, "colspan": 1},
                {"text": "Fee", "header": True, "rowspan": 1, "colspan": 1},
            ],
            [
                {"text": "Damage", "header": False, "rowspan": 1, "colspan": 1},
                {"text": "Free", "header": False, "rowspan": 1, "colspan": 1},
            ],
        ],
    )
    document = source["documents"][0]
    document["blocks"].append(table)
    section = document["sections"][-1]
    section["direct_block_ids"].append(table["id"])
    section["subtree_block_ids"].append(table["id"])
    # The trusted draft carries a complete source context, not just a table row.
    unit = next(u for u in document["draft_units"] if u["heading_block_id"] == section["heading_block_id"])
    unit["context_block_ids"].append(table["id"])
    unit["context_text"] += "\n\n" + table["text"]
    unit["context_sha256"] = hashlib.sha256(unit["context_text"].encode()).hexdigest()
    result = build_chunks(source, CharacterTokenizer(), 64, 64)
    text = "\n".join(c["retrieval_text"] for c in result["chunks"])
    assert "Reason: Damage" in text and "Fee: Free" in text
    fragments = [f for c in result["chunks"] for f in c["fragments"] if f["block_id"] == table["id"]]
    assert {f["table_row"] for f in fragments} == {0, 1}


def test_changed_source_block_hash_is_not_accepted():
    source = bundle()
    source["documents"][0]["blocks"][2]["text"] = "different"
    with pytest.raises(ValueError, match="block"):
        build_chunks(source, CharacterTokenizer(), 40, 64)


def test_cross_source_context_reference_is_not_accepted():
    source = bundle()
    source["documents"][0]["draft_units"][0]["context_block_ids"].append("other:b0001")
    with pytest.raises(ValueError, match="context"):
        build_chunks(source, CharacterTokenizer(), 40, 64)


def test_complete_context_refuses_unknown_chunk_and_changed_context():
    result = build_chunks(bundle(), CharacterTokenizer(), 40, 64)
    with pytest.raises(ValueError, match="chunk"):
        complete_context(result, "other:chunk", 1000)
    bad = copy.deepcopy(result)
    chunk = bad["chunks"][0]
    bad["contexts"][chunk["context_id"]]["text"] = "changed"
    with pytest.raises(ValueError, match="hash"):
        complete_context(bad, chunk["id"], 1000)


def test_deterministic_ids_and_hashes_for_same_inputs():
    one = build_chunks(bundle(), CharacterTokenizer(), 40, 64)
    two = build_chunks(bundle(), CharacterTokenizer(), 40, 64)
    assert one == two


@pytest.mark.parametrize("mutation", ["duplicate_unit", "duplicate_context", "duplicate_owner", "missing_owner"])
def test_ambiguous_or_missing_bindings_fail_closed(mutation):
    source = bundle()
    document = source["documents"][0]
    if mutation == "duplicate_unit":
        document["draft_units"].append(copy.deepcopy(document["draft_units"][0]))
    elif mutation == "duplicate_context":
        document["draft_units"][1]["id"] = document["draft_units"][0]["id"]
    elif mutation == "duplicate_owner":
        document["sections"][-1]["direct_block_ids"].append("doc:b0003")
    else:
        document["sections"][-1]["direct_block_ids"].remove("doc:b0005")
    with pytest.raises(ValueError):
        build_chunks(source, CharacterTokenizer(), 40, 64)


def test_merged_table_does_not_pretend_to_have_a_simple_grid():
    table = {
        "kind": "table",
        "rows": [
            [{"text": "Condition", "header": True, "rowspan": 2, "colspan": 1}],
            [{"text": "Exception", "header": False, "rowspan": 1, "colspan": 1}],
        ],
    }
    rows = representations(table)
    assert [row["text"] for row in rows] == ["Condition", "Exception"]
    assert all(row["grid_requires_review"] and not row["column_headers"] for row in rows)


@pytest.mark.parametrize("limit", [False, 0, -1, "2000"])
def test_invalid_complete_context_cap_is_rejected(limit):
    result = build_chunks(bundle(), CharacterTokenizer(), 40, 64)
    with pytest.raises(ValueError, match="character"):
        complete_context(result, result["chunks"][0]["id"], limit)


def test_missing_token_offsets_cannot_silently_truncate():
    class InvalidOffsets(CharacterTokenizer):
        def __call__(self, text, **kwargs):
            encoded = super().__call__(text, **kwargs)
            if "offset_mapping" in encoded:
                encoded["offset_mapping"] = [(0, 0)] * len(encoded["input_ids"])
            return encoded

    with pytest.raises(ValueError, match="offsets"):
        split_text("long document" * 10, InvalidOffsets(), 17)
