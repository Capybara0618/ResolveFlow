"""Keep order and shipment facts explicit, scoped, versioned and unmodified."""

from copy import deepcopy

from resolveflow.support.context import render_context
from tests.unit.test_support_agent import request


def test_order_paid_and_carrier_lost_are_separate_versioned_facts():
    req = request()
    line_id = req.line_id
    observations = [
        {"source_id": "O1", "source_type": "ORDER", "version": 1,
         "data": {"line_id": line_id, "order_line": {"line_id": line_id, "status": "PAID"}}},
        {"source_id": "O2", "source_type": "SHIPMENT", "version": 3,
         "data": {"lines": [{"line_id": line_id, "status": "LOST", "carrier_conclusion": "LOST"}]}},
    ]
    original = deepcopy(observations)
    packet = render_context(req, {}, observations)
    assert packet["fact_view"] == [
        {"source_id": "O1", "source_type": "ORDER", "source_version": 1,
         "facts": {"order_line_status": "PAID"}},
        {"source_id": "O2", "source_type": "SHIPMENT", "source_version": 3,
         "facts": {"shipment_status": "LOST", "carrier_conclusion": "LOST"}},
    ]
    assert packet["observations"] == observations and observations == original


def test_fact_view_ignores_other_lines_and_failed_or_unbound_sources():
    req = request()
    observations = [
        {"source_id": "O1", "source_type": "ORDER", "version": 1,
         "data": {"line_id": req.line_id, "order_line": {"line_id": "OTHER", "status": "PAID"}}},
        {"source_id": "O2", "source_type": "SHIPMENT", "version": 3,
         "data": {"lines": [{"line_id": "OTHER", "status": "LOST", "carrier_conclusion": "LOST"}]}},
        {"source_id": "O3", "source_type": "SHIPMENT", "version": 4, "error": "SOURCE_UNAVAILABLE"},
    ]
    assert render_context(req, {}, observations)["fact_view"] == []


def test_each_read_version_stays_visible_without_deriving_business_state():
    req = request()
    observations = [
        {"source_id": "O1", "source_type": "ORDER", "version": 1,
         "data": {"line_id": req.line_id, "order_line": {"line_id": req.line_id, "status": "PAID"}}},
        {"source_id": "O2", "source_type": "ORDER", "version": 2,
         "data": {"line_id": req.line_id, "order_line": {"line_id": req.line_id, "status": "REFUNDED"}}},
        {"source_id": "O3", "source_type": "ORDER", "version": 3,
         "data": {"line_id": req.line_id, "order_line": {"line_id": req.line_id}}},
        {"source_id": "O4", "source_type": "ORDER",
         "data": {"line_id": req.line_id, "order_line": {"line_id": req.line_id, "status": "PAID"}}},
    ]
    facts = render_context(req, {}, observations)["fact_view"]
    assert [row["source_version"] for row in facts] == [1, 2]
    assert [row["facts"]["order_line_status"] for row in facts] == ["PAID", "REFUNDED"]
