"""Source scope and label exclusion are preparation gates, not effect scores."""

from copy import deepcopy

import pytest
from scripts import customer_current_eval as current
from scripts.evaluation.customer_quantification_data import agent_cases, audit, rag_data
from scripts.policy_codex_review import resolve_atom


def test_source_labeled_denominators_and_failure_snapshots_match_the_intended_cases():
    report = audit()
    assert tuple(report[key] for key in (
        "conversations", "complex_conversations", "rag_queries", "rag_answerable")) == (32, 24, 40, 32)
    for case in agent_cases():
        req, _ = current.prepare_turn(case, 0, [])
        assert all(k not in str(req.context) for k in ("criteria", "artifact", "expected"))
        if case["family"] == "tool_failure":
            statuses = case["snapshot"]["http_status"]
            assert statuses.get("get_order_context", 404) != 200 or statuses.get("get_shipment_trace", 404) != 200


def test_labels_do_not_escape_source_scope_and_tables_resolve_to_header_preserving_rows():
    queries, atoms, _, index = rag_data()
    assert atoms["R01"][0][0]["table_row"] == 3 and atoms["R05"][0][0]["table_row"] == 2
    wrong = deepcopy(queries[0])
    wrong["scope"] = queries[-1]["scope"]
    with pytest.raises(ValueError, match="scope"):
        resolve_atom({"block_id": "jd-general:b0002"}, wrong, index)
