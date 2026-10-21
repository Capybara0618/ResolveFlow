import hashlib
import json

from resolveflow.support.guide import guide_source


def test_guide_is_versioned_source_bound_and_not_refund_policy():
    source = guide_source()
    assert source["source_type"] == "KNOWLEDGE"
    assert source["version"] == "2026.10.21-v1"
    assert source["data"]["authority"] == "APPLICATION_GUIDE"
    assert "policy_manifest" not in source["data"] and "rule_id" not in source["data"]
    assert len(source["data"]["sections"]) == 10
    assert "不需要填写退款金额" in source["data"]["text"]
    assert "并不会自动创建退款工单" in source["data"]["text"]
    assert len(json.dumps(source, ensure_ascii=False).encode()) < 8192
    assert len(source["data"]["knowledge_sha256"]) == 64


def test_guide_returns_independent_values_with_exact_source_fingerprint():
    first = guide_source()
    first["data"]["text"] = "tampered"
    second = guide_source()
    assert second["data"]["text"] != "tampered"
    assert second["data"]["text_sha256"] == hashlib.sha256(second["data"]["text"].encode()).hexdigest()
