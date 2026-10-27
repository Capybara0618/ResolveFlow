"""Saved-candidate checks cannot become live calls or fabricated tool results."""

import pytest
from tests.recorded_sources import SavedSources, diagnose


def test_saved_candidate_diagnostic_preserves_text_without_updating_historical_scores():
    result = diagnose()
    assert result["passed"] is True and result["provider_requests"] == result["business_writes"] == 0
    assert {(r["id"], r["turn"]) for r in result["rows"]} == {
        ("D03", 1), ("D06", 2), ("D08", 1), ("D10", 2),
    }
    assert all(r["direct_explanations_preserved"] and not r["has_unrequested_summary"]
               for r in result["rows"])
    assert "not semantic quality" in result["limits"]


def test_saved_source_missing_records_fail_instead_of_calling_a_real_business_service():
    sources = SavedSources([])
    with pytest.raises(AssertionError, match="offline record missing"):
        sources.read("get_order_context", {})
    assert sources.calls == []
