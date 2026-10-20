"""Separate title recall still passes the production merchant/generation gates."""

from dataclasses import replace

import pytest

from resolveflow.policies.index import PolicyIndex, PolicyIndexNotReadyError
from tests.integration.test_policy_index import LOGISTICS_SEPTEMBER


def test_title_recall_uses_source_field_and_keeps_complete_original(agent_db):
    index = PolicyIndex(agent_db)
    # With exactly two documents, BM25 IDF is zero for every singleton term.
    bundle = replace(
        LOGISTICS_SEPTEMBER,
        rules=[*LOGISTICS_SEPTEMBER.rules, {"rule_id": "OTHER", "title": "商品破损", "text": "破损须人工核验。"}],
    )
    generation = index.build(bundle)
    args = dict(
        merchant_id=bundle.merchant_id,
        bundle_ids=[bundle.bundle_id],
        manifest_hash=bundle.manifest_hash,
        generation_ids={bundle.bundle_id: generation.generation_id},
        query="七天无扫描",
        top_k=2,
        path="bm25",
        lexical_field="title",
    )
    result = index.search(**args)
    assert result[0].rule_id == "R-NOSCAN-7D"
    assert result[0].text == bundle.rules[1]["text"]
    assert result[0].title == bundle.rules[1]["title"]
    with pytest.raises(PolicyIndexNotReadyError):
        index.search(**{**args, "merchant_id": "M-other"})
    with pytest.raises(PolicyIndexNotReadyError):
        index.search(**{**args, "generation_ids": {bundle.bundle_id: "missing"}})
    with pytest.raises(ValueError):
        index.search(**{**args, "path": "dense"})
