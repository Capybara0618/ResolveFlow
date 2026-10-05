"""Create an explicit v2 calibration fork; never overwrite the frozen v1 assets."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

from scripts.evaluation.dataset import ALIGNED_DATA, DATA, digest, read


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def build(directory: Path = ALIGNED_DATA):
    if directory.exists():
        raise ValueError("Calibration dataset is immutable; select a new version directory")
    cases, gold = read("agent/cases.json"), read("gold/agent.json")
    parent = read("manifest.json")
    for name in parent["files"]:
        if name not in {"agent/cases.json", "gold/agent.json"}:
            destination = directory / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(DATA / name, destination)
    for case in cases:
        case["case_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "resolveflow-eval-case:" + case["id"]))
        case["input_revision"] = len(case["backend"]["evidence"]["materials"])
        materials, questions = [], []
        for index, old in enumerate(case["backend"]["evidence"]["materials"]):
            identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, case["case_id"] + ":material:" + str(index)))
            material = {
                "evidence_id": identifier,
                "source_type": "REVIEWER_VERIFICATION"
                if old["source_type"] == "REVIEWER_VERIFICATION"
                else "CUSTOMER_STATEMENT",
                "source_ref": f"case:{case['case_id']}:evidence:{identifier}",
                "source_version": str(index + 1),
                "input_revision": index + 1,
                "content_hash": hashlib.sha256(old["content"].encode()).hexdigest(),
                "content": old["content"],
            }
            if material["source_type"] == "REVIEWER_VERIFICATION":
                material.update(
                    verification_result=old["verification_result"], reviewed_evidence_id=materials[0]["evidence_id"]
                )
            if old.get("question_id"):
                material["question_id"] = old["question_id"]
                questions.append(
                    {
                        "question_id": old["question_id"],
                        "input_revision": max(1, index),
                        "questions": [{"field": "receiver", "prompt": "请核对实际收货人。"}],
                    }
                )
            materials.append(material)
        case["review_context"] = {"materials": materials, "questions": questions}
        case["backend"]["evidence"] = {
            "case_id": case["case_id"],
            "input_revision": case["input_revision"],
            "evidence": [
                {
                    "observation_id": m["evidence_id"],
                    **{k: m[k] for k in ("source_ref", "source_version", "content_hash")},
                }
                for m in materials
            ],
        }
        answer = gold[case["id"]]
        answer["support_requirements"] = []
        if "REFUND" not in answer["allowed_actions"]:
            continue
        answer["support_requirements"].append(
            {
                "id": "paid_free_line",
                "any_of": [
                    {
                        "tool": "get_order_context",
                        "fields": {
                            **case["scope"],
                            "order_status": "PAID",
                            "line_refund_state": "FREE",
                            "refunded_amount": 0,
                            "reserved_refund_amount": 0,
                            "currency": "CNY",
                            "line_paid_amount": case["backend"]["order"]["line_paid_amount"],
                            "paid_at": case["backend"]["order"]["paid_at"],
                            "payment_version": case["backend"]["order"]["payment_version"],
                        },
                    }
                ],
            }
        )
        if case["family"] == "unshipped":
            answer["support_requirements"].append(
                {
                    "id": "not_shipped",
                    "any_of": [
                        {
                            "tool": "get_order_context",
                            "fields": {"fulfillment_status": "NOT_SHIPPED", "fulfillment_version": 1},
                        }
                    ],
                }
            )
        else:
            answer["support_requirements"].append(
                {"id": "human_confirmed", "any_of": [{"tool": "get_case_evidence", "verification": "CONFIRMED"}]}
            )
            if case["family"] == "quality":
                answer["must_tools"].remove("get_shipment_trace")
                answer["support_requirements"].append(
                    {
                        "id": "delivered",
                        "any_of": [
                            {"tool": "get_order_context", "fields": {"fulfillment_status": "DELIVERED"}},
                            {"tool": "get_shipment_trace", "fields": {"status": "DELIVERED"}},
                        ],
                    }
                )
            else:
                answer["support_requirements"].append(
                    {
                        "id": "carrier_lost",
                        "any_of": [
                            {"tool": "get_shipment_trace", "fields": {"status": "LOST", "carrier_conclusion": "LOST"}}
                        ],
                    }
                )
    write(directory / "agent/cases.json", cases)
    write(directory / "gold/agent.json", gold)
    files = {name: digest(directory / name) for name in parent["files"]}
    write(
        directory / "manifest.json",
        {
            **parent,
            "version": "resolveflow-evaluation-aligned-v2",
            "files": files,
            "parent_manifest_sha256": digest(DATA / "manifest.json"),
            "input_profile": "Java ReviewerRunInput + EvidenceListResponse; synthetic loopback sources",
            "changes": [
                "inject revision-bound review_context at dispatch",
                "get_case_evidence returns references, never raw material text",
                "quality delivery may be established by order projection or carrier trace",
                "positive Gold additionally checks cited field values and anchored human verification",
            ],
            "unchanged": ("32 case ids, pairs, splits, allowed/forbidden actions, "
                          "policy texts, RAG queries and rule Gold"),
        },
    )


def freeze_replay(directory: Path = ALIGNED_DATA):
    destination = directory / "replay/manifest.json"
    if destination.exists():
        raise ValueError("Replay packs are already frozen")
    packs = sorted((directory / "replay/golden").glob("*/pack.json"))
    if len(packs) != 5:
        raise ValueError("Expected five newly exported packs before finalizing")
    files = {}
    for pack in packs:
        for path in (pack, pack.with_name("files.json")):
            files[path.relative_to(directory).as_posix()] = digest(path)
    write(destination, {"dataset_manifest_sha256": digest(directory / "manifest.json"), "files": files})


if __name__ == "__main__":
    build()
