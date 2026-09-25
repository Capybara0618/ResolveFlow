"""Shared fakes for the spike's tests: a scripted model and a self-counting tool.

These live outside the test modules because two of them need the same fakes (control and recovery), and because
`ScriptedModel` embeds facts about the real SDK that are worth reading on their own: which method a provider
subclass must implement, what `ChatModelBase.__init__` requires, what a tool call block looks like in 2.x, and
which SDK defaults have to be overridden for our constraints to hold.

They are deliberately *not* in `resolveflow_spike` (the production-shaped package): a fake model is test
machinery, and putting it in the importable package would invite production code to depend on it.
"""

from __future__ import annotations

import pathlib
from typing import Any

import anyio
from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg
from agentscope.model import ChatModelBase, ChatResponse
from agentscope.tool import ToolBase, Toolkit

# `ToolResultState` is the state a `ToolChunk` carries. AgentScope 2.0.8 does not list it in
# `agentscope.tool.__all__`; `agentscope.tool._response` is its only home, so this is a private reach. It is done
# **once, here**, so the private dependency is one line to change when AS02 decides how to handle it, instead of
# scattered through the tests.
from agentscope.tool._response import ToolResultState  # type: ignore[attr-defined]

from resolveflow_spike.adapter import BudgetMiddleware, RefusingPermissionMiddleware, ToolNames

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
ACTIONS_PY = REPO_ROOT / "agent" / "src" / "resolveflow" / "harness" / "actions.py"
WHITELIST = ToolNames.from_project(ACTIONS_PY)

__all__ = [
    "ToolResultState",
    "ACTIONS_PY",
    "WHITELIST",
    "CountingTool",
    "ScriptedModel",
    "agent_with",
    "run_agent",
]

# ------------------------------------------------------------------ the tools


class CountingTool(ToolBase):
    """A tool that records every execution of its body.

    The counter is the evidence. `docs/agentscope-migration.md:41` says a batch mixing an illegal action with
    legal ones must be refused *whole*, so "did the legal read run anyway" has to be answerable from the tool's
    own side rather than from the permission decision.

    ``check_permissions`` is abstract on ``ToolBase`` and is implemented as ``passthrough``: the spike's gate is
    the *middleware*, and a tool that also decided permissions would make it ambiguous which one refused — the
    thing this test is trying to measure.
    """

    def __init__(self, name: str, executions: list[str]) -> None:
        self.name = name
        self.description = f"spike tool {name}"
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
        """Pass the decision to the middleware: this tool has no opinion of its own."""
        from agentscope.permission import PermissionBehavior, PermissionDecision

        return PermissionDecision(
            behavior=PermissionBehavior.PASSTHROUGH, message="the spike gate is the middleware"
        )

    async def call(self, **kwargs: Any) -> Any:
        self._executions.append(self.name)
        from agentscope.tool import ToolChunk
        from agentscope.tool._response import ToolResultState  # type: ignore[attr-defined]

        return ToolChunk(content=[], state=ToolResultState.SUCCESS)


# ------------------------------------------------------------------ the scripted model


class ScriptedModel(ChatModelBase):
    """A `ChatModelBase` that returns one scripted `ChatResponse` per call and counts them.

    Subclassing the real base rather than duck-typing: the budget hook calls the model's own `count_tokens`, and
    the point of that is to prove the interception covers AgentScope's real input surface rather than an
    estimate the spike chose.

    ``max_retries=0`` is not a default — the base class defaults to **3**, which would mean the SDK retried
    failed calls *underneath* our budget hook: three provider requests for one reservation. That is the "only one
    layer retries" rule of `docs/agent-spec.md:40` being broken by a library default, and finding it is part of
    what this sub-step is for. The spike sets it to zero and the compatibility report records it, because the
    production adapter (AS02) has to make the same choice explicitly rather than inherit it.
    """

    def __init__(self, tool_calls: list[tuple[str, dict[str, Any]]], **kwargs: Any) -> None:
        from pydantic import BaseModel

        class _NoParameters(BaseModel):
            """The parameter bag a real model class would carry (temperature, top_p, ...).

            ``BaseModel`` itself cannot be instantiated, so the spike passes a concrete empty one. A provider
            adapter would pass its own; what matters for this sub-step is only that ``parameters`` is part of the
            recorded input rather than an afterthought.
            """

        super().__init__(
            credential=kwargs.pop("credential", None),
            model="spike-scripted",
            parameters=_NoParameters(),
            stream=False,
            max_retries=0,
            **kwargs,
        )
        # A provider model class always carries a formatter (`DeepSeekChatModel` sets
        # `formatter or DeepSeekChatFormatter()`); the agent loop consults it to decide which media types the
        # model can accept, so a model without one fails before the first turn. Setting it here is a fact about
        # what an adapter must supply, not a spike convenience.
        from agentscope.formatter import DeepSeekChatFormatter

        self.formatter = DeepSeekChatFormatter()
        self._script = list(tool_calls)
        self.calls = 0
        self.seen_messages: list[list[Msg]] = []

    async def _call_api(
        self,
        model_name: str,
        messages: list[Msg],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """The extension point a provider subclass implements.

        ``_call_api`` rather than ``__call__``: the base's ``__call__`` wraps this, streams it and accumulates
        chunks, so overriding ``__call__`` would skip the wrapper the real loop uses — and the first version of
        this class did exactly that (mypy caught it as ``Cannot instantiate abstract class ... with abstract
        attribute '_call_api'``, which is the kind of thing a duck-typed fake would have silently let through).

        The count lives here because this is the call that would reach a provider.
        """
        self.calls += 1
        self.seen_messages.append(list(messages))
        if not self._script:
            # A final answer with no tool call ends the loop. The text is deliberately not a plan: an ordinary
            # reply is not a valid proposal (docs/agentscope-migration.md:40).
            from agentscope.message import TextBlock

            return ChatResponse(content=[TextBlock(type="text", text="(spike) no further action")], is_last=True)
        name, arguments = self._script.pop(0)
        import json

        from agentscope.message import ToolCallBlock

        # 2.x spells the block `tool_call` (1.x used `tool_use`) and carries the arguments as a JSON *string*
        # rather than a dict — both are shapes an adapter has to produce, so getting them wrong here is how the
        # spike learns them rather than how production discovers them.
        return ChatResponse(
            content=[
                ToolCallBlock(
                    type="tool_call", id=f"call-{self.calls}", name=name, input=json.dumps(arguments)
                )
            ],
            is_last=True,
        )


def agent_with(
    model: ChatModelBase,
    tools: list[ToolBase],
    *,
    permission: RefusingPermissionMiddleware,
    budget: BudgetMiddleware,
    max_iters: int = 10,
) -> Agent:
    # ``Toolkit.add_tool`` is a **coroutine**, which is easy to miss: an un-awaited call leaves the toolkit
    # empty, and the loop then does not fail -- it quietly produces a final text reply as though the model had
    # chosen to stop. The first version of this helper made exactly that mistake, and the symptom ("no tool
    # executed and no permission refused") reads like a middleware bug and was a missing ``await``.
    toolkit = Toolkit()

    async def assemble() -> None:
        for tool in tools:
            await toolkit.add_tool(tool)

    anyio.run(assemble)
    return Agent(
        name="spike-agent",
        system_prompt="You investigate one order line. Use only the tools you are given.",
        model=model,
        toolkit=toolkit,
        middlewares=[permission, budget],
        react_config=ReActConfig(max_iters=max_iters),
    )


def run_agent(agent: Agent, prompt: str = "investigate") -> Any:
    """Drive one reply to completion.

    ``Agent.reply`` is a coroutine that returns the final ``Msg`` and consumes the event stream itself — it is
    not an async generator, which an earlier version of this helper assumed. It also needs content as a list of
    blocks rather than a string.
    """
    from agentscope.message import TextBlock

    async def drive() -> Any:
        message = Msg(name="spike-user", content=[TextBlock(type="text", text=prompt)], role="user")
        return await agent.reply(message)

    return anyio.run(drive)
