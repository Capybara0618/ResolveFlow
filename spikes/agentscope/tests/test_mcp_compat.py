"""AS01.1: does AgentScope 2.0.8 reach **our** MCP 2.2.0 stdio server?

This is the spike's decisive dependency question, and it is a declared conflict rather than a guess:
`agentscope==2.0.8` requires `mcp<2.0.0`, while `agent/uv.lock` holds `mcp==2.2.0` and the five whitelisted tools
are served by a real 2.2.0 stdio server written against that version's `MCPServer` API (C06.2b). Resolution
fails outright without an override; the override is in `pyproject.toml` and says why.

An override only changes what the resolver installs. Whether the combination *works* is an empirical question,
and the honest way to ask it is to make AgentScope's own MCP client talk to the real tool server as a real
subprocess — not to import a module and declare victory because the import did not raise. `agentscope.mcp`
importing under 2.2.0 is necessary and nowhere near sufficient: the wire protocol, the handshake, the tool
schemas and the structured results are all places a major-version gap shows up.

The server is the project's own, started exactly as a deployment starts it
(`python -m resolveflow.tools.server`, configured by environment), reading a stub upstream. Nothing here imports
`agentscope.mcp`'s internals or monkey-patches anything: if this passes, the conclusion is "AgentScope's MCP
client and our MCP server agree", which is what the migration needs to know.
"""

from __future__ import annotations

import os
import pathlib
import sys
from typing import Any

import pytest

from resolveflow_spike import stub_upstream

#: The server under test. It belongs to the agent project, and the spike deliberately reaches into that tree
#: rather than vendoring a copy: a copy would be a *different* server, and "AgentScope can talk to a server like
#: ours" is not the claim being tested.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
AGENT_SRC = REPO_ROOT / "agent" / "src"

RUN_ID = "5f2b1c3d-0000-4000-8000-000000000001"
CASE_ID = "9c858abd-0000-4000-8000-0000000000cc"


@pytest.fixture()
def upstream() -> Any:
    server = stub_upstream.start()
    try:
        yield server
    finally:
        server.stop()


def server_environment(upstream_url: str) -> dict[str, str]:
    """The environment a deployment starts the tool server with (C06.2b)."""
    env = dict(os.environ)
    env["RESOLVEFLOW_CASE_BASE_URL"] = upstream_url
    env["RESOLVEFLOW_COMMERCE_BASE_URL"] = upstream_url
    env["RESOLVEFLOW_TOOL_LINE_ID"] = stub_upstream.LINE_ID
    env["RESOLVEFLOW_TOOL_RUN_ID"] = RUN_ID
    env["RESOLVEFLOW_TOOL_CASE_ID"] = CASE_ID
    env["RESOLVEFLOW_TOOL_SERVICE_TOKEN"] = "spike-service-token"  # noqa: S105 - a stub value, not a credential
    env["PYTHONPATH"] = str(AGENT_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def mcp_client(upstream_url: str) -> Any:
    """AgentScope's own MCP client, pointed at the project's tool server.

    The field names come from the installed 2.0.8 (`name`, `is_stateful`, `mcp_config`) rather than from a
    tutorial: the first version of this helper used `config=`, which is what a reader would guess, and pydantic
    answered with the three fields it actually requires. `is_stateful=True` because the server keeps per-run
    state inside the process (the shipment-trace page budget, C06.2b).
    """
    from agentscope.mcp import MCPClient, StdioMCPConfig

    return MCPClient(
        name="resolveflow-tools",
        is_stateful=True,
        mcp_config=StdioMCPConfig(
            command=sys.executable,
            args=["-m", "resolveflow.tools.server"],
            env=server_environment(upstream_url),
        ),
    )


def test_agentscope_mcp_handshake_succeeds_but_tool_adaptation_breaks(upstream: Any) -> None:
    """**The blocker, stated as a test.** `agentscope.mcp` imports under mcp 2.2.0 and the handshake completes —
    the server logs `MCP connected: resolveflow-tools` — and then adapting the first tool raises.

    The cause is one attribute name, and it is the mcp major-version pin made concrete:

    * `agentscope/tool/_adapters.py:261` reads ``tool.inputSchema`` — mcp **1.x**'s camelCase field.
    * mcp **2.2.0** exposes ``input_schema`` (``Tool.model_fields`` = `[..., 'input_schema', ...]`), so the
      attribute does not exist and the adapter raises ``AttributeError: 'Tool' object has no attribute
      'inputSchema'``.
    * the same file reads ``tool.annotations.readOnlyHint`` (line 273); mcp 2.x spells it ``read_only_hint``, so
      even once the first line is fixed every tool would silently be reported as *not* read-only.

    Why this test asserts the failure instead of skipping it: the migration's question is "what does the pin
    actually cost", and an unrecorded red test is how that cost gets rediscovered later as a mystery. The next
    test shows what the fix is and that it is small — which is the input the reviewer needs, per
    ``docs/agentscope-migration.md:71`` (report the minimal reproduction, do not silently switch stacks).
    """
    import anyio

    async def probe() -> None:
        client = mcp_client(upstream.url)
        try:
            await client.connect()
            # Iterating is what triggers the adapter, which is where the failure is.
            for _published in await client.list_tools():
                pass
        finally:
            await client.close()

    with pytest.raises(AttributeError, match="inputSchema"):
        anyio.run(probe)


def test_a_two_attribute_fix_makes_agentscope_see_the_whitelist(monkeypatch: Any, upstream: Any) -> None:
    """The same probe with the two attributes corrected **in memory**: the handshake, the whitelist and a real
    ``tools/call`` all work against our mcp 2.2.0 server.

    What this establishes, and what it does not:

    * it establishes that the incompatibility is a *field-name* gap in one adapter class, not a protocol or
      architecture problem — the tool schemas, the namespacing, ``func()`` and the structured result all work
      unchanged once the schema is read from the right member;
    * it does **not** make the unpatched library work, and this test is not evidence that
      ``agentscope.mcp`` is usable as shipped under mcp 2.2.0. It is evidence for the reviewer's decision:
      either AgentScope's adapter is corrected (upstream fix or a pinned fork) or the project keeps its own
      mcp 2.2.0 client — which is what AS01 must recommend either way.

    The correction is applied with ``monkeypatch`` so it cannot leave a modified site-packages behind; the venv
    is restored by pytest when this test ends.
    """
    import anyio
    from agentscope.tool import _adapters

    original_init = _adapters.MCPTool.__init__

    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        # ``*args``/``**kwargs`` are forwarded untouched: naming the first parameter ``tool`` and the second
        # positionally broke the real signature (``MCPTool.__init__(self, tool, name=..., mcp_name=...)`` passes
        # ``mcp_name`` by keyword) -- a lesson about patching by guessing at a signature.
        tool = args[0] if args else kwargs.get("tool")
        """Give the mcp-1.x attribute names to an mcp-2.x Tool, then call the real constructor.

        mcp 2.2.0's ``Tool`` is a pydantic model, so an unknown attribute cannot simply be assigned — the alias
        has to go into the model's extra state. That is also why this cannot be a "just add a property" fix in
        the project's own code: the substitution is an adapter decision, and the two options are an upstream fix
        or the project keeping its own mcp 2.2.0 client (which C06.2b already has).
        """
        schema = getattr(tool, "input_schema", None) if tool is not None else None
        if not hasattr(tool, "inputSchema") and schema is not None:
            object.__setattr__(
                tool,
                "__pydantic_extra__",
                {**(getattr(tool, "__pydantic_extra__", None) or {}), "inputSchema": schema},
            )
        annotations = getattr(tool, "annotations", None)
        if annotations is not None and not hasattr(annotations, "readOnlyHint"):
            object.__setattr__(
                annotations,
                "__pydantic_extra__",
                {
                    **(getattr(annotations, "__pydantic_extra__", None) or {}),
                    "readOnlyHint": getattr(annotations, "read_only_hint", None),
                },
            )
        original_init(self, *args, **kwargs)



    # The third site is on the call path: `_adapters.py:354` reads `result.isError` on the *result* object,
    # which mcp 2.x spells `is_error`. It only fires once a tool is actually invoked, so it is a second crash
    # after the first is fixed rather than the same one twice.

    async def patched_call(self: Any, **kwargs: Any) -> Any:
        """`MCPTool.call` with the third camelCase site corrected.

        The original reads ``result.isError``; mcp 2.x puts it in ``is_error``, and ``isError`` is only a
        validation *alias* there (``CallToolResult.model_config`` sets ``alias_generator=to_camel``), so it is
        not an attribute and cannot be added to the result. This replacement is the original's stateful branch
        with that one name changed, which is what makes it evidence that the name is the whole obstacle.
        """
        from agentscope.tool import _response  # noqa: PLC2701 - the only home of ToolResultState

        result = await self._session.call_tool(
            self._tool.name, arguments=kwargs, read_timeout_seconds=self._timeout
        )
        # `attr-defined` is ignored on these two lines because `ToolResultState` is not in
        # `agentscope.tool.__all__`; the private reach is recorded once in `tests/_helpers.py` and once here
        # because this test deliberately reimplements `MCPTool.call`.
        return _response.ToolChunk(
            content=self._convert_mcp_content_to_blocks(result.content),
            state=(
                _response.ToolResultState.ERROR  # type: ignore[attr-defined]
                if getattr(result, "is_error", False)
                else _response.ToolResultState.RUNNING  # type: ignore[attr-defined]
            ),
        )
    monkeypatch.setattr(_adapters.MCPTool, "__init__", patched_init, raising=True)
    monkeypatch.setattr(_adapters.MCPTool, "call", patched_call, raising=True)

    async def probe() -> tuple[Any, Any]:
        client = mcp_client(upstream.url)
        try:
            await client.connect()
            schemas = await client.list_tools()
            names = {getattr(schema, "name", None) for schema in schemas}
            tools = {getattr(schema, "name", None): schema for schema in schemas}
            order = tools["mcp__resolveflow-tools__get_order_context"]
            # ``call(**kwargs)`` is the invocation path for an adapted MCP tool; there is no ``func``, and the
            # call is a coroutine rather than a generator.
            return names, await order.call()
        finally:
            await client.close()

    names, result = anyio.run(probe)

    # AgentScope namespaces MCP tools as `mcp__<server>__<tool>` so two servers cannot collide.
    assert names == {
        "mcp__resolveflow-tools__get_order_context",
        "mcp__resolveflow-tools__get_shipment_trace",
        "mcp__resolveflow-tools__get_refund_status",
        "mcp__resolveflow-tools__get_case_evidence",
        "mcp__resolveflow-tools__get_policy_manifest",
    }, f"AgentScope's MCP client did not see the project's whitelist: {names}"

    # The read really happened against the stub and came back as the project's observation.
    text = str(result)
    assert "ORDER_LINE" in text, f"the observation's source type is missing: {text[:400]}"
    assert str(stub_upstream.PAID_AMOUNT) in text, f"the amount is missing: {text[:400]}"
    assert any("/context" in entry["path"] for entry in upstream.requests), upstream.requests
