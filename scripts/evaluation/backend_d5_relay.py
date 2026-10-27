"""Explicitly owned loopback HTTP round robin and Redis fault proxy for D5 only."""

from __future__ import annotations

import argparse
import asyncio
import json

import aiohttp
from aiohttp import web


class Relay:
    def __init__(self, identity, targets, redis_port):
        self.identity, self.targets, self.redis_port = identity, targets, redis_port
        self.sequence = 0
        self.mode = "normal"
        self.changed = asyncio.Event()
        self.changed.set()
        self.writers = set()
        self.counts = [0] * len(targets)
        self.active = 0
        self.errors = 0
        self.history = []
        self.client = None

    async def redis(self, source, sink):
        remote = None
        try:
            if self.mode == "drop":
                return
            reader, remote = await asyncio.open_connection("127.0.0.1", self.redis_port)
            self.writers.update((sink, remote))

            async def copy(read, write):
                while data := await read.read(65536):
                    if self.mode == "drop":
                        return
                    await self.changed.wait()
                    write.write(data)
                    await write.drain()

            jobs = [
                asyncio.create_task(copy(source, remote)),
                asyncio.create_task(copy(reader, sink)),
            ]
            _, pending = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
        except (OSError, ConnectionError):
            self.errors += 1
        finally:
            for writer in (sink, remote):
                if writer:
                    self.writers.discard(writer)
                    writer.close()

    async def control(self, request):
        if request.headers.get("X-D5-Run") != self.identity:
            raise web.HTTPForbidden()
        if request.method == "POST":
            mode = (await request.json())["mode"]
            if mode not in ("normal", "drop", "stall"):
                raise web.HTTPBadRequest()
            self.mode = mode
            if mode == "stall":
                self.changed.clear()
            else:
                self.changed.set()
            if mode == "drop":
                for writer in list(self.writers):
                    writer.close()
            import time

            self.history.append({"mode": mode, "at_ns": time.time_ns()})
        return web.json_response(
            {
                "mode": self.mode,
                "requests": self.counts,
                "active": self.active,
                "redis_errors": self.errors,
                "history": self.history,
            }
        )

    async def forward(self, request):
        index = self.sequence % len(self.targets)
        self.sequence += 1
        self.counts[index] += 1
        self.active += 1
        excluded = {
            "host",
            "connection",
            "content-length",
            "transfer-encoding",
            "accept-encoding",
        }
        headers = {
            k: v for k, v in request.headers.items() if k.lower() not in excluded
        }
        try:
            async with self.client.request(
                request.method,
                self.targets[index] + request.raw_path,
                headers=headers,
                data=await request.read(),
            ) as response:
                body = await response.read()
                return web.Response(
                    status=response.status,
                    body=body,
                    headers={
                        "Content-Type": response.headers.get(
                            "Content-Type", "application/json"
                        ),
                        "X-D5-Node": str(index),
                    },
                )
        except (aiohttp.ClientError, TimeoutError, OSError):
            self.errors += 1
            return web.json_response(
                {"error": "D5_RELAY_UPSTREAM_UNAVAILABLE"}, status=503
            )
        finally:
            self.active -= 1

    async def app(self):
        app = web.Application()
        app.router.add_get("/__d5/snapshot", self.control)
        app.router.add_post("/__d5/mode", self.control)
        app.router.add_route("*", "/{path:.*}", self.forward)

        async def lifespan(app):
            self.client = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=3),
                trust_env=False,
                connector=aiohttp.TCPConnector(limit=100),
                auto_decompress=False,
            )
            yield
            await self.client.close()

        app.cleanup_ctx.append(lifespan)
        return app


async def serve(args):
    if len(args.run_id) != 32 or any(c not in "0123456789abcdef" for c in args.run_id):
        raise ValueError("explicit run identity required")
    relay = Relay(
        args.run_id, [f"http://127.0.0.1:{p}" for p in args.targets], args.redis_target
    )
    redis = await asyncio.start_server(relay.redis, "127.0.0.1", args.redis_listen)
    runner = web.AppRunner(await relay.app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.http_listen).start()
    print(json.dumps({"ready": True, "run_id": args.run_id}), flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        redis.close()
        await redis.wait_closed()
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--http-listen", type=int, required=True)
    parser.add_argument("--redis-listen", type=int, required=True)
    parser.add_argument("--redis-target", type=int, required=True)
    parser.add_argument("--targets", type=int, nargs="+", required=True)
    asyncio.run(serve(parser.parse_args()))


if __name__ == "__main__":
    main()
