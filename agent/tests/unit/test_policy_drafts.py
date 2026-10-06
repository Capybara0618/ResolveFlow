"""Source-bound structure drafts keep conditions together without business answers."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest
from scripts.policy_drafts import audit_encoder, build_draft, prepare


def block(index, text, **extra):
    return {
        "id": f"doc:b{index:04d}",
        "kind": "paragraph",
        "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "raw_fragment_sha256": hashlib.sha256(f"<p>{text}</p>".encode()).hexdigest(),
        "inline_heading_candidate": False,
        "locator": {"start_char": index, "end_char": index + 1},
        **extra,
    }


def inputs():
    blocks = [
        block(1, "Policy"),
        block(2, "Conditions"),
        block(3, "Eligible under conditions"),
        block(4, "Exceptions"),
        block(5, "Customized items excluded"),
    ]
    document = {
        "source_id": "doc",
        "subject": "EXTERNAL:TEST",
        "raw_sha256": "a" * 64,
        "status": "PENDING_REVIEW",
        "blocks": blocks,
        "warnings": [],
    }
    profile = {
        "source_id": "doc",
        "raw_sha256": "a" * 64,
        "annotation_origin": "CODEX_STRUCTURE_DRAFT",
        "headings": [ref(blocks[0], level=1), ref(blocks[1], level=2), ref(blocks[3], level=2)],
        "relations": [{"from": blocks[1]["id"], "to": blocks[3]["id"], "kind": "CONTEXT_REQUIRED"}],
        "table_headers": [],
    }
    return document, profile


def ref(value, **extra):
    return {key: value[key] for key in ("id", "raw_fragment_sha256", "text_sha256")} | extra


def test_sibling_exception_is_in_context_and_every_block_is_assigned_once():
    document, profile = inputs()
    result = build_draft(document, profile)
    unit = next(u for u in result["draft_units"] if u["heading_block_id"] == "doc:b0002")
    assert "Customized items excluded" in unit["context_text"]
    assert "Customized items excluded" not in unit["retrieval_text"]
    assert "Policy" in unit["context_text"]
    assigned = [key for section in result["sections"] for key in section["direct_block_ids"]]
    assert sorted(assigned) == sorted(b["id"] for b in document["blocks"])
    assert result["publishable"] is False and result["independent_review_count"] == 0


def test_whole_parent_subtree_contains_child_exception():
    document, profile = inputs()
    result = build_draft(document, profile)
    parent = next(u for u in result["draft_units"] if u["heading_block_id"] == "doc:b0001")
    assert "Customized items excluded" in parent["retrieval_text"]
    assert parent["encoder_length_checked"] is False


def test_relationship_cycles_terminate_and_context_is_not_duplicated():
    document, profile = inputs()
    profile["relations"].append({"from": "doc:b0004", "to": "doc:b0002", "kind": "CONTEXT_REQUIRED"})
    result = build_draft(document, profile)
    for unit in result["draft_units"]:
        assert len(unit["context_block_ids"]) == len(set(unit["context_block_ids"]))


@pytest.mark.parametrize("field", ["raw_fragment_sha256", "text_sha256"])
def test_annotation_drift_is_refused(field):
    document, profile = inputs()
    profile["headings"][0][field] = "0" * 64
    with pytest.raises(ValueError, match="annotation"):
        build_draft(document, profile)


def test_tampered_parsed_text_is_refused():
    document, profile = inputs()
    document["blocks"][2]["text"] = "Changed eligibility"
    with pytest.raises(ValueError, match="text hash"):
        build_draft(document, profile)


@pytest.mark.parametrize("changes", [{"source_id": "another"}, {"raw_sha256": "0" * 64}])
def test_profile_cannot_be_reused_for_other_source_or_snapshot(changes):
    document, profile = inputs()
    with pytest.raises(ValueError, match="source"):
        build_draft(document, profile | changes)


def test_cross_source_relationship_is_refused():
    document, profile = inputs()
    profile["relations"][0]["to"] = "other:b0004"
    with pytest.raises(ValueError, match="relationship"):
        build_draft(document, profile)


def test_unconfirmed_bold_text_is_not_automatically_a_heading():
    document, profile = inputs()
    document["blocks"][2]["inline_heading_candidate"] = True
    result = build_draft(document, profile)
    assert "doc:b0003" in result["unresolved_heading_candidates"]
    assert not any(s["heading_block_id"] == "doc:b0003" for s in result["sections"])


def test_table_header_draft_keeps_original_cells_and_does_not_mutate_input():
    document, profile = inputs()
    table = block(
        6,
        "Reason | Cost",
        kind="table",
        rows=[
            [
                {"text": "Reason", "header": False, "rowspan": 1, "colspan": 1},
                {"text": "Cost", "header": False, "rowspan": 1, "colspan": 1},
            ]
        ],
    )
    document["blocks"].append(table)
    profile["table_headers"] = [ref(table, rows=[0])]
    before = copy.deepcopy(document)
    result = build_draft(document, profile)
    cell = result["blocks"][-1]["rows"][0][0]
    assert cell["header"] is True and cell["original_header"] is False
    assert cell["header_origin"] == "CODEX_STRUCTURE_DRAFT"
    assert document == before


def test_invalid_header_row_is_refused():
    document, profile = inputs()
    profile["table_headers"] = [ref(document["blocks"][0], rows=[0])]
    with pytest.raises(ValueError, match="table"):
        build_draft(document, profile)


@pytest.mark.parametrize("level", [True, 0, 7, "2"])
def test_invalid_heading_levels_are_refused(level):
    document, profile = inputs()
    profile["headings"][0]["level"] = level
    with pytest.raises(ValueError, match="level"):
        build_draft(document, profile)


def test_duplicate_blocks_or_annotations_are_refused():
    document, profile = inputs()
    document["blocks"].append(document["blocks"][0])
    with pytest.raises(ValueError, match="duplicate"):
        build_draft(document, profile)
    document, profile = inputs()
    profile["headings"].append(profile["headings"][0])
    with pytest.raises(ValueError, match="duplicate"):
        build_draft(document, profile)


def test_native_html_headings_can_be_overridden_only_by_bound_annotation():
    document, profile = inputs()
    document["blocks"][0].update(kind="heading", heading_level=4)
    result = build_draft(document, profile)
    assert next(s for s in result["sections"] if s["heading_block_id"] == "doc:b0001")["level"] == 1


def test_encoder_audit_counts_special_tokens_and_refuses_silent_truncation():
    document, profile = inputs()
    draft = build_draft(document, profile)
    calls = []

    def tokenizer(text, **kwargs):
        calls.append(kwargs)
        return {"input_ids": [0] + list(text) + [1]}

    result = audit_encoder({"documents": [draft]}, tokenizer, 10)
    assert all(c == {"truncation": False, "add_special_tokens": True} for c in calls)
    assert result["encoder_audit"]["requires_split"] > 0
    assert result["documents"][0]["publishable"] is False
    assert all(u["encoder_length_checked"] for u in result["documents"][0]["draft_units"])
    assert all(u["encoder_length_checked"] is False for u in draft["draft_units"])


def test_encoder_audit_does_not_accept_changed_retrieval_text():
    document, profile = inputs()
    draft = build_draft(document, profile)
    draft["draft_units"][0]["retrieval_text"] = "changed"
    with pytest.raises(ValueError, match="retrieval hash"):
        audit_encoder({"documents": [draft]}, None, 512)


@pytest.mark.parametrize("limit", [True, 0, 2, "512"])
def test_encoder_audit_limit_is_explicit(limit):
    with pytest.raises(ValueError, match="limit"):
        audit_encoder({}, None, limit)


def preparation_files(tmp_path):
    sources, profiles, cache = [tmp_path / name for name in ("sources", "profiles", "cache")]
    for directory in (sources, profiles, cache):
        directory.mkdir()
    raw = b'<article id="policy"><h1>Policy</h1><p>Conditions</p></article>'
    source = {
        "id": "doc",
        "title": "Policy",
        "subject": "EXTERNAL:TEST",
        "encoding": "utf-8",
        "url": "https://example.org/policy",
        "role": "EXTERNAL_REFERENCE",
        "adopted_by_project_merchant": False,
        "selector": {"tag": "article", "id": "policy"},
        "expected_sha256": hashlib.sha256(raw).hexdigest(),
    }
    (cache / "doc.html").write_bytes(raw)
    source_data = json.dumps([source]).encode()
    (sources / "sources.json").write_bytes(source_data)
    source_manifest = json.dumps(
        {"documents": 1, "source_families": 1, "files": {"sources.json": hashlib.sha256(source_data).hexdigest()}}
    ).encode()
    (sources / "manifest.json").write_bytes(source_manifest)
    profile_data = json.dumps(
        [
            {
                "source_id": "doc",
                "raw_sha256": source["expected_sha256"],
                "annotation_origin": "CODEX_STRUCTURE_DRAFT",
                "body_selector": source["selector"],
                "headings": [],
                "table_headers": [],
                "relations": [],
            }
        ]
    ).encode()
    (profiles / "profiles.json").write_bytes(profile_data)
    (profiles / "manifest.json").write_text(
        json.dumps(
            {
                "source_manifest_sha256": hashlib.sha256(source_manifest).hexdigest(),
                "files": {"profiles.json": hashlib.sha256(profile_data).hexdigest()},
            }
        ),
        encoding="utf-8",
    )
    return sources, profiles, cache


def test_preparation_binds_two_manifests_and_does_not_publish(tmp_path):
    sources, profiles, cache = preparation_files(tmp_path)
    result = prepare(sources, profiles, cache)
    assert result["publishable"] is False
    assert result["documents"][0]["subject"] == "EXTERNAL:TEST"
    (profiles / "profiles.json").write_bytes(b"[]")
    with pytest.raises(ValueError, match="manifest"):
        prepare(sources, profiles, cache)


def test_preparation_requires_original_frozen_bytes(tmp_path):
    sources, profiles, cache = preparation_files(tmp_path)
    (cache / "doc.html").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash"):
        prepare(sources, profiles, cache)
