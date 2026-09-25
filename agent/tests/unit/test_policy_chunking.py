"""Chunking and the two hashes a citation depends on (C07.1).

The properties here are the ones a wrong implementation fails *silently*: a chunker that cut a rule's
exception off would still retrieve something, and a hash computed over a different member set would still
produce 64 hex characters. So each test names the failure it excludes rather than the function it calls.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from resolveflow.contracts.canonical import content_hash
from resolveflow.policies.chunking import (
    MAX_RULE_TEXT_LENGTH,
    ChunkingError,
    chunk_id_for,
    chunk_of,
    chunks_of_bundle,
)

#: The rule from the shipped fixtures whose *exception* is the point of chunking rules whole. If a future
#: chunker splits text by length, this is the text it will cut in half.
RULE_WITH_EXCEPTION = {
    "rule_id": "R-LOST-EXC-001",
    "title": "丢失规则的例外：高价值行",
    "text": "例外：本规则不适用于支付金额超过 500000 分的订单行，此类行即使结论为 LOST 也不得自动退款，必须转人工。",
}


def test_chunk_ids_count_from_one_as_the_contract_writes_them() -> None:
    # ``c-01`` is the contract's own example and Java's ``PolicyRule.chunkIdFor``; storage counts rules from
    # zero. Reimplementing the conversion with a different base would make every citation from this index name
    # a chunk the service has never heard of.
    assert chunk_id_for(0) == "c-01"
    assert chunk_id_for(9) == "c-10"
    assert chunk_id_for(99) == "c-100"


def test_a_negative_position_is_refused_rather_than_numbered() -> None:
    with pytest.raises(ChunkingError):
        chunk_id_for(-1)


def test_the_content_hash_is_over_the_four_members_java_hashes() -> None:
    """The construction is ``docs/core-contracts.md:56``: bundle_id/chunk_id/title/text, canonical JSON.

    Computed here independently of the implementation under test — with ``json.dumps`` and an explicit
    sort — so the test would catch a change to the member set or the canonicalisation, not merely agree with
    whatever the module happens to do.
    """
    chunk = chunk_of("policy-logistics-2026.09", 0, "R-LOST-001", "承运商判定丢失", "承运商结论为 LOST 时全额退款。")
    expected_payload = {
        "bundle_id": "policy-logistics-2026.09",
        "chunk_id": "c-01",
        "title": "承运商判定丢失",
        "text": "承运商结论为 LOST 时全额退款。",
    }
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    assert chunk.content_hash == expected
    # And the project's own canonicaliser agrees with that spelling, which is the cross-language claim.
    assert chunk.content_hash == content_hash(expected_payload)


def test_the_same_wording_in_two_bundles_is_two_hashes() -> None:
    """A citation has to say *which version* it cites, so the bundle id is inside the hash."""
    wording = "承运商结论为 LOST 时全额退款。"
    august = chunk_of("policy-logistics-2026.08", 0, "R-LOST-001", "承运商判定丢失", wording)
    september = chunk_of("policy-logistics-2026.09", 0, "R-LOST-001", "承运商判定丢失", wording)

    assert august.content_hash != september.content_hash
    assert august.chunk_id == september.chunk_id


def test_a_rule_and_its_exception_stay_in_one_chunk() -> None:
    """``docs/policy-rag.md:15``: 禁止把例外切掉.

    Asserted by identity rather than by length: the chunk's text must *be* the rule's text. A chunker that
    embedded a shortened form but cited the whole rule would pass a length check and still hand the model a
    citation to words the ranking never saw.
    """
    chunks = chunks_of_bundle("policy-logistics-2026.09", [RULE_WITH_EXCEPTION])

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.text == RULE_WITH_EXCEPTION["text"]
    assert chunk.embedded_text == RULE_WITH_EXCEPTION["text"]
    assert "例外" in chunk.text and "不得自动退款" in chunk.text
    assert chunk.citation == {
        "chunk_id": "c-01",
        "rule_id": "R-LOST-EXC-001",
        "content_hash": chunk.content_hash,
    }


def test_the_order_is_java_s_order_because_it_fixes_the_chunk_ids() -> None:
    rules = [
        {"rule_id": "R-B", "title": "乙", "text": "第二条。"},
        {"rule_id": "R-A", "title": "甲", "text": "第一条。"},
    ]
    chunks = chunks_of_bundle("policy-x", rules)

    # R-B is first because the source file put it first, even though R-A sorts earlier. Re-sorting here would
    # renumber the chunks and invalidate every citation the service would otherwise accept.
    assert [(chunk.rule_id, chunk.chunk_id) for chunk in chunks] == [("R-B", "c-01"), ("R-A", "c-02")]


def test_a_bundle_with_no_rules_is_refused() -> None:
    with pytest.raises(ChunkingError, match="no rules"):
        chunks_of_bundle("policy-x", [])


def test_a_rule_id_used_twice_is_refused() -> None:
    rules = [
        {"rule_id": "R-A", "title": "甲", "text": "第一条。"},
        {"rule_id": "R-A", "title": "甲又", "text": "重复。"},
    ]
    with pytest.raises(ChunkingError, match="twice"):
        chunks_of_bundle("policy-x", rules)


def test_a_rule_missing_a_member_names_the_member() -> None:
    with pytest.raises(ChunkingError, match="title"):
        chunks_of_bundle("policy-x", [{"rule_id": "R-A", "text": "没有标题。"}])


def test_text_over_the_contract_bound_is_refused_here_rather_than_later() -> None:
    """A rule Java could not serve cannot be indexed either; refusing names the rule.

    ``contracts/core/openapi-case.yaml``'s ``PolicyRule.text`` is ``maxLength: 4000``, so a longer rule would
    fail as a contract violation somewhere far from the file that caused it.
    """
    with pytest.raises(ChunkingError, match=str(MAX_RULE_TEXT_LENGTH)):
        chunk_of("policy-x", 0, "R-LONG", "标题", "字" * (MAX_RULE_TEXT_LENGTH + 1))
