from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.agent_eval import persist  # noqa: E402
from scripts.evaluation.review import make_review, score_review  # noqa: E402


def inputs(tmp_path):
    source = tmp_path / "source.json"
    report = {
        "mode": "live",
        "manifest_hash": "frozen",
        "results": [
            {"id": "A", "joint_correct": True, "decision": {"kind": "ASK_CUSTOMER"}},
            {"id": "B", "joint_correct": False, "decision": {"kind": "PROPOSE"}},
        ],
    }
    persist(source, report)
    return report, source, make_review(report, source)


def test_pending_review_never_claims_success(tmp_path):
    report, source, review = inputs(tmp_path)
    result = score_review(report, source, review)
    assert result["status"] == "PENDING" and result["pending_n"] == 2 and result["reviewed_n"] == 0


def test_question_semantics_cannot_be_omitted_and_automatic_failure_remains(tmp_path):
    report, source, review = inputs(tmp_path)
    review.update(reviewer="declared reviewer", reviewed_at="2026-10-05")
    for row in review["results"]:
        row.update(decision_supported=True, no_unsupported_claims=True)
    first = score_review(report, source, review)
    assert first["reviewed_n"] == 1 and first["combined_pass"] == 0
    review["results"][0]["question_relevant"] = True
    second = score_review(report, source, review)
    assert second["status"] == "COMPLETE" and second["semantic_pass"] == 2 and second["combined_pass"] == 1


@pytest.mark.parametrize("change", ["hash", "ids", "coerce", "reviewer"])
def test_unbound_incomplete_or_fake_typed_review_is_refused(tmp_path, change):
    report, source, original = inputs(tmp_path)
    review = deepcopy(original)
    if change == "hash":
        review["report_sha256"] = "changed"
    elif change == "ids":
        review["results"].pop()
    elif change == "coerce":
        review["results"][0]["decision_supported"] = "false"
    else:
        review["results"][1].update(decision_supported=True, no_unsupported_claims=True)
    with pytest.raises(ValueError):
        score_review(report, source, review)
