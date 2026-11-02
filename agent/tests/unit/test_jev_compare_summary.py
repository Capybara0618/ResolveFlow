import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from jev_compare_summary import summarize


def prepared(tmp_path):
    answer = {"text": "查询暂时不可用。"}
    answer_hash = hashlib.sha256(json.dumps(answer, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
    rows = [{"id": str(i), "baseline": {"answer": answer},
             "jev_check": {"status": "SKIPPED", "reason": "BUDGET_STEP_TOKENS"},
             "repairs": {"jev-repair": {"status": "FAILED", "answer": None}}} for i in range(19)]
    results = {"rows": rows, "provider_attempts": 0, "conservative_reserved_usd": 0}
    (tmp_path / "results.json").write_text(json.dumps(results), encoding="utf-8")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    review = {"results_sha256": hashlib.sha256((tmp_path / "results.json").read_bytes()).hexdigest(),
              "reviewer": "test-only", "rows": [
                  {"id": str(i), "answers_sha256": {k: answer_hash for k in ("baseline", "jev-gated", "self-check")},
                   "scores": {k: {"grounded": True, "task_complete": i != 0}
                              for k in ("baseline", "jev-gated", "self-check")}, "notes": "explicit test labels"}
                  for i in range(19)]}
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review), encoding="utf-8")
    return path, review


def test_failed_candidate_keeps_baseline_and_skips_do_not_become_successes(tmp_path):
    path, _ = prepared(tmp_path)
    result = summarize(tmp_path, path)
    assert result["arms"]["jev-gated"]["changed_text"] == 0
    assert result["arms"]["jev-gated"]["task_complete"] == 18
    assert result["jev_coverage"]["completed"] == 0 and result["jev_coverage"]["skipped"] == 19


@pytest.mark.parametrize("change", ["remove-label", "alter-answer-hash", "change-result"])
def test_summary_rejects_changed_denominators_and_unreviewed_answers(tmp_path, change):
    path, review = prepared(tmp_path)
    if change == "remove-label":
        review["rows"].pop()
    elif change == "alter-answer-hash":
        review["rows"][0]["answers_sha256"]["baseline"] = "not-reviewed"
    else:
        (tmp_path / "results.json").write_text("{}", encoding="utf-8")
    path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError):
        summarize(tmp_path, path)
