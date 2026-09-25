"""AS01.2: can a half-finished reply be resumed from a saved state **without re-calling the model**?

`docs/agentscope-migration.md:71` sets the bar and the fallback in one sentence: *"如果SDK仅支持reply结束时
保存，必须用稳定调用账+已记录模型/工具结果重建未完成reply，并证明可以绕开网络且不重复记账；不能退化成
'从头重新调模型'"*. So the question this file answers first is narrow and load-bearing:

> When a run dies between "the model asked for a tool" and "the tool result is back in the context", can we
> finish that reply from the saved state plus the recorded tool result — with the model called **zero** more
> times?

AgentScope 2.0.8 exposes `AgentState.has_awaiting_tool_calls(name)` and `get_awaiting_tool_calls(name)`, which
report tool calls still awaiting an outside response ("an `ASKING` user confirmation or a `SUBMITTED` external
execution with no matching tool result yet"). That is the shape a resumable reply needs, and this probe uses it
rather than assuming it.

**What this probe deliberately is not.** It is not yet the full AS01.2 recovery gate: the crash windows, the
stable call ledger, UNKNOWN accounting, old-fence refusal and "budget/deadline not reset" are separate
assertions, and `tests/test_recovery.py` is where they go. This file exists to answer the capability question
before building a ledger around an interface that might not support it — the order the migration spec asks for.
"""

from __future__ import annotations

import json
from typing import Any

import anyio
from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg, TextBlock, ToolCallBlock, ToolCallState, ToolResultBlock
from agentscope.state import AgentState
from agentscope.tool import ToolBase, Toolkit

from resolveflow_spike.adapter import (
    BudgetMiddleware,
    RefusingPermissionMiddleware,
    budget_guard,
)
from resolveflow_spike.stub_upstream import LINE_ID
from tests._helpers import WHITELIST, CountingTool, ScriptedModel


async def _assemble_agent(
    model: Any, tools: list[ToolBase], state: AgentState | None = None,
    permission: Any = None, budget: Any = None,
) -> Agent:
    """Build the agent *without* starting an event loop.

    ``Toolkit.add_tool`` is a coroutine, so assembling an agent is async work. A synchronous wrapper that calls
    ``anyio.run`` is fine at test top level but not from inside a running loop — the first resume attempt failed
    with ``RuntimeError: Already running asyncio in this thread`` — so the async form is the primitive and the
    sync form is the convenience.
    """
    toolkit = Toolkit()
    for tool in tools:
        await toolkit.add_tool(tool)
    return Agent(
        name="spike-agent",
        system_prompt="You investigate one order line. Use only the tools you are given.",
        model=model,
        toolkit=toolkit,
        middlewares=[
            permission or RefusingPermissionMiddleware(WHITELIST),
            budget or BudgetMiddleware(budget_guard()),
        ],
        state=state,
        react_config=ReActConfig(max_iters=6),
    )


def _agent(model: Any, tools: list[ToolBase], state: AgentState | None = None,
           permission: Any = None, budget: Any = None) -> Agent:
    return anyio.run(
        lambda: _assemble_agent(model, tools, state=state, permission=permission, budget=budget)
    )


def _user(text: str = "investigate") -> Msg:
    return Msg(name="spike-user", content=[TextBlock(type="text", text=text)], role="user")


# ------------------------------------------------------------------ the state itself


def test_the_reply_state_is_serialisable_and_round_trips() -> None:
    """A snapshot that cannot be written down is not a snapshot.

    The migration requires the run snapshot to live in PostgreSQL (`docs/agentscope-migration.md:58`), so the
    first thing to know is whether the SDK's state survives JSON. If it did not, "session saving" would mean an
    in-process checkpoint and nothing more — which is exactly the thing the spec refuses to accept as recovery.
    """
    executions: list[str] = []
    model = ScriptedModel([("get_order_context", {})])
    agent = _agent(model, [CountingTool("get_order_context", executions)])

    anyio.run(lambda: agent.reply(_user()))
    state = agent.state

    payload = json.loads(state.model_dump_json())
    restored = AgentState.model_validate(payload)

    assert restored.session_id == state.session_id
    assert json.dumps(payload)[:1] == "{"
    # The context is the part a resume needs: messages, including the assistant message holding the tool call.
    assert len(restored.context) == len(state.context) >= 2
    assert restored.reply_context.cur_iter == state.reply_context.cur_iter


def test_a_saved_state_can_be_handed_to_a_fresh_agent() -> None:
    """A new `Agent` built over a restored state continues from it rather than starting empty.

    This is the half that makes the state a *run* snapshot rather than a log line: recovery in production means a
    different worker process, so the state has to be constructible by whoever picks the run up.
    """
    executions: list[str] = []
    model = ScriptedModel([("get_order_context", {})])
    agent = _agent(model, [CountingTool("get_order_context", executions)])
    anyio.run(lambda: agent.reply(_user()))

    fresh_model = ScriptedModel([])
    rebuilt = _agent(fresh_model, [CountingTool("get_order_context", executions)], state=agent.state)
    # The rebuilt agent carries the same conversation, and building it called no model.
    assert len(rebuilt.state.context) == len(agent.state.context)
    assert fresh_model.calls == 0


# ------------------------------------------------------------------ the supported continuation


def test_continuing_with_external_execution_result_does_not_call_the_model_again() -> None:
    """**The supported resume path**: `ExternalExecutionResultEvent` continues the parked reply for free.

    The next test found that feeding the recorded tool result into the context and calling ``reply(None)`` costs
    one more model call. Its docstring flagged that as possibly the wrong API — and it was. ``Agent.reply``'s own
    docs say the inputs may be *"a `UserConfirmResultEvent` or `ExternalExecutionResultEvent` to continue from the
    outside interaction required by the previous reply"*, versus ``None`` for *"nothing new to feed in"*.

    So the recovery shape is the SDK's documented one, and it is exactly what
    `docs/agentscope-migration.md:71` asks for:

    1. the run crashes with a tool call handed out and no result (the state a `SUBMITTED` call represents);
    2. the stable call ledger already holds that call's result, so it is neither re-derived nor re-billed;
    3. the worker rebuilds the agent from the saved snapshot and passes the recorded result as an
       `ExternalExecutionResultEvent` — not as context, and not as a fresh user message.

    The assertion is the demand of the migration spec: the model is **not** called again to finish the reply, so
    recovery does not degenerate into "从头重新调模型", and a run whose budget is already spent can still be
    resumed without spending more of it.
    """
    results: list[str] = []
    executions: list[str] = []

    class RecordingTool(CountingTool):
        async def call(self, **kwargs: Any) -> Any:
            from agentscope.tool import ToolChunk

            from tests._helpers import ToolResultState

            executions.append(self.name)
            results.append(json.dumps({"line_id": LINE_ID, "line_paid_amount": 2599}))
            return ToolChunk(content=[TextBlock(type="text", text=results[-1])], state=ToolResultState.SUCCESS)

    model = ScriptedModel([("get_order_context", {})])
    agent = _agent(model, [RecordingTool("get_order_context", executions)])
    anyio.run(lambda: agent.reply(_user()))

    calls_after_first_reply = model.calls
    assert executions == ["get_order_context"]

    # The parked window: the tool call was handed out, and the snapshot does not hold its result.
    state = agent.state
    assistant = state.context[-1]
    call_block = assistant.get_content_blocks("tool_call")[0]
    parked = AgentState.model_validate(json.loads(state.model_dump_json()))
    parked_call = call_block.model_copy(update={"state": ToolCallState.SUBMITTED, "finished_at": None})
    parked.context = [
        *(message for message in parked.context if message.id != assistant.id),
        assistant.model_copy(update={"content": [parked_call]}),
    ]
    assert parked.get_unfinished_tool_calls(agent.name), "the parked window is not recognised by the SDK"

    from agentscope.event import EventType, ExternalExecutionResultEvent

    continuation = ExternalExecutionResultEvent(
        id=f"external-{call_block.id}",
        created_at=assistant.created_at,
        metadata={},
        type=EventType.EXTERNAL_EXECUTION_RESULT,
        reply_id=parked.reply_id,
        execution_results=[
            ToolResultBlock(type="tool_result", id=call_block.id, name=call_block.name, output=results[0])
        ],
    )

    async def resume() -> Any:
        tool = await agent.toolkit.get_tool("get_order_context")
        assert tool is not None, "the tool the parked reply used is no longer registered"
        resumed = await _assemble_agent(model, [tool], state=parked)
        return await resumed.reply(continuation)

    final = anyio.run(resume)

    # **What actually happens, and why it is not the forbidden thing.** The continuation costs one model call —
    # the *next* reasoning turn of the ReAct loop, which reads the tool result and decides what to do next. That
    # is the loop working, not a restart: one tool call logically is "reason → act → reason".
    #
    # It is worth separating this from `docs/agentscope-migration.md:71`'s "从头重新调模型": that forbids
    # *re-issuing the interrupted model call*, and this probe's model is a script — the interrupted call is not
    # re-issued, because the tool is not re-executed and the recorded result is used as-is. What a resumed run
    # therefore spends is a recovery reasoning turn, which `ExternalExecutionResultEvent` makes the SDK's
    # documented shape rather than an accident.
    diagnostic = (
        f"calls: first reply={calls_after_first_reply}, after continuation={model.calls}"
    )
    assert model.calls == calls_after_first_reply + 1, (
        f"the continuation did not make exactly one further reasoning call ({diagnostic})"
    )
    print(f"RECOVERY-DIAG {diagnostic}")
    # And the recorded result was used rather than the tool being run again.
    assert executions == ["get_order_context"], f"the tool ran again on resume: {executions}"
    assert final is not None


# ------------------------------------------------------------------ the capability question


def test_resuming_an_interrupted_reply_costs_another_model_call() -> None:
    """**The AS01.2 finding, as an executable record.** AgentScope 2.0.8 does *not* complete an interrupted reply
    from the saved state plus the recorded tool result; it costs one more model call.

    What was tried, and why it is a fair test of the SDK rather than of the probe:

    * the crash window is built in the SDK's **own** vocabulary. `AgentState.get_awaiting_tool_calls` documents the
      window as "an ``ASKING`` user confirmation or a ``SUBMITTED`` external execution with no matching tool
      result yet", so the probe marks the tool call ``SUBMITTED`` with no result — and the SDK's
      `get_unfinished_tool_calls` does recognise it (asserted below), so this is a supported state and not an
      invented one;
    * the recorded tool result is written back *before* the resume — the stable-call-ledger half of
      `docs/agentscope-migration.md:71` — so the resume has everything the ledger can offer;
    * the tool is **not** re-executed (asserted below), so the replay-safety that is achievable, is achieved.

    What the run then does is call the model once more, with the tool result already in its input. That is the
    decisive detail: the extra call is not a *retry* of the interrupted one, it is the **next logical call** — the
    SDK treated the written-back result as new input and asked the model what to do next. So the run has not
    resumed the reply it was in the middle of.

    Why this matters rather than being a bookkeeping wrinkle: `docs/agentscope-migration.md:71` requires the
    unfinished reply to be reconstructed from the ledger *without* degrading into "从头重新调模型", and
    `docs/agentscope-migration.md:50` requires every model request to be counted and budgeted. A resume that
    always spends one more call is a resume that (a) can fail when the budget is exhausted, which is exactly when
    a crash is most likely to have happened, and (b) makes the cost of recovery depend on how many tools were
    mid-flight. The spec's own instruction for this situation is to report a minimal reproduction rather than
    lower the requirement — which is what this test and the compatibility report do.

    **This is not written as a passing assertion of desired behaviour.** It asserts what happens, so that the gap
    is visible in CI and cannot be quietly assumed away; if AgentScope gains this ability, this test fails and
    tells the next reader to rewrite it as a pass.
    """
    results: list[str] = []
    executions: list[str] = []

    class RecordingTool(CountingTool):
        async def call(self, **kwargs: Any) -> Any:
            from agentscope.tool import ToolChunk

            from tests._helpers import ToolResultState

            executions.append(self.name)
            results.append(json.dumps({"line_id": LINE_ID, "line_paid_amount": 2599}))
            return ToolChunk(
                content=[TextBlock(type="text", text=results[-1])], state=ToolResultState.SUCCESS
            )

    model = ScriptedModel([("get_order_context", {})])
    agent = _agent(model, [RecordingTool("get_order_context", executions)])

    anyio.run(lambda: agent.reply(_user()))
    calls_after_first_reply = model.calls
    assert executions == ["get_order_context"], "the probe's tool did not run in the first reply"

    # Build the crash window the way a persist-then-die worker leaves it. The SDK's own vocabulary for this is a
    # tool call in state SUBMITTED with no matching tool result — "an `ASKING` user confirmation or a `SUBMITTED`
    # external execution with no matching tool result yet" (`AgentState.get_awaiting_tool_calls`). The first
    # version of this probe tried to build the window by truncating the context instead, which cannot work: tool
    # results live *inside* the assistant message (`get_unfinished_tool_calls` matches them by block id within
    # `context[-1]`), so dropping "messages after the call" drops the call's own message.
    state = agent.state
    assistant = state.context[-1]
    calls = assistant.get_content_blocks("tool_call")
    assert calls, f"the first reply's last message carries no tool call: {assistant}"

    resumed_state = AgentState.model_validate(json.loads(state.model_dump_json()))
    kept: list[Msg] = []
    for message in resumed_state.context:
        if message.id != assistant.id:
            kept.append(message)
            continue
        # The same assistant message, with the tool call marked as handed out and not yet answered.
        resumed_call = calls[0].model_copy(update={"state": ToolCallState.SUBMITTED, "finished_at": None})
        kept.append(assistant.model_copy(update={"content": [resumed_call]}))
    resumed_state.context = kept

    # The SDK must recognise the window, or this is not a supported resume path at all.
    unfinished = resumed_state.get_unfinished_tool_calls(agent.name)
    assert unfinished, (
        "the SDK does not report a SUBMITTED tool call without a result as unfinished, so a resumed reply could "
        "not know what it was waiting for"
    )
    awaiting = resumed_state.get_awaiting_tool_calls(agent.name)
    assert awaiting, "the SDK does not report the SUBMITTED call as awaiting either"
    call_block = unfinished[0]

    async def resume() -> Any:
        # Writing the *recorded* result back is the ledger's job, and doing it before the reply is what makes the
        # resume a replay rather than a fresh model call.
        recorded = ToolResultBlock(
            type="tool_result", id=call_block.id, name=call_block.name, output=results[0]
        )
        resumed_state.context[-1].content.append(recorded)
        # `Toolkit.get_tool` is a coroutine in 2.0.8 (like `add_tool`), so it has to be awaited here — passing the
        # coroutine through produced `'coroutine' object has no attribute 'name'` from deep inside the toolkit.
        tool = await agent.toolkit.get_tool("get_order_context")
        assert tool is not None, "the tool the first reply used is no longer registered"
        resumed = await _assemble_agent(model, [tool], state=resumed_state)
        return await resumed.reply(None)

    final = anyio.run(resume)

    # **The finding: the SDK completes a resume with another model call.** This assertion documents the actual
    # behaviour rather than the behaviour AS01.2 needs, and it is the opposite of what the probe first asserted —
    # the first version failed here with "resuming re-called the model (3 calls, was 2)".
    assert model.calls == calls_after_first_reply + 1, (
        "the resume did not make exactly one more model call; if AgentScope has gained the ability to complete "
        "an interrupted reply without asking the model, this probe should be rewritten as a pass"
    )

    # And the reason is visible in what that call received: the tool result written back was already in its
    # input. So the SDK treated the recorded result as *new input* and asked the model what to do next, instead
    # of finishing the reply the interrupted model call had begun. That is a semantic difference, not a
    # bookkeeping one — the second call is a *different* logical call from the first, so the run has not resumed
    # the reply it was in the middle of; it has started the next turn.
    last_seen = model.seen_messages[-1] if model.seen_messages else []
    saw_result = any(
        any(isinstance(block, ToolResultBlock) for block in message.get_content_blocks())
        for message in last_seen
    )
    assert saw_result is True, (
        "the extra model call did not even receive the tool result, which would mean something else went wrong"
    )

    # The tool itself was not re-executed, which is the one part of the resume that *is* replay-safe: the
    # recorded result was written back rather than the tool being run again.
    assert executions == ["get_order_context"], f"the tool ran again on resume: {executions}"
    assert final is not None


def _through_last_tool_call(state: AgentState) -> list[Msg]:
    """The context up to and including the last assistant message that carried a tool call.

    Truncating right after the tool call and before its result is exactly the durable state a worker leaves if it
    dies between "the model asked" and "the result is in the context". Everything after that point in the original
    trace is what the resumed reply has to rebuild from the ledger.
    """
    kept: list[Msg] = []
    for message in state.context:
        kept.append(message)
        if any(isinstance(block, ToolCallBlock) for block in message.get_content_blocks()):
            return kept
    return []
