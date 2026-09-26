"""In-process regression guard, used inside a network-disabled replay container."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import patch


@contextmanager
def block_network() -> Iterator[list[str]]:
    """Install after asyncio initializes; OS isolation is supplied by the CLI container."""
    attempts: list[str] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        attempts.append(repr((args, kwargs)))
        raise OSError("strict replay forbids network access")

    with ExitStack() as stack:
        for target, names in (
            (socket, ("create_connection", "getaddrinfo")),
            (socket.socket, ("connect", "connect_ex", "sendto")),
            (asyncio.BaseEventLoop, ("create_connection", "sock_connect", "create_datagram_endpoint")),
        ):
            for name in names:
                stack.enter_context(patch.object(target, name, refuse))
        yield attempts
