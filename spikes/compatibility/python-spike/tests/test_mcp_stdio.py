"""T00 gate: a real MCP stdio session — spawn the server, list tools, call a tool.

Exercises the actual MCP protocol over stdio rather than calling the Python
function directly, which is what docs/architecture.md depends on (ADR 06).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_SCRIPT = Path(__file__).resolve().parents[1] / "src" / "spike_py" / "mcp_server.py"


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        # The server module lives under src/; the venv's python needs the path.
        env={"PYTHONPATH": str(SERVER_SCRIPT.parents[1]), "PYTHONIOENCODING": "utf-8"},
    )


@pytest.mark.asyncio
async def test_stdio_session_lists_and_calls_tools():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.server_info.name == "resolveflow-spike-tools"

            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"read_order_line", "read_shipment_track"} <= names

            result = await session.call_tool("read_order_line", {"line_id": "7001"})
            assert not result.is_error
            payload = result.structured_content or result.content
            # The tool returns the authoritative paid amount; the point is that it
            # crossed a real MCP boundary, not that the value is interesting.
            assert "20000" in str(payload) or 20000 in str(payload)


@pytest.mark.asyncio
async def test_tool_reports_not_found_without_failing_the_session():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("read_order_line", {"line_id": "does-not-exist"})
            assert not result.is_error, "a missing record is an observation, not a protocol error"
            assert "false" in str(result.structured_content or result.content).lower()


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("definitely_not_a_tool", {})
            # The server must not silently pretend an unknown tool succeeded.
            assert result.is_error