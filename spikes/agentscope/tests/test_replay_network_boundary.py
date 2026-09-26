"""Regression probes for replay egress, isolated from pytest's own event loop.

Only a localhost listener is used. A successful connection is a guard bypass,
not a dependency on an external service. Initialize asyncio before installing
the guard: Windows creates its own socketpair during loop initialization.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys

import pytest

_PROBE = r"""
import asyncio
import json
import socket
import sys

from resolveflow_spike.replay import block_network

api, port = sys.argv[1], int(sys.argv[2])
address = ("127.0.0.1", port)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Establish that the listening target really is reachable before the guard.
with socket.create_connection(address, timeout=2):
    pass

async def connect_async():
    _, writer = await asyncio.wait_for(asyncio.open_connection(*address), timeout=2)
    writer.close()
    await writer.wait_closed()

guard = block_network()
attempts = guard.__enter__()
blocked = False
detail = "connection succeeded"
try:
    # A runtime failure before the connection must not masquerade as isolation.
    assert loop.run_until_complete(asyncio.sleep(0, result="ready")) == "ready"
    if api == "create_connection":
        with socket.create_connection(address, timeout=2):
            pass
    elif api == "asyncio":
        loop.run_until_complete(connect_async())
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            result = getattr(client, api)(address)
            if api == "connect_ex" and result != 0:
                raise RuntimeError(f"unexpected transport error {result}, not the replay guard")
except OSError as exc:
    detail = str(exc)
    blocked = "forbids network access" in detail
finally:
    guard.__exit__(None, None, None)
    loop.close()
print(json.dumps({"blocked": blocked, "detail": detail, "attempts": attempts}))
"""


@pytest.mark.parametrize("api", ["create_connection", "connect", "connect_ex", "asyncio"])
def test_replay_rejects_each_outbound_connection_path_in_a_child_process(api: str) -> None:
    """Every supported path fails at the guard, even for a reachable localhost service."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        port = listener.getsockname()[1]
        child = subprocess.run(  # noqa: S603 - fixed probe, our own interpreter, no shell
            [sys.executable, "-c", _PROBE, api, str(port)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    assert child.returncode == 0, f"probe runtime failed, not a proven guard: {child.stderr}"
    result = json.loads(child.stdout.strip().splitlines()[-1])
    assert result["blocked"], f"{api} bypassed replay egress isolation: {result}"
    assert result["attempts"], f"{api} was rejected without recording the destination"
