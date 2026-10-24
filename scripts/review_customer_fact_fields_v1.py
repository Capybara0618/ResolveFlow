"""Offline protocol migration experiment on a saved failure; never updates historical results."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from resolveflow.support.grounding import GroundingError, ground_answer
from resolveflow.support.protocol import AnswerParts, SupportInput

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "reports/chat-refund-handoff-v1/live-v2/runtime-results.json"
OUT = ROOT / "reports/customer-answer-fact-fields-v1/offline-review.json"


def review():
    digest = hashlib.sha256(RAW.read_bytes()).hexdigest()
    run = json.loads(RAW.read_text(encoding="utf-8"))["support_runs"][0]
    candidate = next(c["response_json"]["decision"] for c in reversed(run["calls"]) if c["kind"] == "model")
    request = SupportInput.model_validate(run["input_json"])
    citations = {}
    counts = {"O": 0, "P": 0}
    for call in run["calls"]:
        if call["kind"] != "tool":
            continue
        for source in call["response_json"]:
            prefix = "P" if source["source_type"] == "POLICY" else "O"
            counts[prefix] += 1
            citations[prefix + str(counts[prefix])] = source
    try:
        ground_answer(AnswerParts.model_validate(candidate), request, citations)
    except GroundingError as error:
        original_error = str(error)
    else:
        raise AssertionError("Original failed candidate must remain rejected")
    migrated = deepcopy(candidate)
    migrated["fact_rendering"] = "fields-v1"
    replacements = []
    for piece in migrated["parts"]:
        for fact in piece.get("facts", []):
            marker = "{{" + fact["field"] + "}}"
            if marker in piece["text"]:
                piece["text"] = piece["text"].replace(marker, "订单行实付款（见本段事实）")
                replacements.append({"task_id": piece["task_id"], "marker": marker})
    rendered = ground_answer(AnswerParts.model_validate(migrated), request, citations)
    assert hashlib.sha256(RAW.read_bytes()).hexdigest() == digest
    return {"diagnostic_only": True, "strict_replay": False, "new_provider_calls": 0, "business_writes": 0,
        "raw_sha256": digest, "original_error": original_error,
        "transformations": {"root_fact_rendering": "fields-v1", "macro_replacements": replacements},
        "not_a_real_model_success": True, "original_candidate": candidate,
        "experimental_candidate": migrated, "rendered_parts": [p.model_dump() for p in rendered.parts]}


if __name__ == "__main__":
    value = review()
    assert not OUT.exists(), "Never overwrite a previous experiment"
    OUT.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print({"original_still_rejected": True, "experimental_parts": len(value["rendered_parts"]),
           "new_provider_calls": 0})
