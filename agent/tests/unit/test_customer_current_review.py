"""Detect final rendering replacement that surviving-attempt timing alone misses."""

from scripts.customer_current_review import stable_projection


def delta(part, text, elapsed):
    return {"kind": "answer.delta", "payload": {"part_id": part, "text": text}, "elapsed_ms": elapsed}


def test_navigation_replacement_is_not_called_a_retained_stream_body():
    row = {"events": [delta("part-0", "This direct answer was removed.", 100)], "elapsed_ms": 200,
           "result": {"answer": {"text": "Program navigation at final commit."}}}
    result = stable_projection(row)
    assert result["published_body_ms"] == 200
    assert result["first_stable_observation"] == "FINAL_RESULT_RETURN"
    assert result["replaced_parts"] == ["part-0"]


def test_multi_part_commit_can_keep_one_stream_part_and_replace_another():
    row = {"events": [delta("part-0", "Removed navigation", 100), delta("part-1", "Actual explanation", 150)],
           "elapsed_ms": 200, "result": {"answer": {"text": "Actual explanation\n\nProgram navigation"}}}
    result = stable_projection(row)
    assert result["published_body_ms"] == 150
    assert result["stream_identity_parts"] == ["part-1"]
    assert result["replaced_parts"] == ["part-0"]


def test_reset_or_failed_candidate_is_not_counted_as_published_body():
    events = [delta("part-0", "Old", 100), {"kind": "answer.reset"}, delta("part-0", "New", 150)]
    row = {"events": events, "elapsed_ms": 200, "result": {"answer": {"text": "Old\nNew"}}}
    assert stable_projection(row)["published_body_ms"] == 150
    row["result"]["answer"] = None
    assert stable_projection(row)["published_body_ms"] is None
