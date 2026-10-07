"""Evaluation-only fixed investigator using the production context, gates and read bridges."""

import anyio
from resolveflow.harness.actions import SEARCH_POLICY, TERMINAL_KINDS
from resolveflow.harness.facts import FactsView
from resolveflow.harness.local_reads import PolicySearchBridge
from resolveflow.harness.observation_read import ObservationStore
from resolveflow.harness.sdk_adapter import AgentScopeModelAdapter
from resolveflow.harness.sdk_runner import (
    ActionGateMiddleware,
    McpToolBridge,
    _BudgetHook,
    _GateAwareClient,
    _outcome,
)


def run_fixed(runner):
    return anyio.run(_drive_fixed, runner)


async def _drive_fixed(runner):
    gate = ActionGateMiddleware()
    guard = _BudgetHook(runner, gate)
    client = _GateAwareClient(runner, gate, guard)
    guard.attach_client(client)
    runner.last_client = client
    store = ObservationStore(run_id=runner.facts.run_id)
    store.bind_materials(
        runner.facts.review_context or {},
        case_id=runner.facts.case_id,
        input_revision=runner.facts.input_revision,
    )
    client.bind_context(
        view=FactsView(), store=store, guard=guard, system=runner.system
    )
    adapter = AgentScopeModelAdapter(client, system=runner.system)

    async def read(name, arguments):
        decision = gate.check(
            {"kind": "READ_TOOL", "tool_name": name, "arguments": arguments}
        )
        if decision is None:
            return
        client.note_confirmed_action(decision)
        bridge = McpToolBridge(
            name, runner.tools, runner.facts, gate, adapter, client, guard
        )
        await bridge.call(**arguments)

    for name in ("get_order_context", "get_shipment_trace", "get_case_evidence"):
        await read(name, {})
        if name == "get_shipment_trace":
            while not gate.stop_reason:
                last = client.observations[-1] if client.observations else None
                cursor = (
                    (last.result or {}).get("next_cursor")
                    if last and last.error is None
                    else None
                )
                if not cursor:
                    break
                await read(name, {"cursor": cursor})
        if gate.stop_reason:
            return _outcome(gate.stop_reason, gate, adapter, guard, completed=False)

    def ask():
        # Fixed reads never consume a model request. Only actual provider requests reserve the budget.
        client.begin_turn()
        packet = client.prepare_packet([])
        guard.output_ceiling = guard.guard.reserve_model_request(
            input_tokens=packet.input_tokens
        )
        reply = client.decide(system=runner.system, messages=[])
        adapter.replies.append(reply)
        adapter.modes.append(reply.mode)
        adapter.trajectory.append(
            {"action": reply.decision.get("kind"), "outcome": "MODEL_REPLY"}
        )
        return reply

    gate.notices.append(
        "固定调查流程：订单、物流、材料已按固定顺序读取。当前阶段只生成SEARCH_POLICY查询，top_k=3；不要追加其他调查动作。"
    )
    ask()
    if gate.accepted is None or gate.accepted.get("kind") != SEARCH_POLICY:
        gate.note_stop("FIXED_QUERY_INVALID")
        return _outcome(gate.stop_reason, gate, adapter, guard, completed=False)
    decision = gate.accepted
    runner.index_generation()
    bridge = PolicySearchBridge(
        runner.policy_index,
        runner.facts,
        gate,
        adapter,
        client,
        guard,
        embedder=runner.policy_embedder,
        generation_ids=runner._selected_policy_generations,
    )
    await bridge.call(query=decision["query"], **decision.get("arguments", {}))
    gate.notices.append(
        "固定调查流程：调查与政策检索完成。当前阶段只输出PROPOSE、ASK_CUSTOMER或ESCALATE终局；依据现有事实和政策明确客户补证或商家核查责任，不追加读取。"
    )
    for _ in range(2):
        if gate.stop_reason:
            break
        ask()
        if gate.terminal is not None:
            return _outcome("COMPLETED", gate, adapter, guard, completed=True)
        if gate.accepted and gate.accepted.get("kind") not in TERMINAL_KINDS:
            gate._refuse(
                "FIXED_TERMINAL_REQUIRED",
                "调查已结束，请基于已读事实形成终局，不追加调查",
            )
        gate.repair_message = None
    gate.note_stop(gate.stop_reason or "FIXED_TERMINAL_INVALID")
    return _outcome(gate.stop_reason, gate, adapter, guard, completed=False)
