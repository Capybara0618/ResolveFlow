import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_d5_evidence import capture
from evaluation.backend_d5_http import digest


def test_full_projection_capture_retains_mismatch_without_replacing_expected_hash(tmp_path):
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
        base = f"http://127.0.0.1:{port}"
        cohort = {"specs": {"a": {"path": "/a", "body_sha256": digest({"answer": 42})}}}
        try:
            result = await capture(base, cohort, tmp_path / "correct")
            assert result["a"]["body_sha256"] == cohort["specs"]["a"]["body_sha256"]
            assert json.loads((tmp_path / "correct/a.json").read_text(encoding="utf-8"))["body"] == {"answer": 42}
            with pytest.raises(FileExistsError):
                await capture(base, cohort, tmp_path / "correct")
            cohort["specs"]["a"]["body_sha256"] = "wrong"
            with pytest.raises(ValueError, match="projection changed"):
                await capture(base, cohort, tmp_path / "mismatch")
            assert cohort["specs"]["a"]["body_sha256"] == "wrong"
            saved = json.loads((tmp_path / "mismatch/a.json").read_text(encoding="utf-8"))
            assert saved["body"] == {"answer": 42} and not saved["measurement"]["correct"]
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
