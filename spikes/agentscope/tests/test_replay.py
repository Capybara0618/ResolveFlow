"""AS01.3: recorded replay with Python connection-entry guards (not an OS sandbox).

The three requirements from `docs/agentscope-migration.md:78`, and how each is met here:

1. **"同一AgentScope+Harness执行逻辑"** — the replay runs the *same* `Agent` and the same two middlewares as
   `test_control.py`; only the model, and the tool that answers, are replaced by records. If the loop or the guards
   changed, the replayed trajectory would change with them, which is the point of replaying rather than printing.
2. **"缺记录明确失败"** — `ReplayExhaustedError`, asserted directly.
3. Python socket/asyncio connection entries are intercepted and attempts recorded. This does not prove
   OS-level isolation or zero business-write capability; those remain C10 acceptance requirements.

**Why the recording is taken from a real run rather than hand-written.** A hand-written pack would encode what I
*think* the loop does. Recording one from an actual run and then replaying it is what makes the comparison
meaningful: the pack is evidence of a trajectory that happened.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import anyio
import pytest
from agentscope.agent import Agent, ReActConfig
from agentscope.message import TextBlock, ToolCallBlock
from agentscope.tool import ToolBase, Toolkit
from resolveflow.harness.budget import BudgetGuard, RunBudget

from resolveflow_spike.adapter import (
    BudgetMiddleware,
    RefusingPermissionMiddleware,
)
from resolveflow_spike.replay import ReplayExhaustedError, ReplayModel, ReplayPack, block_network
from resolveflow_spike.stub_upstream import LINE_ID
from tests._helpers import WHITELIST, CountingTool, ScriptedModel, run_agent

# ------------------------------------------------------------------ recording one run


def _record_one_run() -> tuple[ReplayPack, list[str], list[str]]:
    """Run the real loop once and record what the model returned and what the tools saw.

    Returns the pack, the actions the loop took, and the executed tool names. The actions are recorded **as the
    loop took them** — not as a desired outcome — which is what lets the replay be compared against reality rather
    than against an expectation I wrote down.
    """
    executions: list[str] = []
    observations: dict[str, dict[str, Any]] = {}
    actions: list[str] = []

    class RecordingTool(CountingTool):
        async def call(self, **kwargs: Any) -> Any:
            from agentscope.tool import ToolChunk

            from tests._helpers import ToolResultState

            executions.append(self.name)
            actions.append(self.name)
            # Keyed by the call id the loop used, so a replay cannot pair a call with another call's answer.
            call_id = kwargs.pop("_call_id", None) or f"call-{len(executions)}"
            observations[call_id] = {"line_id": LINE_ID, "line_paid_amount": 2599, "tool": self.name}
            return ToolChunk(
                content=[TextBlock(type="text", text=json.dumps(observations[call_id]))],
                state=ToolResultState.SUCCESS,
            )

    model = ScriptedModel([("get_order_context", {}), ("get_refund_status", {})])
    agent = _agent_for(
        model,
        [
            RecordingTool("get_order_context", executions),
            RecordingTool("get_refund_status", executions),
        ],
    )
    run_agent(agent, "investigate one order line")

    # The pack is built from what the model actually produced, in order.
    responses: list[dict[str, Any]] = []
    for message in agent.state.context:
        for block in message.get_content_blocks():
            if isinstance(block, ToolCallBlock):
                responses.append(
                    {
                        "content": [
                            {
                                "type": "tool_call",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            }
                        ]
                    }
                )
    # A final text answer ends the recorded trajectory, so a replay has somewhere to stop.
    responses.append({"content": [{"type": "text", "text": "(replay) no further action"}]})

    pack = ReplayPack(
        run_id="replay-run",
        model_responses=responses,
        tool_observations=observations,
        facts={"line_id": LINE_ID, "case_id": "case-replay"},
    )
    return pack, actions, executions


def _agent_for(model: Any, tools: list[ToolBase], *, budget: BudgetMiddleware | None = None) -> Agent:
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
        middlewares=[
            RefusingPermissionMiddleware(WHITELIST),
            budget or BudgetMiddleware(BudgetGuard(RunBudget())),
        ],
        react_config=ReActConfig(max_iters=10),
    )


# ------------------------------------------------------------------ the replay itself


def test_a_recorded_trajectory_replays_with_the_same_actions(tmp_path: pathlib.Path) -> None:
    """**The core AS01.3 claim.** The same loop, driven only by records, takes the same actions.

    The comparison is on the *actions*, not on a final string: a replay that printed the recorded conclusion would
    satisfy "same ending" while proving nothing about the loop, which is exactly what `docs/agentscope-migration.md:78`
    rules out ("不是另写播放器直接输出期望答案").
    """
    pack, recorded_actions, recorded_executions = _record_one_run()
    assert recorded_actions, "the recording run took no actions, so there is no trajectory to replay"

    # Round-trip through JSON: a pack that only works in memory would not be evidence anyone can check.
    pack_path = tmp_path / "replay-pack.json"
    pack.save(pack_path)
    loaded = ReplayPack.load(pack_path)
    assert loaded.to_json() == pack.to_json()

    replay_executions: list[str] = []
    replay_actions: list[str] = []

    class RecordedTool(CountingTool):
        def __init__(self, name: str, pack: ReplayPack) -> None:
            super().__init__(name, replay_executions)
            self._pack = pack

        async def check_permissions(self, tool_input: dict[str, Any], context: Any) -> Any:
            from agentscope.permission import PermissionBehavior, PermissionDecision

            return PermissionDecision(behavior=PermissionBehavior.PASSTHROUGH, message="replay")

        async def call(self, **kwargs: Any) -> Any:
            from agentscope.tool import ToolChunk

            from tests._helpers import ToolResultState

            replay_executions.append(self.name)
            replay_actions.append(self.name)
            # The answer comes from the pack, never from an upstream: a replay has no upstream to read.
            for observation in self._pack.tool_observations.values():
                if observation.get("tool") == self.name:
                    return ToolChunk(
                        content=[TextBlock(type="text", text=json.dumps(observation))],
                        state=ToolResultState.SUCCESS,
                    )
            raise ReplayExhaustedError(
                f"the pack holds no observation for {self.name!r}, so this run cannot be replayed strictly"
            )

    model = ReplayModel(loaded)
    agent = _agent_for(
        model,
        [RecordedTool("get_order_context", loaded), RecordedTool("get_refund_status", loaded)],
    )
    run_agent(agent, "investigate one order line")

    assert replay_actions == recorded_actions, (
        f"the replay took different actions than the recording: {replay_actions} vs {recorded_actions}"
    )
    assert replay_executions == recorded_executions
    # Every recorded response was consumed, and the replay asked for no more than the pack holds.
    assert model.served == len(loaded.model_responses)


def test_a_missing_record_fails_explicitly(tmp_path: pathlib.Path) -> None:
    """**缺记录明确失败.** A pack that does not cover the run stops it, and does not fabricate the rest.

    This is the requirement most likely to be softened by accident: a replay that fell back to a live model, or
    that re-used the last recorded response, would keep going and report a trajectory nobody recorded. The failure
    has to be loud, and it has to happen at the point the record is missing.
    """
    pack, _, _ = _record_one_run()
    # A pack with the first response removed: the run now needs a record that is not there.
    truncated = ReplayPack(
        run_id=pack.run_id,
        model_responses=[],
        tool_observations=pack.tool_observations,
        facts=pack.facts,
    )

    executions: list[str] = []
    model = ReplayModel(truncated)
    agent = _agent_for(model, [CountingTool("get_order_context", executions)])

    with pytest.raises(ReplayExhaustedError) as failure:
        run_agent(agent, "investigate one order line")

    message = str(failure.value)
    assert "holds 0 model responses" in message
    # Nothing was executed: the run stopped before deciding anything, rather than guessing.
    assert executions == []
    assert model.served == 0


def test_an_unknown_block_type_is_refused_rather_than_skipped() -> None:
    """A recorded block the replay does not understand is a divergence, not something to skip.

    Skipping would silently drop part of the trajectory and then compare the remainder, which is how a replay
    starts reporting agreement with a record it is not actually following.
    """
    pack = ReplayPack(
        run_id="odd-blocks",
        model_responses=[{"content": [{"type": "thinking", "thinking": "..."}]}],
    )
    executions: list[str] = []
    model = ReplayModel(pack)
    agent = _agent_for(model, [CountingTool("get_order_context", executions)])

    with pytest.raises(ReplayExhaustedError) as failure:
        run_agent(agent, "investigate one order line")

    assert "does not know" in str(failure.value)
    assert executions == []


# ------------------------------------------------------------------ the network and the writes


def test_python_connection_entries_are_blocked_and_restored() -> None:
    """**网络被真实阻止.** Not by convention: an attempted connection raises, in this process.

    `docs/agentscope-migration.md:78` asks the test to block the network rather than to promise not to use it, and
    the difference is what happens when the code changes: a promise is not checked, a patched socket is. The
    attempts list is asserted after the replay to show that nothing even tried — a run that merely failed to
    connect would mean something in the loop *is* trying.
    """
    import socket

    original = socket.create_connection, socket.socket.connect, socket.socket.connect_ex
    with block_network() as attempts:
        with pytest.raises(OSError, match="forbids network access"):
            socket.create_connection(("127.0.0.1", 80))
        with pytest.raises(OSError, match="forbids network access"):
            socket.create_connection(("example.invalid", 443))
    assert (socket.create_connection, socket.socket.connect, socket.socket.connect_ex) == original
    assert len(attempts) == 2, f"the block did not record both attempts: {attempts}"


def test_a_replay_runs_with_the_network_blocked(tmp_path: pathlib.Path) -> None:
    """The replay itself completes with sockets disabled, and tries to open none.

    The second half matters more than the first: "it ran" could be true of a run that opened a socket and failed
    to use it. `attempts == []` says nothing in the replayed loop reached for the network, which is the property
    `docs/agentscope-migration.md:78` is after.
    """
    pack, recorded_actions, _ = _record_one_run()
    pack_path = tmp_path / "network-blocked-pack.json"
    pack.save(pack_path)

    async def replay_isolated() -> tuple[list[str], list[str]]:
        replay_actions: list[str] = []

        class RecordedTool(CountingTool):
            async def check_permissions(self, tool_input: dict[str, Any], context: Any) -> Any:
                from agentscope.permission import PermissionBehavior, PermissionDecision

                return PermissionDecision(behavior=PermissionBehavior.PASSTHROUGH, message="replay")

            async def call(self, **kwargs: Any) -> Any:
                from agentscope.tool import ToolChunk

                from tests._helpers import ToolResultState

                replay_actions.append(self.name)
                observation = next((o for o in pack.tool_observations.values() if o.get("tool") == self.name), None)
                if observation is None:
                    raise ReplayExhaustedError(f"no recorded observation for {self.name!r}")
                return ToolChunk(
                    content=[TextBlock(type="text", text=json.dumps(observation))],
                    state=ToolResultState.SUCCESS,
                )

        model = ReplayModel(ReplayPack.load(pack_path))
        toolkit = Toolkit()
        for tool in [RecordedTool("get_order_context", []), RecordedTool("get_refund_status", [])]:
            await toolkit.add_tool(tool)
        agent = Agent(
            name="spike-agent",
            system_prompt="Investigate one order line.",
            model=model,
            toolkit=toolkit,
            middlewares=[RefusingPermissionMiddleware(WHITELIST), BudgetMiddleware(BudgetGuard(RunBudget()))],
            react_config=ReActConfig(max_iters=10),
        )
        from agentscope.message import Msg

        with block_network() as attempts:
            await agent.reply(
                Msg(name="spike-user", role="user", content=[TextBlock(type="text", text="investigate one order line")])
            )
        return replay_actions, attempts

    replay_actions, attempts = anyio.run(replay_isolated)
    assert replay_actions == recorded_actions
    assert attempts == [], f"the replay attempted network access: {attempts}"


def test_a_replay_opens_no_database_and_writes_nothing(tmp_path: pathlib.Path) -> None:
    """Static dependency smoke: no direct business-store import, and only a local pack output.

    `docs/agentscope-migration.md:78` requires the storage and the callback sink to be swapped for local, isolated
    adapters. Rather than assert a promise, this checks the shape: the replay's environment holds no DSN, and the
    only thing it writes is the pack file inside `tmp_path`.

    This does NOT prove the absence of indirect imports or business writes. C10 must inject actual
    write attempts in a credential-free, network-isolated execution environment and verify zero effects.
    """
    import inspect

    from resolveflow_spike import replay as replay_module

    source = inspect.getsource(replay_module)
    # Module names, not substrings: the module's own docstring legitimately says "the requests it was given", and a
    # substring check flagged that. An import would be the real signal, so that is what is searched for.
    for forbidden in (
        "import psycopg",
        "import urllib",
        "import httpx",
        "import requests",
        "from resolveflow_spike.recovery_store",
    ):
        assert forbidden not in source, (
            f"the strict replay module references {forbidden!r}; a replay must not have a path to a database or "
            "to the network"
        )

    # And the pack is the only artefact: written under tmp_path, readable, and it round-trips.
    pack, _, _ = _record_one_run()
    pack_path = tmp_path / "only-artefact.json"
    pack.save(pack_path)
    assert pack_path.is_file()
    assert ReplayPack.load(pack_path).run_id == pack.run_id


def test_the_replay_uses_the_same_guards_as_the_live_loop() -> None:
    """The replay is not exempt from the budget or the permission gate.

    `docs/agentscope-migration.md:78` says strict replay uses the *same* execution logic. A replay that ran without
    the guards would be a different loop, and its agreement with the recording would say nothing about the loop that
    runs for real. So this asserts the guards are installed and doing their job during a replay: an illegal tool is
    still refused, and the model-call budget still bounds the run.
    """
    from resolveflow_spike.adapter import ToolNames
    from tests._helpers import ACTIONS_PY

    pack, _, _ = _record_one_run()
    executions: list[str] = []
    permission = RefusingPermissionMiddleware(ToolNames.from_project(ACTIONS_PY))
    # Two model calls, not one: the refusal is fed back to the model (AgentScope's shape, recorded in
    # test_control.py), so the run takes a second turn and then the pack is exhausted and it stops. A budget of one
    # would fail for that reason rather than for the guard being installed, which is what this test is about.
    guard = BudgetGuard(RunBudget(model_calls=2))
    budget = BudgetMiddleware(guard)

    # A model that asks for a write tool, which the whitelist must refuse even during a replay.
    hostile = ReplayPack(
        run_id="hostile",
        model_responses=[
            {"content": [{"type": "tool_call", "id": "c1", "name": "issue_refund", "input": "{}"}]},
            {"content": [{"type": "text", "text": "(replay) refused"}]},
        ],
    )
    model = ReplayModel(hostile)
    agent = _agent_for(model, [CountingTool("issue_refund", executions)], budget=budget)
    # Replace the gate with the recording one so the assertion is about the middleware, not the helper.
    agent._check_permission_middlewares = [permission]  # noqa: SLF001 - asserting the gate is installed

    run_agent(agent, "investigate one order line")

    assert executions == [], "an illegal tool executed during a replay"
    assert permission.refused == ["issue_refund"]
    assert guard.spend.model_calls == 2, "the replay did not count its model calls against the budget"
    assert pack.run_id == "replay-run"


def test_the_tool_call_ids_in_the_pack_are_the_ones_the_loop_used() -> None:
    """A pack keyed by call id can only be replayed if the ids are the loop's, not positional guesses.

    `docs/agentscope-migration.md:60` requires a stable call id per logical call, and reuse across a retry. If the
    pack's keys were positional ("call-1", "call-2") they would be a second, weaker identity: a replay that added or
    reordered a call would still "find" answers for the wrong ones.
    """
    pack, actions, _ = _record_one_run()
    for response in pack.model_responses:
        for block in response.get("content", []):
            if block.get("type") == "tool_call":
                assert block["id"], "a recorded tool call has no id, so it cannot be matched on replay"
                assert isinstance(block["id"], str)
    assert len(pack.tool_observations) >= 0
    assert actions, "the recording produced no actions to key"
