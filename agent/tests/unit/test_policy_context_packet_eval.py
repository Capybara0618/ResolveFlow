"""Fixed evidence selection and lossless citation packets, independent of query Gold."""

import copy
from dataclasses import replace

import pytest
from scripts.policy_context_packet_eval import audit_pair, catalog, export_packet, make_packet, select_contexts
from scripts.policy_documents import digest


def fixture():
    blocks = [
        {
            "id": f"b{i}",
            "text": letter * 4,
            "text_sha256": digest((letter * 4).encode()),
            "raw_fragment_sha256": digest(letter.encode()),
            "locator": {"line": i},
        }
        for i, letter in enumerate("ABCD", 1)
    ]
    doc = {
        "source_id": "s",
        "subject": "EXTERNAL:T",
        "raw_sha256": "v",
        "source_url": "https://example.org",
        "blocks": blocks,
    }
    contexts, chunks = {}, []
    for i, refs in enumerate((["b1", "b2"], ["b2", "b3"], ["b4"]), 1):
        text = "\n\n".join(blocks[int(ref[1:]) - 1]["text"] for ref in refs)
        contexts[f"ctx{i}"] = {
            "source_id": "s",
            "subject": "EXTERNAL:T",
            "raw_sha256": "v",
            "text": text,
            "text_sha256": digest(text.encode()),
            "required_block_ids": refs,
            "section_path": ["Conditions"],
        }
        chunks.append(
            {"id": f"c{i}", "context_id": f"ctx{i}", "source_id": "s", "subject": "EXTERNAL:T", "raw_sha256": "v"}
        )
    case = {"subject": "EXTERNAL:T", "scope": [{"source_id": "s", "raw_sha256": "v"}]}
    return {"documents": [doc]}, {"contexts": contexts, "chunks": chunks}, case


def test_fixed_selection_does_not_admit_freed_space_context():
    draft, bundle, case = fixture()
    index = catalog(draft)
    selection = select_contexts(case, bundle["chunks"], bundle, index, 20)
    assert selection.context_ids == ("ctx1", "ctx3")
    assert selection.blocked_ids == ("ctx2",)
    packet = make_packet(selection, bundle, index, "deduplicated")
    assert [c["id"] for c in packet["contexts"]] == ["ctx1", "ctx3"]
    assert [b["block_id"] for b in packet["blocks"]] == ["b1", "b2", "b4"]


def test_both_representations_reconstruct_every_selected_context():
    draft, bundle, case = fixture()
    index = catalog(draft)
    selected = select_contexts(case, bundle["chunks"], bundle, index, 100)
    repeated = make_packet(selected, bundle, index, "repeated")
    dedup = make_packet(selected, bundle, index, "deduplicated")
    assert repeated["sources"] == dedup["sources"]
    by_ref = {b["ref"]: b for b in dedup["blocks"]}
    for a, b in zip(repeated["contexts"], dedup["contexts"], strict=True):
        assert a["block_refs"] == b["block_refs"]
        reconstructed = "\n\n".join(by_ref[r]["text"] for r in b["block_refs"])
        assert reconstructed == a["text"] == bundle["contexts"][a["id"]]["text"]
        assert digest(reconstructed.encode()) == b["text_sha256"]
    assert len(dedup["blocks"]) == 4
    assert sum(len(b["text"]) for b in dedup["blocks"]) < sum(len(c["text"]) for c in repeated["contexts"])


@pytest.mark.parametrize("mutation", ["subject", "snapshot", "source", "duplicate", "unknown"])
def test_hit_binding_must_be_in_frozen_query_scope(mutation):
    draft, bundle, case = fixture()
    hits = copy.deepcopy(bundle["chunks"])
    if mutation == "duplicate":
        hits.append(hits[0])
    elif mutation == "unknown":
        hits[0]["id"] = "unknown"
    else:
        hits[0][{"snapshot": "raw_sha256", "source": "source_id"}.get(mutation, mutation)] = "other"
    with pytest.raises(ValueError):
        select_contexts(case, hits, bundle, catalog(draft), 100)


@pytest.mark.parametrize("mutation", ["text", "refs", "locator", "url", "selected_ids", "selected_blocks"])
def test_selection_seal_detects_source_or_selection_drift(mutation):
    draft, bundle, case = fixture()
    index = catalog(draft)
    selection = select_contexts(case, bundle["chunks"], bundle, index, 100)
    if mutation == "text":
        bundle["contexts"]["ctx1"]["text"] = "fake"
    elif mutation == "refs":
        bundle["contexts"]["ctx1"]["required_block_ids"] = ["b1"]
    elif mutation == "locator":
        index["blocks"][("s", "v", "b1")]["locator"] = {"line": 100}
    elif mutation == "url":
        index["sources"][("s", "v")]["source_url"] = "https://other.org"
    elif mutation == "selected_ids":
        selection = replace(selection, context_ids=("ctx1",))
    else:
        selection = replace(selection, block_keys=selection.block_keys[:-1])
    with pytest.raises(ValueError):
        make_packet(selection, bundle, index, "deduplicated")


@pytest.mark.parametrize("limit", [True, 0, -1, "20"])
def test_invalid_selection_limit_is_rejected(limit):
    draft, bundle, case = fixture()
    with pytest.raises(ValueError):
        select_contexts(case, bundle["chunks"], bundle, catalog(draft), limit)


def test_payload_alias_does_not_erase_distinct_provenance():
    draft, bundle, case = fixture()
    # Same text under a different original block is not the same evidence identity.
    draft["documents"][0]["blocks"][2].update(text="AAAA", text_sha256=digest(b"AAAA"))
    b = bundle["contexts"]["ctx2"]
    b.update(required_block_ids=["b3", "b2"], text="AAAA\n\nBBBB", text_sha256=digest(b"AAAA\n\nBBBB"))
    with pytest.raises(ValueError, match="ambiguous"):
        select_contexts(case, bundle["chunks"], bundle, catalog(draft), 100)


class Characters:
    def encode(self, text, add_special_tokens=False):
        assert not add_special_tokens

        class Encoded:
            ids = list(text)

        return Encoded()


def test_token_refusal_is_atomic_and_includes_all_metadata():
    draft, bundle, case = fixture()
    index = catalog(draft)
    selection = select_contexts(case, bundle["chunks"], bundle, index, 100)
    packet = make_packet(selection, bundle, index, "deduplicated")
    whole = export_packet(packet, 100000, Characters())
    assert whole["complete"] and whole["packet"] == packet
    assert whole["tokens"] > 16
    refused = export_packet(packet, whole["tokens"] - 1, Characters())
    assert not refused["complete"] and refused["packet"] is None
    assert refused["packet_sha256"] == whole["packet_sha256"]
    assert export_packet(packet, whole["tokens"], Characters())["complete"]


def test_selection_does_not_consult_question_or_gold():
    draft, bundle, case = fixture()
    index = catalog(draft)
    original = select_contexts(case, bundle["chunks"], bundle, index, 100)
    case.update(query="unrelated text", draft={"required": ["made_up_answer"]}, review={"state": "APPROVED"})
    assert select_contexts(case, bundle["chunks"], bundle, index, 100) == original


def test_same_text_and_block_id_in_two_snapshots_remain_distinct():
    draft, bundle, case = fixture()
    doc = copy.deepcopy(draft["documents"][0])
    doc["raw_sha256"] = "v2"
    draft["documents"].append(doc)
    context = copy.deepcopy(bundle["contexts"]["ctx1"])
    context["raw_sha256"] = "v2"
    bundle["contexts"]["ctx-new"] = context
    hit = {**bundle["chunks"][0], "id": "c-new", "context_id": "ctx-new", "raw_sha256": "v2"}
    bundle["chunks"].append(hit)
    case["scope"].append({"source_id": "s", "raw_sha256": "v2"})
    index = catalog(draft)
    selection = select_contexts(case, [bundle["chunks"][0], hit], bundle, index, 100)
    packet = make_packet(selection, bundle, index, "deduplicated")
    assert len(packet["blocks"]) == 4 and len(packet["sources"]) == 2
    assert packet["contexts"][0]["block_refs"] != packet["contexts"][1]["block_refs"]


def test_identical_context_payload_alias_is_skipped_without_repeating_evidence():
    draft, bundle, case = fixture()
    bundle["contexts"]["alias"] = copy.deepcopy(bundle["contexts"]["ctx1"])
    hit = {**bundle["chunks"][0], "id": "alias-hit", "context_id": "alias"}
    bundle["chunks"].append(hit)
    selection = select_contexts(case, [bundle["chunks"][0], hit], bundle, catalog(draft), 100)
    assert selection.context_ids == ("ctx1",) and selection.exported_chars == 10


def test_all_contexts_too_large_yields_empty_packet_not_partial_text():
    draft, bundle, case = fixture()
    index = catalog(draft)
    selection = select_contexts(case, bundle["chunks"], bundle, index, 3)
    assert selection.context_ids == () and selection.block_keys == ()
    assert selection.blocked_ids == ("ctx1", "ctx2", "ctx3")
    packets = [make_packet(selection, bundle, index, mode) for mode in ("repeated", "deduplicated")]
    audit_pair(*packets)
    assert packets[1]["contexts"] == packets[1]["blocks"] == packets[1]["sources"] == []


@pytest.mark.parametrize("mutation", ["source", "text", "locator", "extra_block", "missing_context", "context_ref"])
def test_packet_reconstruction_audit_detects_missing_or_extra_evidence(mutation):
    draft, bundle, case = fixture()
    index = catalog(draft)
    selection = select_contexts(case, bundle["chunks"], bundle, index, 100)
    repeated = make_packet(selection, bundle, index, "repeated")
    dedup = make_packet(selection, bundle, index, "deduplicated")
    if mutation == "source":
        dedup["sources"][0]["raw_sha256"] = "other"
    elif mutation in {"text", "locator"}:
        dedup["blocks"][0][mutation] = "changed"
    elif mutation == "extra_block":
        dedup["blocks"].append(copy.deepcopy(dedup["blocks"][0]))
    elif mutation == "missing_context":
        dedup["contexts"].pop()
    else:
        dedup["contexts"][0]["block_refs"].pop()
    with pytest.raises(ValueError):
        audit_pair(repeated, dedup)


@pytest.mark.parametrize("limit", [False, 0, -1, "2048"])
def test_invalid_token_probe_limit_is_rejected(limit):
    with pytest.raises(ValueError):
        export_packet({}, limit, Characters())


def test_chat_tokenizer_is_pinned_and_does_not_truncate():
    from resolveflow.harness.token_counting import load_tokenizer
    from scripts.policy_context_packet_eval import count_text

    tokenizer = load_tokenizer()
    text = "原始政策与退款条件。" * 2000
    assert count_text(text, tokenizer) > 8192
    assert count_text(text, tokenizer) == len(tokenizer.encode(text, add_special_tokens=False).ids)
