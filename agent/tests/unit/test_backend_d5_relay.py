import asyncio
import sys
from collections import Counter
from pathlib import Path

import aiohttp
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_d5_normal import plan
from evaluation.backend_d5_relay import Relay


def test_frozen_48_windows_and_rotated_conditions():
    windows = plan()
    assert len(windows) == len({r["id"] for r in windows}) == 48
    assert Counter(r["profile"] for r in windows) == {"P1": 18, "P2": 12, "P3": 18}
    assert all(r["warmup"] == 30 and r["seconds"] == 60 for r in windows)
    assert [r["condition"] for r in windows if r["profile"] == "P1" and r["concurrency"] == 10] == list(
        "ABCB CACAB".replace(" ", "")
    )


def test_actual_two_targets_round_robin_and_owned_redis_faults():
    async def exercise():
        servers = []

        async def node(value):
            async def response(request):
                return web.json_response({"node": value})

            app = web.Application()
            app.router.add_get("/data", response)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            servers.append(runner)
            return f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"

        async def echo(reader, writer):
            try:
                while data := await reader.read(1024):
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()

        upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
        relay = Relay("a" * 32, [await node(0), await node(1)], upstream.sockets[0].getsockname()[1])
        proxy = await asyncio.start_server(relay.redis, "127.0.0.1", 0)
        runner = web.AppRunner(await relay.app())
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.sockets[0].getsockname()[1])
        try:
            async with aiohttp.ClientSession() as client:
                values = []
                for _ in range(4):
                    async with client.get(base + "/data") as response:
                        values.append((await response.json())["node"])
                assert values == [0, 1, 0, 1] and relay.counts == [2, 2]
                async with client.post(base + "/__d5/mode", json={"mode": "drop"}) as response:
                    assert response.status == 403
                writer.write(b"normal")
                await writer.drain()
                assert await asyncio.wait_for(reader.readexactly(6), 1) == b"normal"
                headers = {"X-D5-Run": "a" * 32}
                async with client.post(base + "/__d5/mode", json={"mode": "stall"}, headers=headers) as response:
                    assert response.status == 200
                writer.write(b"wait")
                await writer.drain()
                task = asyncio.create_task(reader.readexactly(4))
                await asyncio.sleep(0.03)
                assert not task.done()
                async with client.post(base + "/__d5/mode", json={"mode": "normal"}, headers=headers):
                    pass
                assert await asyncio.wait_for(task, 1) == b"wait"
                async with client.post(base + "/__d5/mode", json={"mode": "drop"}, headers=headers):
                    pass
                assert await asyncio.wait_for(reader.read(1), 1) == b""
        finally:
            writer.close()
            proxy.close()
            upstream.close()
            await proxy.wait_closed()
            await upstream.wait_closed()
            await runner.cleanup()
            for server in servers:
                await server.cleanup()

    asyncio.run(exercise())
