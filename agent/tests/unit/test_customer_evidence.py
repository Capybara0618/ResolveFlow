"""Evidence expansion must preserve admitted anchors and source/version boundaries."""

import hashlib
from copy import deepcopy

import pytest
from scripts.evaluation.customer_evidence import assemble


class Tokenizer:
    def encode(self, text):
        return type("Encoded", (), {"ids": list(text)})()


def fixture():
    def sha(text):
        return hashlib.sha256(text.encode()).hexdigest()

    blocks = {
        ("doc", "v1", key): {
            "id": key,
            "text": text,
            "text_sha256": sha(text),
            "subject": "M",
            "ordinal": n,
        }
        for n, (key, text) in enumerate([("rule", "base rule"), ("exception", "important exception")])
    }
    context_text = "base rule\n\nimportant exception"
    child = {
        "id": "child",
        "source_id": "doc",
        "raw_sha256": "v1",
        "subject": "M",
        "context_id": "parent",
        "fragments": [{"block_id": "rule", "text_range": [0, 9], "table_row": None}],
    }
    bundle = {
        "chunks": [child],
        "contexts": {
            "parent": {
                "source_id": "doc",
                "raw_sha256": "v1",
                "subject": "M",
                "required_block_ids": ["rule", "exception"],
                "text": context_text,
                "text_sha256": sha(context_text),
            }
        },
    }
    index = {"blocks": blocks, "sources": {("doc", "v1"): {"subject": "M"}}}
    case = {"subject": "M", "scope": [{"source_id": "doc", "raw_sha256": "v1"}]}
    return case, child, bundle, index


def test_parent_expansion_preserves_anchor_and_adds_exact_exception_once():
    case, child, bundle, index = fixture()
    packet = assemble(case, [child, child], bundle, index, Tokenizer(), expand=True)
    assert packet["body"] == "base rule\n\nimportant exception"
    assert len(packet["pieces"]) == 2
    assert packet["admitted_child_ids"] == ["child"]
    assert packet["expanded_context_ids"] == ["parent"]
    assert all(p["raw_sha256"] == "v1" for p in packet["pieces"])


def test_parent_over_budget_keeps_direct_anchor_and_never_truncates_parent():
    case, child, bundle, index = fixture()
    packet = assemble(case, [child], bundle, index, Tokenizer(), expand=True, max_chars=12, max_tokens=12)
    assert packet["body"] == "base rule"
    assert packet["blocked_context_ids"] == ["parent"]
    assert packet["expanded_context_ids"] == []


def test_overlap_is_merged_but_disjoint_source_spans_keep_the_gap():
    case, child, bundle, index = fixture()
    child["fragments"] = [
        {"block_id": "rule", "text_range": [0, 4]},
        {"block_id": "rule", "text_range": [2, 6]},
        {"block_id": "rule", "text_range": [8, 9]},
    ]
    packet = assemble(case, [child], bundle, index, Tokenizer())
    assert [p["text_range"] for p in packet["pieces"]] == [[0, 6], [8, 9]]
    assert packet["body"] == "base r\n\ne"


def test_scope_original_and_parent_tampering_are_rejected():
    case, child, bundle, index = fixture()
    wrong = deepcopy(child)
    wrong["raw_sha256"] = "v2"
    with pytest.raises(ValueError):
        assemble(case, [wrong], bundle, index, Tokenizer())
    case["subject"] = "OTHER"
    with pytest.raises(ValueError):
        assemble(case, [child], bundle, index, Tokenizer())
    case["subject"] = "M"
    bundle["contexts"]["parent"]["text"] = "missing exception"
    with pytest.raises(ValueError):
        assemble(case, [child], bundle, index, Tokenizer(), expand=True)


def test_forged_or_invalid_spans_cannot_count_as_evidence():
    case, child, bundle, index = fixture()
    child["fragments"][0]["text_range"] = [0, 99]
    with pytest.raises(ValueError):
        assemble(case, [child], bundle, index, Tokenizer())


def test_token_budget_is_checked_independently_of_character_budget():
    case, child, bundle, index = fixture()
    packet = assemble(case, [child], bundle, index, Tokenizer(), expand=True, max_chars=1000, max_tokens=10)
    assert packet["body"] == "base rule"
    assert packet["blocked_context_ids"] == ["parent"]


def test_invalid_parent_binding_and_corrupt_source_hash_are_rejected():
    case, child, bundle, index = fixture()
    bundle["contexts"]["parent"]["raw_sha256"] = "other"
    with pytest.raises(ValueError, match="binding"):
        assemble(case, [child], bundle, index, Tokenizer(), expand=True)
    index["blocks"][("doc", "v1", "rule")]["text"] = "tampered!"
    with pytest.raises(ValueError, match="hash"):
        assemble(case, [child], bundle, index, Tokenizer())


def test_table_row_uses_canonical_representation_and_keeps_row_identity():
    case, child, bundle, index = fixture()
    block = index["blocks"][("doc", "v1", "rule")]
    block.update(kind="table", rows=[[{"text": "base"}, {"text": "rule"}]])
    child["fragments"][0].update(table_row=0, text_range=[0, 11])
    packet = assemble(case, [child], bundle, index, Tokenizer())
    assert packet["body"] == "base | rule"
    assert packet["pieces"][0]["table_row"] == 0


def test_all_admitted_child_anchors_are_reserved_before_parent_expansion():
    case, child, bundle, index = fixture()
    other = deepcopy(child)
    other["id"] = "second"
    other["fragments"] = [{"block_id": "exception", "text_range": [0, 9]}]
    bundle["chunks"].append(other)
    packet = assemble(case, [child, other], bundle, index, Tokenizer(), expand=True, max_chars=20)
    assert packet["admitted_child_ids"] == ["child", "second"]
    assert packet["body"] == "base rule\n\nimportant"
    assert packet["blocked_context_ids"] == ["parent"]
