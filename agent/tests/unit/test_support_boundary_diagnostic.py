"""Saved-candidate checks cannot become live calls or fabricated tool results."""

import pytest

from tests.recorded_sources import SavedSources


def test_saved_source_missing_records_fail_instead_of_calling_a_real_business_service():
    sources = SavedSources([])
    with pytest.raises(AssertionError, match="offline record missing"):
        sources.read("get_order_context", {})
    assert sources.calls == []
