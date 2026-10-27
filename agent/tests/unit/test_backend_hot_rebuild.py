import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_hot_rebuild import summarize


def evidence(loads=2):
    rows = [
        {
            "index": i,
            "node": "commerce" if i % 2 == 0 else "commerce2",
            "status": 200,
            "body_sha256": "expected",
            "elapsed_ms": 3,
        }
        for i in range(30)
    ]
    events = []
    for i in range(loads):
        events += [
            {
                "stage": stage,
                "node": "commerce",
                "call": str(i),
                "product": "P-1001",
                "at": f"2026-10-27T00:00:0{i * 2 + offset}Z",
            }
            for stage, offset in (("load_start", 0), ("load_end", 1))
        ]
    return rows, events


def test_rebuild_count_is_page_loads_and_sql_keeps_epoch_queries():
    rows, events = evidence()
    result = summarize(rows, events, 2, 36, "expected")
    assert result["rebuilds"] == 2 and result["sql"] == 36
    assert result["success"] == 30 and result["rejected"] == 0
    rows[0].update(status=503, body_sha256="refused")
    result = summarize(rows, events, 2, 35, "expected")
    assert result["success"] == 29 and result["rejected"] == 1


def test_missing_duplicate_and_miscounted_loads_fail():
    rows, events = evidence()
    with pytest.raises(ValueError, match="denominator"):
        summarize(rows[:-1], events, 2, 36, "expected")
    rows[-1]["index"] = 0
    with pytest.raises(ValueError, match="denominator"):
        summarize(rows, events, 2, 36, "expected")
    rows, events = evidence()
    with pytest.raises(ValueError, match="page counter"):
        summarize(rows, events, 3, 36, "expected")
