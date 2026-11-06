"""Ownership migration must fail before ambiguous or missing owners can be reassigned."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from buyer_identity_migration import OwnershipConflict, audit_ownership, build_mapping


def test_platform_buyer_keeps_one_identity_across_two_shops():
    mapping = build_mapping([
        {"merchant_id": "A", "customer_id": "CA", "buyer_id": "B1"},
        {"merchant_id": "B", "customer_id": "CB", "buyer_id": "B1"},
    ], [])
    assert [row["buyer_id"] for row in mapping] == ["B1", "B1"]
    assert audit_ownership(mapping, [
        {"table": "orders", "merchant_id": "A", "customer_id": "CA", "count": 3},
        {"table": "support", "merchant_id": "B", "customer_id": "CB", "buyer_id": "B1", "count": 1},
    ]) == {"ready": True, "mapping_count": 2, "tables": {"orders": 3, "support": 1}, "conflicts": []}


def test_legacy_customer_ids_reused_by_two_shops_are_not_merged():
    accounts = [{"username": "alice", "role": "CUSTOMER", "merchant_id": "A", "customer_id": "C1"},
                {"username": "bob", "role": "CUSTOMER", "merchant_id": "B", "customer_id": "C1"}]
    mapping = build_mapping([], accounts)
    assert mapping == build_mapping([], reversed(accounts))
    assert mapping[0]["buyer_id"] != mapping[1]["buyer_id"]


@pytest.mark.parametrize("bindings", [
    [{"merchant_id": "A", "customer_id": "C1", "buyer_id": "B1"},
     {"merchant_id": "A", "customer_id": "C1", "buyer_id": "B2"}],
    [{"merchant_id": "A", "customer_id": "C1", "buyer_id": "B1"},
     {"merchant_id": "A", "customer_id": "C2", "buyer_id": "B1"}],
])
def test_conflicting_bindings_refuse_migration(bindings):
    with pytest.raises(OwnershipConflict):
        build_mapping(bindings, [])


def test_legacy_account_cannot_claim_a_platform_buyers_existing_orders():
    with pytest.raises(OwnershipConflict, match="旧账号与平台账号"):
        build_mapping([{"merchant_id": "A", "customer_id": "C1", "buyer_id": "B1"}],
                      [{"username": "legacy", "role": "CUSTOMER", "merchant_id": "A", "customer_id": "C1"}])


def test_missing_or_disagreeing_owner_blocks_readiness():
    mapping = build_mapping([{"merchant_id": "A", "customer_id": "C1", "buyer_id": "B1"}], [])
    report = audit_ownership(mapping, [
        {"table": "orders", "merchant_id": "A", "customer_id": "C2", "count": 1},
        {"table": "support", "merchant_id": "A", "customer_id": "C1", "buyer_id": "B2", "count": 1},
    ])
    assert not report["ready"]
    assert [row["code"] for row in report["conflicts"]] == ["UNMAPPED_OWNER", "BUYER_OWNER_MISMATCH"]
