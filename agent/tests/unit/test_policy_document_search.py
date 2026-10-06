import pytest
from scripts.policy_document_search import query_scope, search


def corpus():
    return {
        "documents": [
            {"source_id": "a", "subject": "EXTERNAL:A", "raw_sha256": "v1"},
            {"source_id": "b", "subject": "EXTERNAL:A", "raw_sha256": "v2"},
            {"source_id": "c", "subject": "EXTERNAL:C", "raw_sha256": "v3"},
        ]
    }


def test_explicit_same_subject_sources_keep_exact_versions():
    result = query_scope(["a", "b"], corpus())
    assert result == {
        "subject": "EXTERNAL:A",
        "scope": [{"source_id": "a", "raw_sha256": "v1"}, {"source_id": "b", "raw_sha256": "v2"}],
    }


@pytest.mark.parametrize("scope", [[], ["a", "a"], ["unknown"], ["a", "c"]])
def test_bad_or_cross_subject_scope_is_refused(scope):
    with pytest.raises(ValueError):
        query_scope(scope, corpus())


@pytest.mark.parametrize(
    "query,strategy,k", [("", "dense", 5), ("q", "dense", 6), ("q", "dense", True), ("q", "unknown", 5)]
)
def test_invalid_queries_fail_without_encoder_or_network(query, strategy, k):
    with pytest.raises(ValueError):
        search(query, ["a"], strategy, k)
