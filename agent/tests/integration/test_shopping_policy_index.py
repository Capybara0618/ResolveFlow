"""Both immutable shopping policy sources in isolated real PG indexes; no live models."""

from pathlib import Path

import pytest
import yaml

from resolveflow.contracts.canonical import content_hash
from resolveflow.policies import PolicyIndex, PolicyIndexNotReadyError, ServedBundle
from resolveflow.policies.chunking import chunk_of
from resolveflow.runtime.db import Database

ROOT = Path(__file__).resolve().parents[3]


def source_bundle(bundle_id: str) -> ServedBundle:
    # Test-only source construction. Runtime ingestion must fetch Java's stored hash via its API.
    raw = yaml.safe_load((ROOT / "fixtures/policies/bundles" / f"{bundle_id}.yaml").read_text(encoding="utf-8"))
    return ServedBundle(
        bundle_id=raw["bundle_id"],
        merchant_id=raw["merchant_id"],
        version=raw["version"],
        manifest_hash=content_hash(raw),
        safety_epoch=raw["safety_epoch"],
        rules=raw["rules"],
    )


@pytest.mark.parametrize("bundle_id", ["policy-logistics-2026.10", "policy-demo-m1002-logistics-2026.10"])
def test_shopping_rule_retrieval_preserves_identity_hash_and_entire_restrictions(
    agent_db: Database,
    bundle_id: str,
) -> None:
    index = PolicyIndex(agent_db)
    bundles = [source_bundle(name) for name in ("policy-logistics-2026.10", "policy-demo-m1002-logistics-2026.10")]
    for bundle in bundles:
        index.build(bundle)
    selected = next(bundle for bundle in bundles if bundle.bundle_id == bundle_id)
    hits = index.search(
        merchant_id=selected.merchant_id,
        bundle_ids=[bundle_id],
        manifest_hash=selected.manifest_hash,
        query="已付款未发货 NOT_SHIPPED ORDER_PAID",
        path="bm25",
        top_k=5,
    )
    assert hits
    assert {hit.bundle_id for hit in hits} == {bundle_id}
    assert {hit.merchant_id for hit in hits} == {selected.merchant_id}
    hit = next(hit for hit in hits if hit.rule_id == "R-UNSHIPPED-001")
    rule = selected.rules[0]
    expected = chunk_of(bundle_id, 0, rule["rule_id"], rule["title"], rule["text"])
    assert hit.content_hash == expected.content_hash
    java_hashes = {
        "policy-logistics-2026.10": "8be58dbf703806964c1a588d36d1af0e257e3133acd930a1173507b163d9da32",
        "policy-demo-m1002-logistics-2026.10": "94595529a8a68bf67b8392accce45aabf0e8682ec9812f94f0247c8dd906d500",
    }
    assert hit.content_hash == java_hashes[bundle_id]
    assert hit.chunk_id == expected.chunk_id
    assert hit.text == rule["text"]
    assert "UNKNOWN" in hit.text and "最终由售后专员决定" in hit.text
    with pytest.raises(PolicyIndexNotReadyError):
        index.search(
            merchant_id=selected.merchant_id,
            bundle_ids=[bundle_id],
            manifest_hash="f" * 64,
            query="未发货",
            path="bm25",
        )
    other = "M-1002" if selected.merchant_id == "M-1001" else "M-1001"
    with pytest.raises(PolicyIndexNotReadyError, match="another merchant"):
        index.search(
            merchant_id=other, bundle_ids=[bundle_id], manifest_hash=selected.manifest_hash, query="未发货", path="bm25"
        )
