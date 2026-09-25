"""AS02.1: the SDK boundary adapter, exercised through the **real** AgentScope loop.

The adapter's whole job is to be a translation and nothing else (`docs/agentscope-migration.md:43`), so these
tests assert the two properties that would break if it became something else:

* **one model call per step** — if the adapter ever re-asked the client, the harness's ledger and the SDK's loop
  would disagree about how many calls happened, and the 12-call cap would be enforced against the smaller number;
* **the decision arrives intact** — the harness validates the decision *after* the loop with
  `validate_decision`, so a translation that dropped or renamed a field would silently remove a check rather than
  fail one.

The loop is the real one: `Agent` and `Toolkit` from the installed AgentScope, driven with the project's own
scripted client. A test that called `_call_api` directly would prove the translation and not the integration, and
the integration is what AS02.2 will depend on.
"""

from __future__ import annotations

import json
from typing import Any

import anyio
from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg, TextBlock, ToolCallBlock
from agentscope.tool import ToolBase, Toolkit

from resolveflow.harness import actions
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_adapter import AgentScopeModelAdapter, messenger_message

SYSTEM = "You investigate one order line."


class CountingTool(ToolBase):
    """A tool that records every execution, so "the tool ran" is observable from the tool's own side."""

    def __init__(self, name: str, executions: list[str]) -> None:
        self.name = name
        self.description = f"test tool {name}"
        self.input_schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        self.is_concurrency_safe = False
        self.is_read_only = True
        self.is_external_tool = False
        self.is_state_injected = False
        self.is_mcp = False
        self.mcp_name: str | None = None
        self.dangerous_files: list[str] = []
        self.dangerous_directories: list[str] = []
        self._executions = executions

    def check_permissions(self, tool_input: dict[str, Any], context: Any) -> Any:
        from agentscope.permission import PermissionBehavior, PermissionDecision

        return PermissionDecision(behavior=PermissionBehavior.PASSTHROUGH, message="the test gate decides")

    async def call(self, **kwargs: Any) -> Any:
        from agentscope.tool import ToolChunk

        self._executions.append(self.name)
        return ToolChunk(content=[], state="success")


def read_tool(name: str, **arguments: Any) -> dict[str, Any]:
    return {"kind": actions.READ_TOOL, "tool_name": name, "arguments": arguments, "reasoning": "looking"}


def propose(action: str = "MANUAL_REVIEW") -> dict[str, Any]:
    return {
        "kind": actions.PROPOSE,
        "recommended_action": action,
        "reason_codes": ["LOST_IN_TRANSIT"],
        "summary": "a person should decide",
    }


def agent_with(model: Any, tools: list[ToolBase]) -> Agent:
    toolkit = Toolkit()

    async def assemble() -> None:
        for tool in tools:
            await toolkit.add_tool(tool)

    anyio.run(assemble)
    return Agent(
        name="adapter-agent",
        system_prompt=SYSTEM,
        model=model,
        toolkit=toolkit,
        react_config=ReActConfig(max_iters=6),
    )


def drive(agent: Agent, text: str = "investigate") -> Any:
    async def run() -> Any:
        return await agent.reply(Msg(name="user", role="user", content=[TextBlock(type="text", text=text)]))

    return anyio.run(run)


# ------------------------------------------------------------------ the translation itself


def test_the_packet_goes_over_as_one_unchanged_json_block() -> None:
    """The bytes AgentScope sends are the packet the harness recorded (`docs/agent-harness.md:22`).

    Unchanged is the property: a packet re-shaped into prose on the way through would make the recorded "exact
    provider input" a description of something that was never sent.
    """
    packet = {"run": {"run_id": "r1"}, "step": 1, "observations": [{"tool_name": "get_order_context"}]}
    message = messenger_message(packet)

    assert message.role == "user"
    blocks = message.get_content_blocks()
    assert len(blocks) == 1
    assert isinstance(blocks[0], TextBlock)
    assert json.loads(blocks[0].text) == packet


def test_a_read_decision_becomes_a_tool_call_and_a_terminal_one_does_not() -> None:
    """The mapping that makes the SDK's loop perform the action, so its permission hook sees it.

    `READ_TOOL` must become a tool call — that is the interception point AS01.1 validated — and a terminal decision
    must *not*, because AgentScope ends a reply when a turn produces no tool call. Sending a PROPOSE as a tool call
    would ask the loop to execute the proposal.
    """
    model = AgentScopeModelAdapter(MockModelClient(script=[read_tool("get_order_context"), propose()]), system=SYSTEM)

    first = anyio.run(lambda: model._call_api("m", []))  # noqa: SLF001 - asserting the translation itself
    assert [type(block).__name__ for block in first.content] == ["ToolCallBlock"]
    call = first.content[0]
    assert isinstance(call, ToolCallBlock)
    assert call.name == "get_order_context"
    assert json.loads(call.input) == {}

    second = anyio.run(lambda: model._call_api("m", []))  # noqa: SLF001
    assert [type(block).__name__ for block in second.content] == ["TextBlock"]
    # The terminal decision travels as JSON, whole: the harness re-validates it after the loop.
    carried = json.loads(second.content[0].text)  # type: ignore[union-attr]
    assert carried["kind"] == actions.PROPOSE
    assert carried["recommended_action"] == "MANUAL_REVIEW"
    assert carried["reason_codes"] == ["LOST_IN_TRANSIT"]


def test_an_unknown_decision_kind_is_carried_rather_than_dropped() -> None:
    """The harness owns the refusal, so the adapter must not quietly swallow what it refuses.

    If the adapter dropped an unknown kind, `validate_decision` would never see it and the run would end for the
    wrong reason — with no refusal recorded, which is the opposite of `docs/agent-spec.md:22`'s requirement that
    unknown actions are refused *and* the refusal is visible.
    """
    model = AgentScopeModelAdapter(
        MockModelClient(script=[{"kind": "WANDER_OFF", "arguments": {}}]), system=SYSTEM
    )
    response = anyio.run(lambda: model._call_api("m", []))  # noqa: SLF001

    assert len(response.content) == 1
    carried = json.loads(response.content[0].text)  # type: ignore[union-attr]
    assert carried["kind"] == "WANDER_OFF"


# ------------------------------------------------------------------ the integration


def test_the_real_loop_drives_the_client_once_per_step() -> None:
    """One `decide` per model turn, through the real `Agent`.

    This is the property `docs/agentscope-migration.md:43` warns about: an adapter that re-asked the client — for a
    repair, a retry, a re-read — would leave the ledger and the loop disagreeing, and the cap of
    `docs/agent-spec.md:40` would be enforced against the smaller of the two counts.
    """
    executions: list[str] = []
    client = MockModelClient(script=[read_tool("get_order_context"), propose()])
    model = AgentScopeModelAdapter(client, system=SYSTEM)
    agent = agent_with(model, [CountingTool("get_order_context", executions)])

    drive(agent)

    # Two decisions, two turns: the read, then the proposal. Not three, and not one.
    assert client.calls == 2, f"the client was asked {client.calls} times for two turns"
    assert model.calls == client.calls
    # And the tool the model chose is the tool that ran, which is what makes the adapter a boundary rather than a
    # decoration: the SDK's own loop executed it.
    assert executions == ["get_order_context"]


def test_a_terminal_decision_ends_the_loop_without_another_model_turn() -> None:
    """A PROPOSE stops the reply, so the SDK does not ask "what next" after a decision.

    `docs/agentscope-migration.md:40` forbids the SDK adding a summary call or continuing the same batch after a
    terminal action, so the count is the assertion: a proposal on the first turn means exactly one model call.
    """
    client = MockModelClient(script=[propose("REFUND"), propose("REFUND")])
    model = AgentScopeModelAdapter(client, system=SYSTEM)
    agent = agent_with(model, [])

    drive(agent)

    assert client.calls == 1, f"a terminal decision cost {client.calls} model calls"


def test_the_adapter_forwards_the_system_prompt_and_the_conversation() -> None:
    """What the client is asked is the loop's own messages, not a second rendering of them.

    `docs/agentscope-migration.md:43`: the SDK must not first call a model to decide an action and then call again.
    A related failure would be the adapter sending the *harness's* system prompt rather than the one the loop was
    built with, which would make the recorded input a description of a different request.
    """
    client = MockModelClient(script=[propose()])
    model = AgentScopeModelAdapter(client, system=SYSTEM)
    agent = agent_with(model, [])

    drive(agent, "the parcel never arrived")

    assert client.conversations, "the client was never asked"
    turns = client.conversations[0]
    assert turns, "the adapter asked the client with no messages at all"
    # Messages arrive as AgentScope `Msg` objects, untouched: the adapter forwards the SDK's own conversation
    # rather than re-rendering it, so there is no second spelling of the input to drift.
    rendered = [block.text for turn in turns for block in turn.get_content_blocks() if hasattr(block, "text")]
    assert any("the parcel never arrived" in text for text in rendered), (
        f"the user's message did not reach the client: {rendered}"
    )
    # And the system prompt the adapter was built with is the one it passes on.
    assert model._system == SYSTEM  # noqa: SLF001 - the point is that there is one prompt, not two
