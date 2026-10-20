"""Query enrichment uses only this line's observed shipment facts, never policy text or claims."""

from resolveflow.support.query import grounded_query


def shipment(status, *, line="line-A", version=3, conclusion=None):
    return {
        "source_type": "SHIPMENT",
        "source_id": "O1",
        "version": version,
        "data": {
            "version": version,
            "lines": [
                {
                    "line_id": line,
                    "status": status,
                    "source_version": version,
                    "carrier_conclusion": conclusion or status,
                }
            ],
        },
    }


def test_matching_observed_fact_preserves_original_query_and_records_source():
    plan = grounded_query("物流丢失，想了解退款条件", [shipment("LOST")], "line-A")
    assert plan.original == "物流丢失，想了解退款条件"
    assert plan.query == "物流状态 LOST；物流丢失，想了解退款条件"
    assert plan.source_ids == ("O1",) and plan.reason == "shipment_fact"


def test_claims_policy_refund_unknown_and_other_line_do_not_supply_shipment_state():
    query = "没有收到，是不是丢了？"
    for sources in [
        [],
        [{"source_type": "POLICY", "data": {"status": "LOST"}}],
        [{"source_type": "ORDER", "data": {"status": "UNKNOWN"}}],
        [{"source_type": "CONVERSATION", "data": {"status": "LOST"}}],
        [shipment("LOST", line="other")],
        [shipment("invented")],
    ]:
        assert grounded_query(query, sources, "line-A").query == query


def test_newer_status_replaces_old_but_failure_or_same_version_conflict_is_not_guessed():
    query = "怎么处理？"
    plan = grounded_query(query, [shipment("LOST"), shipment("DELIVERED", version=4)], "line-A")
    assert plan.query == "物流状态 DELIVERED；怎么处理？"
    for observations in [
        [shipment("LOST"), shipment("DELIVERED")],
        [shipment("LOST"), {"error": "SOURCE_UNAVAILABLE"}],
    ]:
        assert grounded_query(query, observations, "line-A").query == query


def test_uncertainty_is_kept_and_enrichment_never_truncates_original():
    plan = grounded_query("能否退款？", [shipment("UNKNOWN")], "line-A")
    assert plan.query == "物流状态 UNKNOWN；能否退款？" and "LOST" not in plan.query
    long_query = "问" * 1000
    assert grounded_query(long_query, [shipment("LOST")], "line-A").query == long_query
