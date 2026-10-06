from types import SimpleNamespace

import pytest
from scripts.policy_documents import digest
from scripts.policy_fusion_eval import union_packet
from scripts.policy_structure_eval import inherited_probes


def test_union_keeps_every_admitted_source_block_and_separates_versions():
    keys = [("s", "v1", "b"), ("s", "v2", "b"), ("other", "v1", "b")]
    index = {"blocks": {k: {"text": "same words", "text_sha256": digest(b"same words")} for k in keys}}
    packet = union_packet(SimpleNamespace(block_keys=keys), index)
    assert packet["block_keys"] == keys
    assert packet["text"] == "same words\n\nsame words\n\nsame words"
    assert packet["same_admitted_evidence_set"] is True
    assert packet["complete_policy_guaranteed"] is False


def test_union_cannot_make_a_changed_source_look_valid_by_dropping_it():
    key = ("s", "v", "b")
    with pytest.raises(ValueError, match="original text/hash"):
        union_packet(SimpleNamespace(block_keys=[key]), {"blocks": {key: {"text": "changed", "text_sha256": "old"}}})


def test_union_refuses_ambiguous_duplicate_source_identity():
    key = ("s", "v", "b")
    with pytest.raises(ValueError, match="duplicate"):
        union_packet(SimpleNamespace(block_keys=[key, key]), {})


def test_probe_inherits_exact_scope_and_is_explicitly_synthetic():
    original = {"id": "q", "query": "old", "subject": "s", "scope": [{"source_id": "s", "raw_sha256": "v"}]}
    result = inherited_probes([original], [{"id": "p", "based_on": "q", "query": "paraphrase"}])[0]
    assert result["scope"] == original["scope"] and result["based_on"] == "q"
    assert result["origin"]["kind"] == "CODEX_SYNTHETIC_PARAPHRASE_NOT_BLIND"
    result["scope"][0]["raw_sha256"] = "changed"
    assert original["scope"][0]["raw_sha256"] == "v"


@pytest.mark.parametrize(
    "probes",
    [
        [{"id": "q", "based_on": "q", "query": "same-id"}],
        [{"id": "p", "based_on": "q", "query": "a"}, {"id": "p", "based_on": "q", "query": "b"}],
    ],
)
def test_probe_cannot_replace_a_frozen_query(probes):
    with pytest.raises(ValueError, match="identity"):
        inherited_probes([{"id": "q"}], probes)
