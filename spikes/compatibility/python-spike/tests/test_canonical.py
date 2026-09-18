"""T00 gate: the Python half of the cross-language canonicalisation fixture.

The Java half lives in com.resolveflow.spike.CrossLanguageHashIT and reads the same
files. Agreement between two independently written implementations is the evidence;
either one alone is just an assertion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spike_py.canonical import (
    CanonicalizationError,
    _utf16_sort_key,
    canonicalize,
    content_hash,
    payload_hash,
)

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
INPUTS = CONTRACTS / "cross-language-hash-inputs.json"
EXPECTED = CONTRACTS / "cross-language-hash-expected.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixture_files_exist():
    assert INPUTS.is_file(), f"missing fixture: {INPUTS}"
    assert EXPECTED.is_file(), f"missing frozen values: {EXPECTED}"


def test_execution_payload_hashes_match_frozen_values():
    inputs = _load(INPUTS)
    expected = _load(EXPECTED)["execution_payload_hashes"]

    for item in inputs["execution_payloads"]:
        name = item["name"]
        assert name in expected, f"no frozen hash for payload {name}"
        assert payload_hash(item["payload"]) == expected[name], f"payload hash drift for {name}"


def test_content_hashes_match_frozen_values():
    inputs = _load(INPUTS)
    expected = _load(EXPECTED)["content_hashes"]

    for item in inputs["content_hashes"]:
        name = item["name"]
        assert name in expected, f"no frozen hash for content {name}"
        assert content_hash(item["value"]) == expected[name], f"content hash drift for {name}"


def test_hash_is_sha256_hex():
    inputs = _load(INPUTS)
    digest = payload_hash(inputs["execution_payloads"][0]["payload"])
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_runtime_fields_do_not_change_the_hash():
    inputs = _load(INPUTS)
    payload = dict(inputs["execution_payloads"][0]["payload"])
    before = payload_hash(payload)

    # entitlement_id is filled in after reservation; trace/send time are transport
    # concerns. None of them may be covered by the hash (contracts.md:17).
    enriched = {**payload, "entitlement_id": "ent-1", "payload_hash": before, "trace_id": "t-1"}
    assert payload_hash(enriched) == before


def test_utf16_key_ordering_differs_from_code_point_ordering():
    keys = ["�", "\U00010000", "b", "A"]
    assert sorted(keys) != sorted(keys, key=_utf16_sort_key), (
        "fixture would not exercise the ordering difference"
    )
    canonical = canonicalize({k: k for k in keys})
    # U+10000 sorts before U+FFFD under UTF-16 code-unit ordering.
    assert canonical.index("\U00010000") < canonical.index("�")


def test_float_money_is_refused():
    with pytest.raises(CanonicalizationError):
        canonicalize({"amount_minor": 200.5})


def test_missing_field_is_refused():
    with pytest.raises(CanonicalizationError, match="missing field"):
        payload_hash({"action": "REFUND", "operation_id": "x"})


def test_unknown_action_is_refused():
    with pytest.raises(CanonicalizationError):
        payload_hash({"action": "CHARGEBACK"})


def test_canonical_output_has_no_whitespace_and_is_stable():
    value = {"b": 1, "a": [1, True, None, "x"]}
    canonical = canonicalize(value)
    assert canonical == '{"a":[1,true,null,"x"],"b":1}'
    assert " " not in canonical
    assert canonicalize(value) == canonical