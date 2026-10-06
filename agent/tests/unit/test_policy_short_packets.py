import copy

import pytest
from agent.tests.unit.test_policy_context_packet_eval import fixture
from scripts.policy_context_packet_eval import canonical_json, catalog, make_packet, select_contexts
from scripts.policy_documents import digest
from scripts.policy_short_packet_eval import compact, resolve


def packet():
    draft, bundle, case = fixture()
    index = catalog(draft)
    selection = select_contexts(case, bundle["chunks"], bundle, index, 100)
    return compact(make_packet(selection, bundle, index, "deduplicated"))


def lookup(p, ledger, ref="C0", **kwargs):
    return resolve(
        p,
        ledger,
        ref,
        ledger_sha256=kwargs.pop("sha", digest(canonical_json(ledger).encode())),
        subject=kwargs.pop("subject", "EXTERNAL:T"),
        scope=kwargs.pop("scope", {("s", "v")}),
    )


def test_short_context_resolves_complete_original_evidence():
    p, ledger = packet()
    result = lookup(p, ledger)
    assert result["context_id"] == "ctx1"
    assert [b["text"] for b in result["blocks"]] == ["AAAA", "BBBB"]
    assert result["sources"][0]["raw_sha256"] == "v"
    assert "locator" not in canonical_json(p)
    assert "locator" in canonical_json(ledger)


@pytest.mark.parametrize("change", ["text", "subject", "snapshot", "refs", "url"])
def test_packet_or_ledger_tampering_fails_against_trusted_digest(change):
    p, ledger = packet()
    before = digest(canonical_json(ledger).encode())
    if change == "text":
        p["blocks"][0]["text"] = "fake"
    elif change == "refs":
        p["contexts"][0]["block_refs"].pop()
    else:
        ledger["full_packet"]["sources"][0][{"snapshot": "raw_sha256", "url": "source_url"}.get(change, change)] = (
            "other"
        )
    with pytest.raises(ValueError):
        lookup(p, ledger, sha=before)


@pytest.mark.parametrize("ref", ["C99", "s0", "unknown", "B0"])
def test_unknown_or_wrong_kind_alias_fails(ref):
    p, ledger = packet()
    with pytest.raises(ValueError):
        lookup(p, ledger, ref)


@pytest.mark.parametrize("params", [{"subject": "OTHER"}, {"scope": {("s", "older")}}])
def test_caller_scope_must_match_source(params):
    p, ledger = packet()
    with pytest.raises(ValueError):
        lookup(p, ledger, **params)


def test_server_ledger_is_not_mutated_by_lookup_or_returned_record():
    p, ledger = packet()
    before = copy.deepcopy(ledger)
    result = lookup(p, ledger, "b0")
    result["blocks"][0]["locator"]["line"] = 900
    assert ledger == before
