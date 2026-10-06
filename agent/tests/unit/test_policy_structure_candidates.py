from copy import deepcopy

import pytest
from scripts.policy_structure_candidates import (
    aggregate,
    atomic_bundle,
    local_packet,
    numbered_level,
    rrf,
    selected_spans,
    source_metadata,
    source_structure,
)


def document():
    texts = [
        "商品服务规则",
        "1. 一般规则",
        "完好商品在期限内申请。",
        "2. 不受理情形：",
        "（1）配件不完整；",
        "（2）另列限制；",
        "3. 运费说明",
        "确认责任后承担费用。",
    ]
    blocks = [
        {"id": f"x:{i}", "text": text, "kind": "paragraph", "text_sha256": str(i), "locator": {"line": i}}
        for i, text in enumerate(texts)
    ]
    return {
        "source_id": "x",
        "raw_sha256": "raw",
        "subject": "external",
        "blocks": blocks,
        "sections": [{"heading_block_id": "x:0", "level": 1}],
    }


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1.3不受理情形", 4),
        ("2. 其他规则", 3),
        ("2.3物流", 4),
        ("2.4退货需联系客服。", None),
        ("3. " + "很长的正文" * 20, None),
        ("标题无编号", None),
    ],
)
def test_typographic_candidates_do_not_turn_substantive_sentences_into_headings(text, expected):
    assert numbered_level(text) == expected


def test_original_text_unchanged_and_list_heading_is_carried():
    doc = document()
    original = deepcopy(doc)
    result = source_structure(doc)
    assert result["membership"]["x:4"]["heading_ids"] == ["x:0", "x:3"]
    assert result["membership"]["x:7"]["heading_ids"] == ["x:0", "x:6"]
    assert doc == original


def test_colon_introduction_owns_only_following_list():
    doc = document()
    doc["blocks"][3]["text"] = "需要注意以下例外："
    result = source_structure(doc)
    assert "x:3" in result["membership"]["x:4"]["heading_ids"]
    assert "x:3" not in result["membership"]["x:7"]["heading_ids"]


def chunk(key, source="x", version="raw", group="same"):
    return {
        "id": key,
        "source_id": source,
        "raw_sha256": version,
        "group_id": group,
        "context_id": key,
        "subject": "external",
        "fragments": [{"block_id": "x:4"}],
    }


@pytest.mark.parametrize("mode", ["atom", "parent"])
def test_grouping_never_merges_other_source_or_version(mode):
    hits = [(chunk("a"), 0.9), (chunk("b"), 0.8), (chunk("c", version="v2"), 0.7), (chunk("d", source="another"), 0.6)]
    bundle = {"contexts": {c["id"]: {"text_sha256": "identical-body"} for c, _ in hits}}
    assert [c["id"] for c, _ in aggregate(hits, mode, bundle)] == ["a", "c", "d"]


def test_complete_span_group_is_separate_from_raw_child_selection():
    a, b, c = chunk("a"), chunk("b"), chunk("c", group="other")
    assert selected_spans([a], {"chunks": [a, b, c]}, "atom") == [a, b]
    assert selected_spans([a], {"chunks": [a, b, c]}, "none") == [a]


def test_rrf_uses_ranks_and_zero_lexical_scores_contribute_nothing():
    a, b, z = chunk("a", group="a"), chunk("b", group="b"), chunk("z", group="z")
    ranked = rrf([(a, 0.9), (b, 0.1)], [(b, 999), (z, 0)], window=20, constant=60)
    assert ranked[0][0] == b
    assert ranked[0][1] == pytest.approx(1 / 62 + 1 / 61)
    assert [c["id"] for c, _ in ranked] == ["b", "a"]
    assert rrf([(a, 0.9), (b, 0.1)], [(b, 1e-9), (z, 0)]) == ranked


def test_rrf_two_spans_of_same_atom_are_one_identity():
    a, b = chunk("a"), chunk("b")
    result = rrf([(a, 0.5)], [(b, 1)])
    assert len(result) == 1 and result[0][1] == pytest.approx(2 / 61)


@pytest.mark.parametrize("kwargs", [{"window": 0}, {"constant": True}, {"constant": -1}])
def test_invalid_rrf_parameters_refused(kwargs):
    with pytest.raises(ValueError):
        rrf([], [], **kwargs)


def test_local_packet_keeps_exact_block_and_scope_titles_but_not_entire_document():
    doc = document()
    case = {"scope": [{"source_id": "x", "raw_sha256": "raw"}], "subject": "external"}
    result = local_packet(case, [chunk("hit")], {}, {"documents": [doc]}, 8000)
    assert "（1）配件不完整；" in result["text"] and "2. 不受理情形：" in result["text"]
    assert "确认责任后承担费用。" not in result["text"]
    assert result["complete_policy_guaranteed"] is False
    blocked = local_packet(case, [chunk("hit")], {}, {"documents": [doc]}, 1)
    assert blocked["block_keys"] == [] and blocked["blocked_ids"] == ["hit"]


@pytest.mark.parametrize("change", ["scope", "subject", "version"])
def test_local_packet_refuses_cross_subject_or_snapshot(change):
    doc = document()
    case = {"scope": [{"source_id": "x", "raw_sha256": "raw"}], "subject": "external"}
    hit = chunk("hit")
    if change == "scope":
        case["scope"][0]["source_id"] = "other"
    elif change == "subject":
        hit["subject"] = "other"
    else:
        doc["raw_sha256"] = "changed"
    with pytest.raises(ValueError):
        local_packet(case, [hit], {}, {"documents": [doc]}, 8000)


def test_dates_are_source_bound_and_do_not_create_merchant_authority():
    doc = document()
    doc["blocks"][2]["text"] = "版本生效日期：2024年08月09日"
    result = source_metadata({"documents": [doc]})[0]
    assert result["dates_found_in_source"][0]["date"] == "2024-08-09"
    assert result["dates_found_in_source"][0]["block_id"] == "x:2"
    assert result["authority"] == "EXTERNAL_REFERENCE_NOT_MERCHANT_POLICY"


class CharacterTokenizer:
    def __call__(self, text, **kwargs):
        return {
            "input_ids": [0, *range(len(text)), 0],
            "offset_mapping": [(0, 0), *[(i, i + 1) for i in range(len(text))], (0, 0)],
        }


def test_atomic_prefix_and_long_body_have_complete_source_spans_without_truncation():
    from types import SimpleNamespace

    from scripts.policy_documents import digest

    doc = document()
    doc["blocks"] = doc["blocks"][:3]
    doc["blocks"][2]["text"] = "甲" * 900 + "末尾限制不能删除。"
    for block in doc["blocks"]:
        block["text_sha256"] = digest(block["text"].encode())
        block["raw_fragment_sha256"] = "raw-part"
    original = {
        "chunks": [
            {"source_id": "x", "context_id": "parent", "fragments": [{"block_id": b["id"]}]} for b in doc["blocks"]
        ],
        "contexts": {"parent": {"text": "complete authoritative source"}},
    }
    output, _ = atomic_bundle({"documents": [doc]}, original, SimpleNamespace(tokenizer=CharacterTokenizer()))
    fragments = [f for c in output["chunks"] for f in c["fragments"] if f["block_id"] == "x:2"]
    assert len(fragments) > 1
    assert "".join(f["text"] for f in fragments) == doc["blocks"][2]["text"]
    assert fragments[0]["text_range"][0] == 0
    assert fragments[-1]["text_range"][1] == len(doc["blocks"][2]["text"])
    assert all(c["encoder_tokens"] <= 384 for c in output["chunks"])
    assert all(c["span_space"] == "ORIGINAL_BODY_NOT_SEARCH_PREFIX" for c in output["chunks"])
