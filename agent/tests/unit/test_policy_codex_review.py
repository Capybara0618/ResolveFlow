from copy import deepcopy

import pytest
from scripts.policy_codex_review import (
    resolve_atom,
    sufficiently_covered,
    summarize,
    validate_fragments,
    validate_labels,
)
from scripts.policy_documents import digest
from scripts.policy_query_eval import coverage


def source_fixture():
    text = "header: quality; fee: seller"
    key = ("s", "raw", "s:b1")
    case = {"id": "q", "subject": "external", "scope": [{"source_id": "s", "raw_sha256": "raw"}]}
    index = {
        "sources": {key[:2]: {"subject": "external"}},
        "blocks": {key: {"text_sha256": digest(text.encode()), "subject": "external", "locator": {"line": 1}}},
        "representations": {key: [{"text": text, "table_row": 1}]},
    }
    atom = resolve_atom({"block_id": "s:b1", "table_row": 1}, case, index)
    fragment = {
        "block_id": "s:b1", "table_row": 1, "block_text_sha256": digest(text.encode()),
        "text_range": [0, len(text)], "text": text, "representation_sha256": digest(text.encode()),
        "fragment_sha256": digest(text.encode()),
    }
    chunk = {"source_id": "s", "raw_sha256": "raw", "subject": "external", "fragments": [fragment],
             "retrieval_text": text, "content_sha256": digest(text.encode())}
    return case, index, atom, chunk


@pytest.mark.parametrize("change", ["wrong_row", "wrong_source", "partial_span"])
def test_block_identity_alone_is_not_sufficient(change):
    _, _, atom, chunk = source_fixture()
    fragment = chunk["fragments"][0]
    if change == "wrong_row":
        fragment["table_row"] = 2
    elif change == "wrong_source":
        chunk["raw_sha256"] = "other-version"
    else:
        fragment["text_range"][1] -= 1
    assert coverage([chunk], atom) is False


def test_union_of_adjacent_source_spans_and_or_alternatives():
    _, _, atom, chunk = source_fixture()
    next_chunk = deepcopy(chunk)
    chunk["fragments"][0]["text_range"][1] = 10
    next_chunk["fragments"][0]["text_range"][0] = 10
    assert coverage([chunk, next_chunk], atom)
    assert sufficiently_covered([["missing", "present"], ["equivalent"]],
                                lambda ref: ref in {"present", "equivalent"})
    assert not sufficiently_covered([["missing", "present"]], lambda ref: ref == "present")
    assert sufficiently_covered([], lambda ref: True) is None


@pytest.mark.parametrize("ref", [{"block_id": "absent"}, {"block_id": "s:b1"},
                                 {"block_id": "s:b1", "table_row": 2}])
def test_unknown_block_or_table_row_is_rejected(ref):
    case, index, _, _ = source_fixture()
    with pytest.raises(ValueError):
        resolve_atom(ref, case, index)


def test_out_of_scope_version_is_rejected():
    case, index, _, _ = source_fixture()
    case["scope"][0]["raw_sha256"] = "different-version"
    with pytest.raises(ValueError, match="escaped query scope"):
        resolve_atom({"block_id": "s:b1", "table_row": 1}, case, index)


@pytest.mark.parametrize("change", ["text", "span", "hash", "body"])
def test_fragment_integrity_fails_before_scoring(change):
    _, index, _, chunk = source_fixture()
    validate_fragments([chunk], index)
    fragment = chunk["fragments"][0]
    if change == "text":
        fragment["text"] = "made up"
    elif change == "span":
        fragment["text_range"][0] = 1
    elif change == "hash":
        fragment["representation_sha256"] = "different"
    else:
        chunk["retrieval_text"] = "made up"
    with pytest.raises(ValueError):
        validate_fragments([chunk], index)


def test_review_cannot_drop_a_query_or_duplicate_it():
    case, index, _, _ = source_fixture()
    label = {"id": "q", "answerability": "ANSWERABLE", "conclusion": "c", "rationale": "r",
             "evidence_sets": [[{"block_id": "s:b1", "table_row": 1}]]}
    review = {"origin": "CODEX_REVIEW", "blind_review": False, "results": [label]}
    assert validate_labels(review, [case], index)["q"] == label
    with pytest.raises(ValueError, match="denominator"):
        validate_labels({**review, "results": []}, [case], index)
    with pytest.raises(ValueError, match="denominator"):
        validate_labels({**review, "results": [label, label]}, [case], index)


def test_partial_and_no_answer_do_not_inflate_full_answer_coverage():
    template = {"method": "dense", "k": 2, "exported_chars": 100, "returned_scope_fraction": 0.5,
                "redundant_parent_slots": 0, "all_hit_scores_zero": False}
    rows = [
        {**template, "query_id": "full", "answerability": "ANSWERABLE",
         "direct_sufficient": False, "expanded_sufficient": True},
        {**template, "query_id": "partial", "answerability": "PARTIAL",
         "direct_sufficient": True, "expanded_sufficient": True},
        {**template, "query_id": "missing", "answerability": "NOT_IN_CORPUS",
         "direct_sufficient": None, "expanded_sufficient": None},
    ]
    result = summarize(rows)[0]
    assert result["all_queries"] == 3
    assert result["answerable_denominator"] == 1
    assert result["direct_complete"] == 0 and result["expanded_complete"] == 1
    assert result["partial_denominator"] == 1 and result["partial_direct_support"] == 1
    assert result["non_answerable_count"] == 1
    assert summarize(rows)[1]["answerable_mean_exported_chars"] is None
