"""Do not turn independent wording or model-generated queries into fabricated Gold."""

import json
from copy import deepcopy

import pytest
from scripts.evaluation import rag_probes as probes


def test_external_questions_are_exact_and_separate_from_synthetic_gold():
    queries, sources = probes.external_queries()
    assert len(sources) == 11 and len(queries) == 33
    assert len({q["source_id"] for q in queries}) == 11
    assert all("must_rules" not in q and "expected_action" not in q for q in queries)
    assert all(s["kind"] == "OFFICIAL_FAQ" for s in sources)


@pytest.mark.parametrize("changes", [
    {"query": "modified customer wording"}, {"merchant_id": "wrong merchant"},
    {"must_rules": ["R-LOST-001"]}, {"source_id": "invented source"},
])
def test_external_input_contamination_is_rejected(monkeypatch, changes):
    original = probes.read

    def contaminated(name, directory):
        value = deepcopy(original(name, directory))
        if name == "queries.json":
            value[0].update(changes)
        return value

    monkeypatch.setattr(probes, "read", contaminated)
    with pytest.raises(ValueError):
        probes.external_queries()


def report_with_search():
    cases = probes.read("agent/cases.json", probes.ALIGNED_DATA)
    hashes = {p.relative_to(probes.ROOT).as_posix(): probes.digest(p)
              for area in ("harness", "policies", "tools")
              for p in (probes.ROOT / "agent/src/resolveflow" / area).glob("*.py")}
    return {"mode": "live", "synthetic": True, "state": "FINISHED", "code_hashes": hashes,
            "manifest_hash": probes.digest(probes.ALIGNED_DATA / "manifest.json"),
            "results": [{"id": cases[0]["id"], "requests": [
                {"decision": {"kind": "SEARCH_POLICY", "query": "退款材料不足", "arguments": {"top_k": 2}}}]}]}


def test_live_probe_retains_exact_query_scope_turn_hash_and_top_k(tmp_path):
    path = tmp_path / "live.json"
    path.write_text(json.dumps(report_with_search()), encoding="utf-8")
    queries = probes.current_live_queries(path)
    assert len(queries) == 1 and queries[0]["query"] == "退款材料不足"
    assert queries[0]["original_top_k"] == 2 and queries[0]["turn"] == 1
    assert queries[0]["source_sha256"] == probes.digest(path)
    assert "must_rules" not in queries[0]


@pytest.mark.parametrize("changes", [
    {"mode": "mock"}, {"state": "RUNNING"}, {"manifest_hash": "a" * 64},
    {"code_hashes": {}}, {"results": []},
    {"results": [{"id": "A01A", "requests": []}]},
])
def test_mock_unfinished_wrong_version_and_zero_queries_fail(tmp_path, changes):
    report = report_with_search()
    report.update(changes)
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        probes.current_live_queries(path)


def test_unlabelled_candidates_have_no_accuracy_even_if_every_query_returns_hits():
    rows = [{"split": "external", "path": "dense", "hits": [{"rule_id": "R-LOST-001"}],
             "filter_violations": 0, "returned_chars_at_2": 100}]
    summary = probes.probe_summary(rows)["external/dense"]
    assert summary["n"] == summary["unscored_n"] == 1
    assert summary["accuracy"] is None


def test_external_dropped_scope_cannot_shrink_the_frozen_denominator(monkeypatch):
    original = probes.read

    def missing(name, directory):
        value = original(name, directory)
        return value[:-1] if name == "queries.json" else value

    monkeypatch.setattr(probes, "read", missing)
    with pytest.raises(ValueError, match="denominator"):
        probes.external_queries()


def test_external_repeated_question_cannot_be_counted_as_independent_source(monkeypatch):
    original = probes.read
    sources = original("sources.json", probes.EXTERNAL)
    repeated = {**sources[0], "id": sources[1]["id"]}

    def duplicate(name, directory):
        value = deepcopy(original(name, directory))
        if name == "sources.json":
            value[1] = repeated
        if name == "queries.json":
            for q in value:
                if q["source_id"] == repeated["id"]:
                    q["query"] = repeated["question"]
        return value

    monkeypatch.setattr(probes, "read", duplicate)
    with pytest.raises(ValueError, match="independent"):
        probes.external_queries()
