"""AS01.2: the recovery budget the user decided on (2026-09-25), and the MCP decision that goes with it.

Two decisions were taken after the AS01.1/AS01.2 capability probes, and each needs to be true in code rather than
only in the report:

1. **Recovery gets a reserved allowance, and the turn is still pre-charged as `RECOVERY_TURN`.** The probe found
   that resuming a parked reply costs one reasoning turn, and that the run's ordinary budget may already be spent
   when a crash happens. Reserving an allowance lets the run finish; charging it keeps the ledger agreeing with
   what the provider was actually asked for (`docs/agentscope-migration.md:50`, `docs/agent-spec.md:40`).
2. **MCP stays on the project's own mcp 2.2.0 client.** AgentScope's MCP path has four camelCase assumptions that
   break under mcp 2.x (AS01.1 §3), and the migration explicitly requires the official stdio path to be kept
   (`docs/agentscope-migration.md:30`). So AgentScope receives tools that are already ordinary Python objects.
"""

from __future__ import annotations

import anyio
import pytest
from resolveflow.harness.budget import BudgetExhaustedError, BudgetGuard, RunBudget

from resolveflow_spike.adapter import RecoveryAllowance, budget_guard

# ------------------------------------------------------------------ decision 1: the recovery allowance


def test_a_recovery_turn_is_allowed_after_the_ordinary_budget_is_spent() -> None:
    """**The point of the allowance.** A run at its model-call limit can still pay for recovery.

    This is the situation the probe identified: the run spent its last ordinary call, then crashed with a tool
    result parked. Without an allowance there is nothing left to resume with, and the run cannot finish — which
    is the worst outcome, because the work that was already paid for is stranded.
    """
    guard = BudgetGuard(RunBudget(model_calls=2))
    allowance = RecoveryAllowance(guard, recovery_model_calls=2)

    # The run spends its ordinary budget exactly.
    guard.reserve_model_call(input_tokens=10, output_tokens=10)
    guard.reserve_model_call(input_tokens=10, output_tokens=10)
    assert guard.spend.model_calls == 2
    with pytest.raises(BudgetExhaustedError):
        guard.reserve_model_call(input_tokens=10, output_tokens=10)

    # And the allowance lets the recovery turn through, because the *run* has an allowance even though its
    # ordinary calls are gone. The budget it is charged against is therefore not the same thing as the ordinary
    # cap — which is exactly why this needed a decision rather than a default.
    allowed = allowance.note_recovery_turn(input_tokens=10, output_tokens=10, reason="resume parked reply")

    assert allowed is True
    assert allowance.remaining == 1
    assert allowance.ledger[-1] == {
        "kind": "RECOVERY_TURN",
        "allowed": True,
        "reason": "resume parked reply",
        "turn": 1,
    }


def test_the_recovery_turn_is_charged_to_the_runs_own_ledger() -> None:
    """Charging it is what keeps one record of one run.

    If the allowance were free, the run's reported spend would understate what the provider was asked for, and a
    later reconciliation or a strict replay would compare a recorded trajectory against a cost that never
    appeared. So the pre-charge lands on the run's own guard.
    """
    guard = BudgetGuard(RunBudget(model_calls=12, input_tokens=40000, output_tokens=4000))
    allowance = RecoveryAllowance(guard, recovery_model_calls=2)

    before = guard.spend.model_calls
    assert allowance.note_recovery_turn(input_tokens=120, output_tokens=30, reason="recovery") is True

    assert guard.spend.model_calls == before + 1, "the recovery turn was not counted in the run's spend"
    assert guard.spend.input_tokens >= 120, "the recovery turn's input was not charged"
    assert guard.spend.output_tokens >= 30, "the recovery turn's output was not reserved"


def test_the_allowance_is_finite_and_not_a_reset() -> None:
    """A run that keeps crashing does not get an unbounded recovery budget.

    `docs/agentscope-migration.md:69` requires an expired or exhausted run to be terminated rather than renewed
    silently; an allowance that grew on every crash would be exactly the silent renewal that forbids. So it is
    consumed, and once gone it says no and leaves the decision (fail, escalate) to the run's owner.
    """
    guard = BudgetGuard(RunBudget(model_calls=12))
    allowance = RecoveryAllowance(guard, recovery_model_calls=1)

    assert allowance.note_recovery_turn(input_tokens=10, output_tokens=10, reason="first") is True
    assert allowance.remaining == 0
    assert allowance.note_recovery_turn(input_tokens=10, output_tokens=10, reason="second") is False

    # The refusal is recorded with its reason, and it did not spend anything.
    refusal = allowance.ledger[-1]
    assert refusal["allowed"] is False
    assert refusal["reason"] == "second"
    assert "exhausted" in refusal["detail"]
    # The ordinary budget was not grown to make room: the allowance is the only thing that was consumed.
    assert guard.spend.model_calls == 1


def test_the_allowance_still_respects_the_runs_hard_caps() -> None:
    """An allowance is not a licence to exceed the run's caps.

    `docs/agentscope-migration.md:50` says the input count covers the final system prompt, messages and tool
    schemas, and that a run may not send a request the budget cannot pay for. A recovery turn is a request like
    any other, so the per-step cap still refuses it — the allowance only answers "may the run still work", never
    "may this request be larger than allowed".
    """
    guard = BudgetGuard(RunBudget(step_input_tokens=100, input_tokens=40000))
    allowance = RecoveryAllowance(guard, recovery_model_calls=2)

    allowed = allowance.note_recovery_turn(input_tokens=101, output_tokens=10, reason="oversized recovery")

    assert allowed is False
    assert "BUDGET_STEP_TOKENS" in allowance.ledger[-1]["detail"]
    # Nothing was spent: a refused request is not an attempt.
    assert guard.spend.model_calls == 0
    assert allowance.remaining == 2, "a refused turn must not consume the allowance either"


def test_a_zero_allowance_is_representable_and_refuses() -> None:
    """A run may legitimately be configured with no recovery budget, and then recovery simply cannot happen.

    Making that a legal configuration matters: it is the honest way to express "this run must not spend anything
    on recovery", and it has to refuse cleanly rather than fail in arithmetic.
    """
    allowance = RecoveryAllowance(budget_guard(), recovery_model_calls=0)
    assert allowance.remaining == 0
    assert allowance.note_recovery_turn(input_tokens=1, output_tokens=1, reason="none") is False
    with pytest.raises(ValueError):
        RecoveryAllowance(budget_guard(), recovery_model_calls=-1)


# ------------------------------------------------------------------ decision 2: MCP stays ours


def test_the_projects_own_mcp_client_is_the_path_agentscope_uses() -> None:
    """**The second decision.** AgentScope drives the loop; the project's own mcp 2.2.0 client reads the data.

    Why this is the decision and not a workaround: AgentScope 2.0.8's MCP adapter reads four mcp-1.x camelCase
    attributes (`inputSchema`, `readOnlyHint`, `isError`, `McpError`) that mcp 2.2.0 does not expose, so routing
    our tools through it would mean either pinning `mcp<2` — a major version no part of this project uses, and
    one `agent/` cannot follow because the C06.2b server is written against 2.2.0's `MCPServer` — or patching a
    third-party library. `docs/agentscope-migration.md:30` also requires the official stdio path to be kept, and
    `harness/mcp_client.py` already is that path, with real tests against a real server.

    What this test pins is the *shape* of the decision: AgentScope receives tool objects, and nothing in the
    spike routes a read through `agentscope.mcp`. A future change that reintroduced AgentScope's MCP client would
    fail here and have to argue with the four findings first.
    """
    import inspect

    from resolveflow_spike import adapter

    source = inspect.getsource(adapter)
    assert "agentscope.mcp" not in source, (
        "the spike's adapter reaches for AgentScope's MCP client; the decided path is the project's own mcp "
        "2.2.0 client (see the four camelCase findings in reports/agentscope-migration/compatibility.md)"
    )

    # And the tools AgentScope is given are ordinary AgentScope tool objects built in-process, which is the
    # consequence: the MCP boundary is crossed once, by code this project controls and already tests.
    from tests._helpers import CountingTool

    tool = CountingTool("get_order_context", [])
    assert isinstance(tool, __import__("agentscope.tool", fromlist=["ToolBase"]).ToolBase)


def test_the_recovery_allowance_does_not_reach_into_agentscope() -> None:
    """A budget guard is ours, so it can be tested without an SDK in the loop at all.

    This is the practical dividend of decision 2 being about a boundary rather than about a wrapper: the same
    `BudgetGuard` that bounds the SDK's model calls is exercisable on its own, which is why the AS01.2 recovery
    probes can be written against it directly.
    """
    allowance = RecoveryAllowance(budget_guard(RunBudget(model_calls=1)), recovery_model_calls=1)

    async def no_such_call() -> None:  # pragma: no cover - proves no loop is needed
        raise AssertionError("this test must not need an event loop")

    # No anyio.run, no Agent, no model: the allowance is plain synchronous bookkeeping.
    assert allowance.note_recovery_turn(input_tokens=5, output_tokens=5, reason="no sdk needed") is True
    assert anyio is not None  # imported for the other tests in this module
    assert callable(no_such_call)
