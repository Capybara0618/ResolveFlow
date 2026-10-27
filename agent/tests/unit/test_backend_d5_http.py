import asyncio
import gzip
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_d5_http import digest, percentile, score, traffic_key, window


def cohort():
    return {"profiles": {"P1": ["a"]}, "specs": {"a": {"path": "/a", "body_sha256": digest({"answer": 42})}}}


def test_nearest_rank_keeps_tail_and_empty():
    assert percentile([], 0.95) is None
    assert percentile(list(range(1, 21)), 0.95) == 19
    assert percentile([1, 2], 0.95) == 2


def test_missing_duplicate_and_forged_success_rejected(tmp_path):
    path = tmp_path / "requests.jsonl.gz"
    row = {
        "sequence": 0,
        "key": "a",
        "status": 200,
        "elapsed_ms": 1,
        "error": None,
        "body_sha256": "wrong",
        "correct": True,
    }

    def save(rows):
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item) + "\n")

    metadata = {"requests": 1, "elapsed_seconds": 1, "target_seconds": 1}
    save([row])
    with pytest.raises(ValueError, match="scoring mismatch"):
        score(path, cohort(), "P1", metadata)
    row.update(body_sha256=digest({"answer": 42}))
    save([row, row])
    with pytest.raises(ValueError, match="missing or duplicate"):
        score(path, cohort(), "P1", {**metadata, "requests": 2})
    save([])
    with pytest.raises(ValueError, match="missing or duplicate"):
        score(path, cohort(), "P1", metadata)


def test_short_window_rejected(tmp_path):
    path = tmp_path / "empty.gz"
    with gzip.open(path, "wt"):
        pass
    with pytest.raises(ValueError, match="shortened"):
        score(path, cohort(), "P1", {"requests": 0, "elapsed_seconds": 0.5, "target_seconds": 1})


def test_sequence_has_exact_declared_hotspot_distribution():
    example = {"profiles": {"P1": ["hot"] * 8 + ["next", "other"]}}
    keys = [traffic_key(example, "P1", i) for i in range(100)]
    assert keys.count("hot") == 80 and keys.count("next") == keys.count("other") == 10


def test_real_http_failure_keeps_actual_latency_and_denominator(tmp_path):
    async def exercise():
        count = 0

        async def answer(request):
            nonlocal count
            count += 1
            await asyncio.sleep(0.01)
            return web.json_response({"answer": 42}, status=500 if count % 3 == 0 else 200)

        app = web.Application()
        app.router.add_get("/a", answer)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        path = tmp_path / "actual.gz"
        try:
            meta = await window(f"http://127.0.0.1:{port}", cohort(), "P1", 2, 0.15, path)
        finally:
            await runner.cleanup()
        summary = score(path, cohort(), "P1", meta)
        assert summary["failed"] > 0 and summary["success"] > 0
        assert summary["total"] == summary["failed"] + summary["success"] == count
        assert 5 < summary["failure_p95_ms"] < 1000
        with pytest.raises(FileExistsError):
            await window("http://127.0.0.1:1", cohort(), "P1", 1, 0.01, path)

    asyncio.run(exercise())


def test_fault_recovery_clock_includes_time_since_actual_restore():
    import time

    from evaluation.backend_d5_faults import recovery

    async def exercise():
        async def answer(request):
            return web.json_response({"answer": 42})

        app = web.Application()
        app.router.add_get("/a", answer)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        anchor = time.time_ns() - 2_000_000_000
        try:
            result = await recovery(f"http://127.0.0.1:{port}", cohort(), "P1", anchor)
            assert result["anchor_ns"] == anchor
            assert 2 <= result["first_success_seconds"] < 5
            assert len(result["followup"]) == 10 and all(r["correct"] for r in result["followup"])
            expired = await recovery(f"http://127.0.0.1:{port}", cohort(), "P1", time.time_ns() - 6_000_000_000)
            assert expired["first_success_seconds"] is None and expired["observations"] == []
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
