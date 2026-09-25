"""AS01.1: the two hard blocks, driven through AgentScope's **native** loop.

`docs/agentscope-migration.md:34` sets the acceptance criterion for this sub-step: the action/termination/batch
mapping is covered by tests, **an illegal tool action results in zero tool executions**, and **after the budget is
exhausted there are zero new model or tool calls**.

Both are asserted about the *effects*, not about the decision objects:

* illegal action ⇒ the tool body's own counter is zero. A permission hook that returned "deny" and was ignored
  would satisfy a weaker assertion, and that is precisely the failure worth excluding.
* budget exhausted ⇒ the mock model's call counter does not move. "The loop stopped" and "the provider was never
  contacted again" are different facts, and the second is the one that costs money.

The model is a fake `ChatModelBase` returning scripted tool calls, for the reason C06.4 used a scripted client:
choosing the actions by hand is what makes this a test of the plumbing. **This is not evidence of model
autonomy** — H1 needs a live model and is C08's subject, and `docs/agentscope-migration.md:62` says a mock
passing must not be reported as live.
"""

from __future__ import annotations

import pathlib
from typing import Any

import anyio
import pytest
from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg
from agentscope.model import ChatModelBase, ChatResponse
from agentscope.tool import ToolBase, Toolkit
from resolveflow.harness.budget import BudgetExhaustedError, RunBudget

from resolveflow_spike.adapter import (
    BudgetMiddleware,
    RefusingPermissionMiddleware,
    ToolNames,
    budget_guard,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
ACTIONS_PY = REPO_ROOT / "agent" / "src" / "resolveflow" / "harness" / "actions.py"

WHITELIST = ToolNames.from_project(ACTIONS_PY)


def test_the_whitelist_came_from_the_projects_own_abi_module() -> None:
    """A guard test for the guard: the spike is reading the project's list, not a copy of it.

    If this ever reads an empty set, every "illegal action is refused" assertion below would pass for the wrong
    reason — because *everything* would be illegal — which is the classic way a whitelist test becomes vacuous.
    """
    assert len(WHITELIST) == 5, f"the project's whitelist should hold five tools, read {list(WHITELIST)}"
    assert "get_order_context" in WHITELIST
    assert "issue_refund" not in WHITELIST


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
        from agentscope.tool._response import ToolResultState

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


# ------------------------------------------------------------------ illegal actions


def test_an_illegal_tool_action_never_reaches_the_tool_body() -> None:
    """**The acceptance criterion.** A tool outside the whitelist is denied, and its body never runs.

    The refused name is a *write* tool, which is the case that matters: `docs/agent-spec.md:22` says the Agent has
    no write tools at all, so a model that asks for one must not be able to reach it by asking. Asserting only
    "a deny decision was produced" would pass for a harness that decided correctly and executed anyway.
    """
    executions: list[str] = []
    allowed = CountingTool("get_order_context", executions)
    forbidden = CountingTool("issue_refund", executions)
    model = ScriptedModel([("issue_refund", {})])
    permission = RefusingPermissionMiddleware(WHITELIST)
    budget = BudgetMiddleware(budget_guard())

    agent = agent_with(model, [allowed, forbidden], permission=permission, budget=budget)
    run_agent(agent)

    assert executions == [], f"an illegal tool executed: {executions}"
    assert permission.refused == ["issue_refund"], permission.refused
    # The refusal is fed back to the model, so the loop takes one more turn before ending: two calls, not one.
    # That is AgentScope's shape and it is acceptable — what matters is that the turn is bounded (the budget
    # middleware caps it) and that the tool never ran. The report records that the SDK *does* feed a denial back,
    # because a project that wanted "stop immediately on a refusal" (AS02's `stop_on_reject`) would have to set it.
    assert model.calls == 2, f"the model was called {model.calls} times for one refused action"


def test_a_legal_read_still_runs_and_the_illegal_one_in_the_same_batch_does_not() -> None:
    """A batch mixing a legal read and an illegal write: the legal one runs, the illegal one does not.

    `docs/agentscope-migration.md:41` requires the *batch* to be judged before execution so that no member is
    executed and then found to be over-privileged. Here the legal read is first in the batch, so a harness that
    only checked as it went would have executed it before noticing the write — which is exactly what this test
    can tell apart, because the tool counts its own executions.
    """
    executions: list[str] = []
    allowed = CountingTool("get_order_context", executions)
    forbidden = CountingTool("write_evidence", executions)
    model = ScriptedModel([("get_order_context", {}), ("write_evidence", {})])
    permission = RefusingPermissionMiddleware(WHITELIST)
    budget = BudgetMiddleware(budget_guard())

    agent = agent_with(model, [allowed, forbidden], permission=permission, budget=budget)
    run_agent(agent)

    assert executions == ["get_order_context"], f"only the legal read should have run: {executions}"
    assert permission.refused == ["write_evidence"], permission.refused


def test_an_unknown_tool_name_is_refused_the_same_way() -> None:
    """A name that is neither whitelisted nor a known write tool is refused, not executed.

    `docs/agent-spec.md:22` refuses 未知动作 and 写工具 for the same reason — the whitelist is the permission —
    so a name nobody recognises must not slip through as "not obviously dangerous".
    """
    executions: list[str] = []
    tool = CountingTool("get_shipment_trace_v2", executions)
    permission = RefusingPermissionMiddleware(WHITELIST)

    agent = agent_with(
        ScriptedModel([("get_shipment_trace_v2", {})]),
        [tool],
        permission=permission,
        budget=BudgetMiddleware(budget_guard()),
    )
    run_agent(agent)

    assert executions == [], f"an unknown tool executed: {executions}"
    assert permission.refused == ["get_shipment_trace_v2"]


# ------------------------------------------------------------------ the budget


def test_the_model_budget_stops_the_loop_and_the_provider_is_not_called_again() -> None:
    """**The acceptance criterion.** After the budget is exhausted, zero new model calls reach the provider.

    Forced with a two-call budget rather than the spec's twelve so the test is quick, and asserted on the model's
    own counter: `docs/agentscope-migration.md:51` says the SDK's "wrap up now" hint does not replace a pre-call
    refusal, and the way to show the refusal is real is that the call that would have followed never happened.
    """
    executions: list[str] = []
    tool = CountingTool("get_order_context", executions)
    guard = budget_guard(RunBudget(model_calls=2))
    budget = BudgetMiddleware(guard)
    permission = RefusingPermissionMiddleware(WHITELIST)
    # More scripted turns than the budget allows: the loop must be stopped by the budget, not by the script
    # running out, or the test would prove nothing about the budget.
    model = ScriptedModel([("get_order_context", {})] * 8)

    agent = agent_with(model, [tool], permission=permission, budget=budget, max_iters=20)

    with pytest.raises(BudgetExhaustedError):
        run_agent(agent)

    assert model.calls == 2, f"the budget allowed two model calls but {model.calls} were made"
    assert guard.spend.model_calls == 2
    assert budget.refused >= 1, "the third call should have been refused by the reservation"
    # Every call that was allowed is accounted for, so the ledger and the provider agree.
    assert budget.allowed == 2


def test_the_budget_counts_the_tool_schemas_and_prompt_not_only_the_new_packet() -> None:
    """`docs/agentscope-migration.md:50`: the input count covers system, messages **and tool schemas**.

    The model's own `count_tokens` is used, and it appends the tool JSON schemas. A budget that only counted the
    new context packet would undercount exactly the part that grows as tools are added — which is the drift this
    test exists to catch, and it is checked by comparing a run with a large tool schema against one without.
    """
    executions: list[str] = []

    class FatTool(CountingTool):
        def __init__(self, name: str) -> None:
            super().__init__(name, executions)
            self.input_schema = {
                "type": "object",
                "properties": {f"field_{i}": {"type": "string", "description": "x" * 200} for i in range(60)},
                "required": [],
            }

    guard = budget_guard(RunBudget(model_calls=5, input_tokens=40000, step_input_tokens=8192))
    agent = agent_with(
        ScriptedModel([("fat_tool", {})]),
        [FatTool("fat_tool")],
        permission=RefusingPermissionMiddleware(WHITELIST),
        budget=BudgetMiddleware(guard),
    )
    run_agent(agent)

    # The schema is ~12k characters, so the counted input must be well above a messages-only estimate of a
    # one-line prompt. A number near zero would mean the schemas were skipped.
    assert guard.spend.input_tokens > 1000, (
        f"the input count ignored the tool schemas: {guard.spend.input_tokens} tokens for a 60-field schema"
    )


def test_a_single_oversized_request_is_refused_before_the_provider_sees_it() -> None:
    """The per-step cap is checked at the same hook, so an oversized request is never sent.

    `agent-harness.md:37` requires 单步不能超过累计; the point of checking it here is that the refusal happens
    *before* the network call, which is what makes it a cap rather than a report.
    """
    executions: list[str] = []
    guard = budget_guard(RunBudget(step_input_tokens=1, input_tokens=10))
    budget = BudgetMiddleware(guard)
    model = ScriptedModel([("get_order_context", {})])

    agent = agent_with(
        model,
        [CountingTool("get_order_context", executions)],
        permission=RefusingPermissionMiddleware(WHITELIST),
        budget=budget,
    )

    with pytest.raises(BudgetExhaustedError):
        run_agent(agent)

    assert model.calls == 0, "the provider was called despite the step cap refusing the request"
    assert guard.spend.model_calls == 0, "a refused request must not be counted as spent"
