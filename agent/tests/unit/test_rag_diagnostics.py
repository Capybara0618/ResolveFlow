"""Diagnostic scores must not pretend synthetic model queries are independently labelled."""

from dataclasses import replace

import pytest
from resolveflow.policies import PolicyHit
from scripts.evaluation import rag_experiments as diagnostics

HIT = PolicyHit("bundle", "merchant", "v1", "a" * 64, "A", "c-01", "b" * 64, "title", "text", 0.5, "dense")


def test_all_evidence_rr_requires_every_needed_rule():
    scores = diagnostics.metrics([HIT], {"A", "B"})
    assert scores["coverage_at_1"] == 0.5
    assert scores["complete_evidence_rr"] == 0
    assert scores["all_required_at_5"] is False


def test_complete_rank_penalizes_late_second_required_rule():
    hits = [HIT, replace(HIT, rule_id="C"), replace(HIT, rule_id="B")]
    scores = diagnostics.metrics(hits, {"A", "B"})
    assert scores["complete_evidence_rr"] == 1 / 3
    assert scores["all_required_at_2"] is False
    assert scores["all_required_at_5"] is True


def test_negative_retrieval_candidate_is_not_refund_eligibility():
    assert diagnostics.metrics([HIT], set()) == {"scored": True, "positive": False, "returned_candidates": True}


def test_saved_live_queries_are_traceable_unlabelled_probes():
    probes = diagnostics.live_queries()
    assert len(probes) == 8
    assert all(p["split"] == "live_query_probe" and len(p["source_sha256"]) == 64 for p in probes)
    assert all("must_rules" not in p and "expected_action" not in p for p in probes)
    report = {"results": []}
    diagnostics.report_row(report, probes[0], [], {}, "body", "dense", 0)
    summary = diagnostics.summarize(report["results"])["body/dense/live_query_probe"]
    assert summary["unscored_n"] == 1
    assert summary["coverage_at_5"] is None


def test_frozen_challenge_has_separate_gold_and_marks_same_author_bias():
    queries, gold = diagnostics.challenge()
    assert len(queries) == 24 and set(gold) == {q["id"] for q in queries}
    assert all("must_rules" not in q for q in queries)
    assert all(g["label_source"] == "same_author_policy_reading_not_independent_review" for g in gold.values())


def test_challenge_tampering_or_gold_leak_is_not_silently_accepted(monkeypatch):
    original = diagnostics.read
    def contaminated(name, directory):
        value = original(name, directory)
        if name == "queries.json":
            value[0]["must_rules"] = ["R-LOST-001"]
        return value
    monkeypatch.setattr(diagnostics, "read", contaminated)
    with pytest.raises(ValueError, match="Gold-only"):
        diagnostics.challenge()


@pytest.mark.parametrize("changes", [{"version": "old"}, {"manifest_hash": "c" * 64},
                                    {"merchant_id": "other"}, {"bundle_id": "other"}])
def test_report_detects_version_manifest_and_subject_leaks(changes):
    query = {"id": "x", "split": "diagnostic", "merchant_id": HIT.merchant_id, "bundle_id": HIT.bundle_id,
             "policy_version": HIT.version, "policy_manifest_hash": HIT.manifest_hash}
    report = {"results": []}
    diagnostics.report_row(report, query, [replace(HIT, **changes)], {}, "body", "dense", 0)
    assert report["results"][0]["filter_violations"] == 1
