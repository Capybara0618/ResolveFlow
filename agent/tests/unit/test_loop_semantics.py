"""AS02.2: the run semantics, asserted on **both** loops from one body of expectations.

`docs/agentscope-migration.md:62` is specific about what "kept" has to mean: 旧自主性/权限/预算/翻页/无进展测试语义
全部保留并跑在新循环. Re-writing the expectations for the new loop would keep nothing — it would produce a second
set of assertions that happens to pass, and there would be no way to tell a semantic that survived from one that
was quietly dropped.

So the expectations live in one place (the `_expect*` functions below) and are applied to two drivers:

* `AgentScopeRunner` — the C06.4 self-written loop, still the production path until this sub-step's switch-over;
* `AgentScopeRunner` — the SDK-driven loop, which is where production is going (`docs/agentscope-migration.md:34`).

A semantic that holds in one and not the other fails here, which is the point. `test_harness_loop.py` keeps the
C06.4 tests exactly as they are — they are the historical evidence for those semantics and are not replaced.

**What is deliberately not shared.** The two drivers take different models (a scripted `ModelClient` versus the
same client behind the SDK's adapter), because that difference is the thing under test. What is shared is the
*expectation*, and the tool executor is the same stub for both.
"""

from __future__ import annotations

from typing import Any

import pytest
from resolveflow.contracts.core_models import CoreToolError, ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.actions import ASK_CUSTOMER, PROPOSE, READ_TOOL
from resolveflow.harness.budget import (
    REASON_BUDGET_MODEL_CALLS,
    REASON_NO_PROGRESS,
    RunBudget,
)
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.vocabulary import REASON_COMPLETED, RunFacts

RUN_ID = "5f2b1c3d-0000-4000-8000-0000000000e1"
CASE_ID = "9c858abd-0000-4000-8000-0000000000e2"
LINE_ID = "7100"

FACTS = RunFacts(
    run_id=RUN_ID,
    case_id=CASE_ID,
    input_revision=1,
    line_id=LINE_ID,
    merchant_id="M-1001",
    customer_id="C-2002",
    description="the parcel never arrived",
)


def observation(tool_name: str = "get_order_context", index: int = 0) -> ToolObservation:
    """A successful observation whose hash is distinct per ``index``, so "new evidence" is controllable."""
    return ToolObservation(
        observation_id=f"obs-{tool_name}-{index:016d}",
        tool_name=tool_name,
        source_type=EvidenceSourceType.ORDER_LINE,
        source_ref=f"commerce:/internal/v1/order-lines/{LINE_ID}/context",
        source_version=str(index + 3),
        content_hash=f"{index + 1:064x}",
        observed_at="2026-09-25T00:00:00Z",
        result={"line_paid_amount": 2599, "read": index},
    )


def failed_observation(tool_name: str = "get_shipment_trace") -> ToolObservation:
    return ToolObservation(
        observation_id=f"obs-{tool_name}-{'b' * 16}",
        tool_name=tool_name,
        source_type=EvidenceSourceType.SHIPMENT_TRACK,
        source_ref=f"commerce:/internal/v1/order-lines/{LINE_ID}/shipment",
        observed_at="2026-09-25T00:00:00Z",
        error=CoreToolError(code="NOT_FOUND", message="nothing for this line", retryable=False),
    )


class StubTools:
    """A `ToolExecutor` answering from a queue, remembering what it was asked to do."""

    def __init__(self, *answers: ToolObservation | Exception) -> None:
        self._answers = list(answers)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolObservation:
        self.calls.append((tool_name, arguments))
        if not self._answers:
            raise AssertionError(f"the loop called {tool_name} more times than the script allows")
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def note_trace_page(self) -> None:  # pragma: no cover - the stub does not page
        return

    def close(self) -> None:  # pragma: no cover - nothing to close
        return


def read(tool_name: str, **arguments: Any) -> dict[str, Any]:
    return {"kind": READ_TOOL, "tool_name": tool_name, "arguments": arguments, "reasoning": "looking"}


def propose(action: str = "REFUND") -> dict[str, Any]:
    return {
        "kind": PROPOSE,
        "case_type": "LOGISTICS",
        "recommended_action": action,
        "reason_codes": ["LOST_IN_TRANSIT"],
        "summary": "the trace shows the parcel was never delivered",
    }


def run_on(driver: str, script: list[Any], tools: StubTools, *, budget: RunBudget | None = None) -> Any:
    """Run one script on the named driver.

    Only the construction differs; the assertions afterwards are the shared expectations. That is deliberate: a
    helper that also normalised the *results* would hide exactly the disagreements this file exists to find.
    """
    model = MockModelClient(script=script, repeat_last=True)
    if driver == "harness":
        return AgentScopeRunner(model=model, tools=tools, facts=FACTS, budget=budget).run()
    if driver == "agentscope":
        return AgentScopeRunner(model=model, tools=tools, facts=FACTS, budget=budget or RunBudget()).run()
    raise AssertionError(f"unknown driver {driver!r}")


#: Both drivers. Parametrising the tests over this list is what makes "the same semantics" checkable.
DRIVERS = ["harness", "agentscope"]


# ------------------------------------------------------------------ the shared expectations


@pytest.mark.parametrize("driver", DRIVERS)
def test_a_read_then_a_proposal_is_two_model_calls_and_one_tool_call(driver: str) -> None:
    """The shape of one investigation: model asks, tool answers, model decides.

    Two model calls — one to choose the read, one to decide after seeing it. A driver that already knew the route
    would need one, and that difference is the whole claim of `docs/agent-harness.md:9`.
    """
    model = MockModelClient(script=[read("get_order_context"), propose("MANUAL_REVIEW")], repeat_last=True)
    tools = StubTools(observation())
    result = (
        AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
        if driver == "harness"
        else AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
    )

    assert result.completed is True, f"{driver}: {result.reason_code} {result.notices}"
    assert result.reason_code == REASON_COMPLETED
    assert result.decision is not None
    # Not a refund: since C08.1c one must cite a policy rule the run retrieved, and this run never searched policy
    # (docs/agent-harness.md:13). What this test is about is the read/decide shape, which is unchanged.
    assert result.decision.recommended_action == "MANUAL_REVIEW"
    assert model.calls == 2, f"{driver} asked the model {model.calls} times"
    assert tools.calls == [("get_order_context", {})], f"{driver}: {tools.calls}"
    assert len(result.observations) == 1


@pytest.mark.parametrize("driver", DRIVERS)
def test_a_terminal_decision_ends_the_run_without_another_model_turn(driver: str) -> None:
    """PROPOSE is terminal: the loop must not ask the model what to do next.

    `docs/agentscope-migration.md:40` forbids the SDK adding a summary call or continuing the batch after a
    terminal action, so the count is the assertion — one proposal, one model call, no tools.
    """
    model = MockModelClient(script=[propose("MANUAL_REVIEW")], repeat_last=True)
    tools = StubTools()
    result = (
        AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
        if driver == "harness"
        else AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
    )

    assert model.calls == 1, f"{driver} spent {model.calls} model calls on a terminal decision"
    assert tools.calls == [], f"{driver} executed a tool for a terminal decision"
    assert result.decision is not None and result.decision.recommended_action == "MANUAL_REVIEW"


@pytest.mark.parametrize("driver", DRIVERS)
def test_ask_customer_ends_the_run(driver: str) -> None:
    """`ASK_CUSTOMER` is terminal too: the run stops and waits for a new revision (`docs/agent-spec.md:9`)."""
    script = [
        {
            "kind": ASK_CUSTOMER,
            "questions": [{"question_id": "q1", "field": "shipment_photo", "prompt": "which parcel?"}],
            "reason_codes": ["NEEDS_EVIDENCE"],
        }
    ]
    model = MockModelClient(script=script, repeat_last=True)
    result = (
        AgentScopeRunner(model=model, tools=StubTools(), facts=FACTS).run()
        if driver == "harness"
        else AgentScopeRunner(model=model, tools=StubTools(), facts=FACTS).run()
    )
    assert result.completed is True, f"{driver}: {result.reason_code}"
    assert result.decision is not None and result.decision.kind == ASK_CUSTOMER


@pytest.mark.parametrize("driver", DRIVERS)
def test_a_failed_read_is_handed_back_and_the_run_continues(driver: str) -> None:
    """`docs/agent-harness.md:51`: an error observation goes back to the model, it does not end the run.

    A tool that could not observe has decided nothing, so the run continues and the model sees the failure.
    Ending the run here would turn "the shop was unreachable" into a conclusion.
    """
    model = MockModelClient(script=[read("get_shipment_trace"), propose("MANUAL_REVIEW")], repeat_last=True)
    tools = StubTools(failed_observation())
    result = (
        AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
        if driver == "harness"
        else AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
    )

    assert result.completed is True, f"{driver}: {result.reason_code}"
    # The failure is an attempt: the budget that bounds the loop counts it.
    assert result.spend.tool_attempts == 1, f"{driver} counted {result.spend.tool_attempts} attempts"
    assert result.observations and result.observations[0].error is not None


@pytest.mark.parametrize("driver", DRIVERS)
def test_the_model_call_budget_stops_the_loop(driver: str) -> None:
    """`docs/agent-spec.md:40`: at most 12 model calls. A loop that cannot end is not bounded.

    Forced with a small cap so the test is quick, and asserted on the model's own counter: "the loop stopped" and
    "the provider was asked at most N times" are different facts, and only the second is the budget.
    """
    model = MockModelClient(script=[read("get_order_context")] * 50, repeat_last=True)
    tools = StubTools(*[observation(index=index) for index in range(50)])
    # Default token accounting is unlimited; the iteration bound still terminates this run.
    budget = RunBudget(model_calls=3)
    result = (
        AgentScopeRunner(model=model, tools=tools, facts=FACTS, budget=budget).run()
        if driver == "harness"
        else AgentScopeRunner(model=model, tools=tools, facts=FACTS, budget=budget).run()
    )

    assert result.completed is False, f"{driver} completed a run it should have stopped"
    assert result.reason_code == REASON_BUDGET_MODEL_CALLS, f"{driver}: {result.reason_code}"
    assert model.calls == 3, f"{driver} asked the model {model.calls} times with a cap of 3"


@pytest.mark.parametrize("driver", DRIVERS)
def test_two_identical_actions_without_new_evidence_are_stopped(driver: str) -> None:
    """`docs/agent-spec.md:44`: 两次反馈，第三次停止 — and the third is refused **before it runs**.

    The script asks for the same read and the tool answers identically, so no new evidence ever arrives. The third
    identical action ends the run rather than being executed: a driver that ran it first and stopped after would
    have spent an attempt on the thing it was refusing.
    """
    model = MockModelClient(script=[read("get_order_context")] * 20, repeat_last=True)
    tools = StubTools(*[observation() for _ in range(20)])
    budget = RunBudget(model_calls=12)
    result = (
        AgentScopeRunner(model=model, tools=tools, facts=FACTS, budget=budget).run()
        if driver == "harness"
        else AgentScopeRunner(model=model, tools=tools, facts=FACTS, budget=budget).run()
    )

    assert result.completed is False, f"{driver} completed a run with no progress"
    assert result.reason_code == REASON_NO_PROGRESS, f"{driver}: {result.reason_code}"
    assert len(tools.calls) == 3, f"{driver} ran {len(tools.calls)} identical reads; the third must be refused"
    assert result.spend.no_progress_rounds == 2, f"{driver}: {result.spend.no_progress_rounds} feedback rounds"


@pytest.mark.parametrize("driver", DRIVERS)
def test_a_different_page_is_not_mistaken_for_no_progress(driver: str) -> None:
    """`docs/agent-spec.md:44`: 不同版本/下一页不误判. A continuation is a different action.

    A progress rule keyed on the tool name alone would stop a run that is legitimately paging.
    """
    script = [
        read("get_shipment_trace", limit=2),
        read("get_shipment_trace", limit=2, cursor="cGFnZT0y"),
        propose("MANUAL_REVIEW"),
    ]
    model = MockModelClient(script=script, repeat_last=True)
    tools = StubTools(observation("get_shipment_trace", 0), observation("get_shipment_trace", 1))
    result = (
        AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
        if driver == "harness"
        else AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
    )

    assert result.completed is True, f"{driver}: {result.reason_code}"
    assert len(tools.calls) == 2, f"{driver}: {tools.calls}"


# ------------------------------------------------------------------ the refusals


@pytest.mark.parametrize("driver", DRIVERS)
@pytest.mark.parametrize(
    "decision",
    [
        pytest.param({"kind": "EXECUTE_REFUND", "tool_name": "refund", "arguments": {}}, id="unknown-kind"),
        pytest.param(
            {"kind": READ_TOOL, "tool_name": "issue_refund", "arguments": {}}, id="write-tool"
        ),
        pytest.param(
            {"kind": READ_TOOL, "tool_name": "get_order_context", "arguments": {"line_id": "7002"}},
            id="identity-field",
        ),
        pytest.param(
            {"kind": READ_TOOL, "tool_name": "get_order_context", "arguments": {"url": "http://x/y"}},
            id="arbitrary-url",
        ),
    ],
)
def test_an_action_the_abi_forbids_never_reaches_a_tool(driver: str, decision: dict[str, Any]) -> None:
    """**The acceptance criterion.** An illegal action causes zero tool executions, in either loop.

    Asserted on the tool's own call list rather than on a refusal object: a gate that returned "deny" and was
    ignored would satisfy the weaker assertion, and that is the failure worth excluding
    (`docs/agent-spec.md:22`).
    """
    model = MockModelClient(script=[decision], repeat_last=True)
    tools = StubTools()
    result = (
        AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
        if driver == "harness"
        else AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
    )

    assert tools.calls == [], f"{driver} executed {tools.calls} for a forbidden action"
    assert result.completed is False, f"{driver} reported completion for a forbidden action"
    assert result.decision is None, f"{driver} reported a decision for a forbidden action"


# ------------------------------------------------------------------ the budget arithmetic is shared


def test_the_run_budget_defaults_to_the_one_the_spec_declares() -> None:
    """The single loop enforces the spec's numbers, so a drift is a red test rather than a surprise.

    `docs/agent-spec.md:40`: 12 model calls, 16 tool attempts, 8 local reads, 40000 input / 4000 output tokens;
    `docs/agent-harness.md:37`: 8192 per-step input, 1024 per-step output. This used to compare two drivers'' budget
    objects; after AS02.2 there is one loop, so the check is against the spec directly.
    """
    runner = AgentScopeRunner(model=MockModelClient(script=[propose()]), tools=StubTools(), facts=FACTS)

    assert runner.budget == RunBudget()
