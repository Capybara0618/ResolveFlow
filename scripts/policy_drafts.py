"""Prepare source-bound section/context drafts, never executable merchant policy.

Layout and structure annotations are transparent data, not refund decision code.
All relations are candidates until independently reviewed. No model or DB access.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.policy_documents import digest, load_sources, parse_document  # noqa: E402

VERSION = "policy-structure-draft-v1"
ORIGIN = "CODEX_STRUCTURE_DRAFT"


def build_draft(document: dict, profile: dict) -> dict:
    if (
        document["source_id"] != profile.get("source_id")
        or document["raw_sha256"] != profile.get("raw_sha256")
        or not document.get("subject", "").startswith("EXTERNAL:")
    ):
        raise ValueError("profile source/snapshot differs")
    if profile.get("annotation_origin") != ORIGIN:
        raise ValueError("structure draft origin must be explicit")
    blocks = copy.deepcopy(document["blocks"])
    by_id = {b["id"]: b for b in blocks}
    if not blocks or len(by_id) != len(blocks):
        raise ValueError("empty or duplicate parsed block ids")
    for block in blocks:
        if digest(block["text"].encode()) != block["text_sha256"]:
            raise ValueError("parsed text hash differs")

    def bound(annotation):
        block = by_id.get(annotation.get("id"))
        if block is None or any(annotation.get(key) != block[key] for key in ("raw_fragment_sha256", "text_sha256")):
            raise ValueError("structure annotation hash/block differs")
        return block

    heading_levels = {b["id"]: b["heading_level"] for b in blocks if b["kind"] == "heading"}
    annotated = set()
    for annotation in profile.get("headings", []):
        block = bound(annotation)
        if block["id"] in annotated:
            raise ValueError("duplicate heading annotation")
        annotated.add(block["id"])
        level = annotation.get("level")
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 6:
            raise ValueError("heading level must be an integer from 1 to 6")
        heading_levels[block["id"]] = level

    header_tables = set()
    for annotation in profile.get("table_headers", []):
        block = bound(annotation)
        if block["kind"] != "table" or block["id"] in header_tables:
            raise ValueError("invalid or duplicate table header annotation")
        header_tables.add(block["id"])
        rows = annotation.get("rows")
        if (
            not isinstance(rows, list)
            or not rows
            or len(set(rows)) != len(rows)
            or any(
                isinstance(row, bool) or not isinstance(row, int) or not 0 <= row < len(block["rows"]) for row in rows
            )
        ):
            raise ValueError("table header row outside preserved table")
        for row in rows:
            for cell in block["rows"][row]:
                cell["original_header"] = cell["header"]
                cell["header"] = True
                cell["header_origin"] = ORIGIN

    root_id = f"{document['source_id']}:document"
    sections = [
        {
            "id": root_id,
            "heading_block_id": None,
            "level": 0,
            "parent_id": None,
            "title": document.get("title") or document["source_id"],
            "direct_block_ids": [],
            "required_section_ids": [],
        }
    ]
    stack = [sections[0]]
    warnings = set(document.get("warnings", []))
    for block in blocks:
        if block["id"] in heading_levels:
            level = heading_levels[block["id"]]
            while stack[-1]["level"] >= level:
                stack.pop()
            if level > stack[-1]["level"] + 1:
                warnings.add("HEADING_LEVEL_GAP_REQUIRES_REVIEW")
            section = {
                "id": f"{block['id']}:section",
                "heading_block_id": block["id"],
                "level": level,
                "parent_id": stack[-1]["id"],
                "title": block["text"],
                "direct_block_ids": [],
                "required_section_ids": [],
            }
            sections.append(section)
            stack.append(section)
        stack[-1]["direct_block_ids"].append(block["id"])
    by_section = {s["id"]: s for s in sections}
    by_heading = {s["heading_block_id"]: s for s in sections if s["heading_block_id"] is not None}
    by_heading["$document"] = sections[0]
    children = {s["id"]: [] for s in sections}
    for section in sections[1:]:
        children[section["parent_id"]].append(section["id"])

    def subtree(section_id):
        section = by_section[section_id]
        found = set(section["direct_block_ids"])
        for child in children[section_id]:
            found.update(subtree(child))
        return found

    for section in sections:
        ids = subtree(section["id"])
        section["subtree_block_ids"] = [b["id"] for b in blocks if b["id"] in ids]
    for relation in profile.get("relations", []):
        before, after = by_heading.get(relation.get("from")), by_heading.get(relation.get("to"))
        if before is None or after is None or relation.get("kind") != "CONTEXT_REQUIRED":
            raise ValueError("relationship must bind sections in the same source")
        if after["id"] not in before["required_section_ids"]:
            before["required_section_ids"].append(after["id"])

    def context_ids(section):
        found = set()
        visited = set()
        pending = [section["id"]]
        while pending:
            key = pending.pop()
            if key in visited:
                continue
            visited.add(key)
            current = by_section[key]
            found.update(current["subtree_block_ids"])
            pending.extend(current["required_section_ids"])
            ancestor = current["parent_id"]
            while ancestor is not None:
                parent = by_section[ancestor]
                found.update(parent["direct_block_ids"])
                pending.extend(parent["required_section_ids"])
                ancestor = parent["parent_id"]
        return [b["id"] for b in blocks if b["id"] in found]

    units = []
    for section in sections:
        if not section["direct_block_ids"]:
            continue
        retrieval_ids = section["subtree_block_ids"]
        context = context_ids(section)
        path = []
        current = section
        while current is not None:
            path.append(current["title"])
            current = by_section.get(current["parent_id"])
        retrieval_text = "\n\n".join(by_id[key]["text"] for key in retrieval_ids)
        context_text = "\n\n".join(by_id[key]["text"] for key in context)
        units.append(
            {
                "id": f"{section['id']}:draft",
                "heading_block_id": section["heading_block_id"],
                "section_path": list(reversed(path)),
                "retrieval_block_ids": retrieval_ids,
                "context_block_ids": context,
                "retrieval_text": retrieval_text,
                "context_text": context_text,
                "retrieval_sha256": digest(retrieval_text.encode()),
                "context_sha256": digest(context_text.encode()),
                "encoder_length_checked": False,
            }
        )
    unresolved = [b["id"] for b in blocks if b.get("inline_heading_candidate") and b["id"] not in heading_levels]
    return {
        "source_id": document["source_id"],
        "subject": document["subject"],
        "raw_sha256": document["raw_sha256"],
        "source_url": document.get("source_url"),
        "status": "PENDING_HUMAN_REVIEW",
        "publishable": False,
        "indexable": False,
        "independent_review_count": 0,
        "annotation_origin": ORIGIN,
        "warnings": sorted(warnings),
        "unresolved_heading_candidates": unresolved,
        "blocks": blocks,
        "sections": sections,
        "draft_units": units,
    }


def prepare(source_directory: Path, profile_directory: Path, cache: Path) -> dict:
    sources = load_sources(source_directory)
    manifest_raw = (profile_directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    profile_raw = (profile_directory / "profiles.json").read_bytes()
    if manifest.get("source_manifest_sha256") != digest(
        (source_directory / "manifest.json").read_bytes()
    ) or manifest.get("files", {}).get("profiles.json") != digest(profile_raw):
        raise ValueError("structure profile manifest differs")
    profiles = json.loads(profile_raw)
    by_source = {s["id"]: s for s in sources}
    if (
        not isinstance(profiles, list)
        or len(profiles) != len(by_source)
        or {p["source_id"] for p in profiles} != set(by_source)
    ):
        raise ValueError("structure profiles must cover every source once")
    documents = []
    for profile in profiles:
        original = by_source[profile["source_id"]]
        selected = original | {"selector": profile["body_selector"]}
        # Re-parse the frozen bytes with the explicit refined body selector. No
        # deletion by policy keywords, scenario IDs or model-generated answers.
        parsed = parse_document((cache / f"{original['id']}.html").read_bytes(), selected)
        parsed["title"] = original["title"]
        documents.append(build_draft(parsed, profile))
    return {
        "version": VERSION,
        "builder_sha256": digest(Path(__file__).read_bytes()),
        "parser_sha256": digest((ROOT / "scripts/policy_documents.py").read_bytes()),
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "profile_manifest_sha256": digest(manifest_raw),
        "documents": documents,
        "status": "PENDING_HUMAN_REVIEW",
        "publishable": False,
        "independent_review_count": 0,
        "retrieval_accuracy": None,
    }


def audit_encoder(result: dict, tokenizer, limit: int) -> dict:
    """Measure actual encoder input, not characters or the chat model's tokens.

    This gate intentionally does not truncate or split. Long candidates remain
    pending so later chunk experiments can compare on identical source content.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 3:
        raise ValueError("encoder limit must be an integer of at least 3")
    report = copy.deepcopy(result)
    count = overflow = 0
    for document in report["documents"]:
        for unit in document["draft_units"]:
            if digest(unit["retrieval_text"].encode()) != unit["retrieval_sha256"]:
                raise ValueError("draft retrieval hash differs")
            tokens = len(tokenizer(unit["retrieval_text"], truncation=False, add_special_tokens=True)["input_ids"])
            unit.update(
                encoder_length_checked=True, encoder_tokens=tokens, encoder_limit=limit, requires_split=tokens > limit
            )
            count += 1
            overflow += tokens > limit
    report["encoder_audit"] = {
        "limit": limit,
        "units": count,
        "requires_split": overflow,
        "truncation": False,
        "includes_special_tokens": True,
        "token_space": "LOCAL_POLICY_ENCODER_NOT_CHAT_LLM",
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path("evals/policy-documents-v1"))
    parser.add_argument("--profiles", type=Path, default=Path("evals/policy-structure-v1"))
    parser.add_argument("--cache", type=Path, default=Path("tmp/policy-documents-v1"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-encoder", action="store_true", help="local pinned encoder length check; no API calls")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("existing draft output must not be overwritten")
    result = prepare(args.sources, args.profiles, args.cache)
    if args.audit_encoder:
        sys.path.insert(0, str(ROOT / "agent/src"))
        from resolveflow.policies.retrieval import embedder

        local = embedder()
        encoder = local._encoder()
        result = audit_encoder(result, encoder.tokenizer, encoder.max_seq_length)
        result["encoder_audit"].update(model=local.model, revision=local.revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(
        json.dumps(
            {
                "documents": len(result["documents"]),
                "status": result["status"],
                "publishable": False,
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
