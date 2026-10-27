import io
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_d5_faults import plan as faults_plan
from evaluation.backend_d5_rebuild import plan, rebuild_peak
from evaluation.backend_d5_rebuild_support import redis, resp


def event(stage, node, call, second):
    return {
        "stage": stage,
        "node": node,
        "call": call,
        "product": "hot",
        "at": f"2026-10-27T00:00:{second:02d}.000000Z",
    }


def test_120_rebuild_rounds_keep_rotation_load_and_real_ttl_plan():
    rows = plan()
    assert len(rows) == len({r["id"] for r in rows}) == 120
    assert Counter((r["scenario"], r["condition"]) for r in rows) == {
        (scenario, condition): 10 for scenario in ("R01", "R02", "R03", "R04", "R05", "R06") for condition in ("B", "C")
    }
    assert [r["condition"] for r in rows[:4]] == ["B", "C", "C", "B"]
    assert sum(r["concurrency"] == 10 for r in rows) == sum(r["concurrency"] == 30 for r in rows) == 60
    assert sum(r["ttl"] for r in rows) == 10
    assert Counter(r["redis_fault"] for r in rows if r["scenario"] == "R06") == {"drop": 10, "stall": 10}


def test_15_fault_windows_have_original_full_duration_and_denominators():
    rows = faults_plan()
    assert len(rows) == 15 and Counter(r["profile"] for r in rows) == {"P1": 12, "P3": 3}
    assert all(r["warmup"] == 10 and r["seconds"] == 30 and r["concurrency"] == 32 for r in rows)


def test_peak_uses_actual_overlap_instead_of_sum_of_node_peaks():
    first = [
        event("load_start", "a", "1", 1),
        event("load_end", "a", "1", 2),
        event("load_start", "b", "2", 3),
        event("load_end", "b", "2", 4),
    ]
    assert rebuild_peak(first, "hot") == 1
    overlapping = [
        event("load_start", "a", "1", 1),
        event("load_start", "b", "2", 2),
        event("load_end", "a", "1", 3),
        event("load_end", "b", "2", 4),
    ]
    assert rebuild_peak(overlapping, "hot") == 2


def test_missing_load_end_needs_actual_terminal_process_event():
    rows = [event("load_start", "a", "1", 1)]
    with pytest.raises(ValueError, match="without actual terminal"):
        rebuild_peak(rows, "hot")
    timestamp = 1793059202 * 1_000_000_000  # 2026-10-27T00:00:02Z
    assert rebuild_peak(rows, "hot", {"node": "a", "at_ns": timestamp}) == 1


def test_read_only_redis_observer_rejects_mutations_before_opening_network():
    for command in ("DEL", "FLUSHALL", "EVAL", "SET"):
        with pytest.raises(ValueError, match="read-only"):
            redis(None, command, "owned-key")


def test_resp_parser_preserves_missing_key_and_rejects_truncated_evidence():
    assert resp(io.BytesIO(b"*3\r\n$3\r\nkey\r\n:42\r\n$-1\r\n")) == ["key", 42, None]
    with pytest.raises(ValueError, match="truncated"):
        resp(io.BytesIO(b"$9\r\nshort\r\n"))
    with pytest.raises(ValueError, match="truncated"):
        resp(io.BytesIO(b":42"))


def assessment_fixture():
    from evaluation.backend_d5_http import digest

    body = {
        "items": [{"product_id": "hot", "version": 1}],
        "summary": {"count": 1, "average": 3.0, "stars": [0, 0, 1, 0, 0]},
    }
    row = {"status": 200, "body": body, "body_sha256": digest(body)}
    events = [event("load_start", "commerce", "a", 1), event("load_end", "commerce", "a", 2), {"stage": "sql_execute"}]
    result = {
        "round": {"scenario": "R01", "condition": "B", "concurrency": 2, "ttl": False},
        "products": [{"product": "hot"}],
        "facts": {"recovery_seconds": 0.01},
        "reference": row,
        "initial": [{**row, "node": "commerce", "index": 0}, {**row, "node": "commerce2", "index": 1}],
        "followup": [row] * 10,
        "after": {"commerce": {"sql_inflight": 0, "meters": {}}},
        "before": {"commerce": {"meters": {}}},
        "rebuild_peak": 1,
        "rebuild_loads": 1,
        "sql_execute_events": 1,
        "independent": [
            {"product": product, "status": 200, "body": {"items": [{"product_id": product}]}}
            for product in ("other-a", "other-b")
        ],
    }
    return result, events


def test_semantic_assessor_rejects_hidden_http_error_and_fake_fault_trigger():
    from evaluation.backend_d5_rebuild_audit import assess

    result, events = assessment_fixture()
    assert assess(result, events)["passed"]
    result["initial"][0]["status"] = 500
    assert not assess(result, events)["passed"]
    result, events = assessment_fixture()
    result["round"].update(scenario="R06", redis_fault="stall")
    result["facts"].update(redis_injected={"mode": "stall"}, redis_restored={"mode": "normal"})
    assert "Redis fault not observed by application" in assess(result, events)["reasons"]


def test_normal_mutex_requires_one_load_not_just_nonoverlapping_loads():
    from evaluation.backend_d5_rebuild_audit import assess

    result, events = assessment_fixture()
    result["round"]["condition"] = "C"
    events += [event("load_start", "commerce2", "b", 3), event("load_end", "commerce2", "b", 4)]
    result["rebuild_loads"] = 2
    assert "normal lease duplicated page load" in assess(result, events)["reasons"]


def test_request_journal_rejects_unresolved_or_forged_response(tmp_path):
    import json

    from evaluation.backend_d5_rebuild_audit import journal_audit

    path = tmp_path / "journal.jsonl"
    start = {"stage": "start", "request_id": "a", "started_ns": 1}
    path.write_text(json.dumps(start) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unresolved"):
        journal_audit(path)
    end = {
        "stage": "end",
        "request_id": "a",
        "started_ns": 1,
        "elapsed_ms": 3,
        "body": {"answer": 42},
        "body_sha256": "forged",
    }
    path.write_text(json.dumps(start) + "\n" + json.dumps(end) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="body hash"):
        journal_audit(path)
