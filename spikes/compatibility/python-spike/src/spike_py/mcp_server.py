"""Minimal real MCP stdio tool server.

Mirrors the shape the project needs (docs/architecture.md: read-only business
tools served over stdio, no public MCP endpoint). Exists in T00 only to prove the
official SDK's stdio path actually works; the six real tools land in T18.

Note: the MCP Python SDK 2.x renamed FastMCP to MCPServer (mcp.server.mcpserver).
Any v1-era sample code using mcp.server.fastmcp will not run against 2.x.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

SERVER_NAME = "resolveflow-spike-tools"

server = MCPServer(
    name=SERVER_NAME,
    version="0.0.1",
    instructions="T00 spike: read-only evidence tools over stdio.",
)

# Stand-in for the authority-owned data the real tool adapters will call.
_ORDER_LINE = {
    "line_id": "7001",
    "order_id": "9001",
    "sku": "SKU-1",
    "line_paid_amount_minor": 20000,
    "currency": "CNY",
}


@server.tool(
    name="read_order_line",
    description="Read the authoritative paid amount for an order line (read-only).",
)
def read_order_line(line_id: str) -> dict:
    if line_id != _ORDER_LINE["line_id"]:
        # Returning an explicit not-found result rather than raising keeps the
        # failure visible to the model as an observation, not an infrastructure error.
        return {"found": False, "line_id": line_id}
    return {"found": True, **_ORDER_LINE}


@server.tool(
    name="read_shipment_track",
    description="Read shipment tracking events for a shipment (read-only).",
)
def read_shipment_track(shipment_id: str) -> dict:
    if shipment_id != "ship-1":
        return {"found": False, "shipment_id": shipment_id}
    return {
        "found": True,
        "shipment_id": shipment_id,
        "carrier": "SF",
        "events": [
            {"code": "PICKED_UP", "at": "2026-09-01T02:00:00Z"},
            {"code": "DAMAGED", "at": "2026-09-02T07:30:00Z", "note": "包裹受损"},
        ],
    }


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()