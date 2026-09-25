"""C06.4①: the AgentScopeRunner drives one investigation loop, over a scripted model.

``docs/agent-harness.md:9`` states the property this file exists to prove: **the action after an Observation
comes from the model, not from a fixed route keyed on case_type**. So the tests below do not assert "the run
read the shipment"; they assert the causal mechanism — that what the model asked for is what was executed,
that what the tool saw is what the model was handed back, and that the loop ends when the model decides
rather than when a route runs out.

This is the first slice of C06.4, so the model is a **script** (:class:`~resolveflow.harness.model.MockModelClient`)
and the tools are a stub executor. Both are deliberate: with the model scripted, a failure here is a failure
of the harness, not of the model; and the stub keeps this file free of subprocesses so it stays a unit test.
Driving the *real* five tools over real MCP stdio is C06.4② and is proven there.

The budget rules are checked as **counts of calls**, not as a status code. ``docs/agent-spec.md:40`` caps model
calls at 12 and tool attempts at 16; "the loop stopped" and "the loop made at most twelve model calls" are
different facts, and only the second one is the budget.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from resolveflow.contracts.core_models import CoreToolError, ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.actions import (
    ASK_CUSTOMER,
    PROPOSE,
    READ_TOOL,
    ActionRefusedError,
    ModelDecision,
    validate_decision,
)
from resolveflow.harness.budget import (
    MAX_NO_PROGRESS_ROUNDS,
    REASON_BUDGET_MODEL_CALLS,
    REASON_BUDGET_TOOL_ATTEMPTS,
    REASON_NO_PROGRESS,
    BudgetExhaustedError,
    BudgetGuard,
    RunBudget,
)
from resolveflow.harness.model import MockModelClient, ModelReply, ModelUsage
from resolveflow.harness.sdk_adapter import messenger_message
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.vocabulary import REASON_COMPLETED, RunFacts
from tests.conftest import input_text_of

RUN_ID = "5f2b1c3d-0000-4000-8000-000000000001"
CASE_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"
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


def _bound_under_test(**caps: Any) -> RunBudget:
    """The spec's budget with only the named cap lowered, for a test about **one** bound.

    The single SDK-driven loop reserves, for every request, the per-step token caps — which is what
    ``docs/agent-harness.md:37`` asks for: the answer's length is unknowable beforehand, and reserving zero would
    make the cumulative caps unenforceable. The consequence for a *test* is that a budget smaller than the
    default can be exhausted on tokens before the bound the test names, so the assertion fails for a reason the
    test is not about. Several earlier versions of these tests did exactly that and the failures looked like
    budget bugs.

    So every cap keeps the spec's default and the caller lowers the one it is testing. ``output_tokens`` and
    ``input_tokens`` are popped rather than fixed so a caller can lower them deliberately.
    """
    base = RunBudget()
    return RunBudget(
        output_tokens=caps.pop("output_tokens", base.output_tokens),
        input_tokens=caps.pop("input_tokens", base.input_tokens),
        **caps,
    )


def varied_observation(index: int, tool_name: str = "get_order_context") -> ToolObservation:
    """An observation whose content hash has not been seen before.

    Needed by the budget tests: the no-progress rule stops a run whose reads keep returning the same bytes, so a
    test about a *budget* bound must keep producing new evidence or it observes the no-progress bound instead.
    The first version of these tests passed ``index`` into the result payload, which left the hash identical — the
    hash is what "new evidence" is decided on, so the run stopped for the wrong reason.
    """
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


def observation(tool_name: str = "get_order_context", **result: Any) -> ToolObservation:
    """A successful observation, in the shape a tool answers with (``ToolObservation``).

    The content hash is fixed, so reading the same thing twice **is** the same evidence — which is the state
    ``docs/agent-spec.md:44``'s no-progress rule is about. :func:`fresh_observation` is the other state.
    """
    return ToolObservation(
        observation_id=f"obs-{tool_name}-{'a' * 16}",
        tool_name=tool_name,
        source_type=EvidenceSourceType.ORDER_LINE,
        source_ref=f"commerce:/internal/v1/order-lines/{LINE_ID}/context",
        source_version="3",
        content_hash="0" * 64,
        observed_at="2026-09-25T00:00:00Z",
        result=result or {"line_paid_amount": 2599},
    )


def fresh_observation(tool_name: str = "get_order_context", index: int = 0) -> ToolObservation:
    """A successful observation whose content hash has not been seen before.

    Used by the budget tests, which need the run to keep making progress: if every read returned the same bytes,
    the no-progress rule would stop the run long before any budget did, and the test would prove the wrong bound.
    """
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


def failed_observation(tool_name: str = "get_order_context", code: str = "NOT_FOUND") -> ToolObservation:
    """An observation that says nothing could be read. Carries no version and no hash, on purpose."""
    return ToolObservation(
        observation_id=f"obs-{tool_name}-{'b' * 16}",
        tool_name=tool_name,
        source_type=EvidenceSourceType.ORDER_LINE,
        source_ref=f"commerce:/internal/v1/order-lines/{LINE_ID}/context",
        observed_at="2026-09-25T00:00:00Z",
        error=CoreToolError(code=code, message="nothing for this line", retryable=False),
    )


class StubTools:
    """A ToolExecutor that answers from a queue and remembers what it was asked to do.

    It is a stub rather than a mock library so the assertions can be about *what the harness asked for*: the
    ``calls`` list is the evidence that the model's chosen tool and arguments are the ones that ran.
    """

    def __init__(self, *answers: ToolObservation | Exception) -> None:
        self._answers = list(answers)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        #: The run each call claimed to be made for — checked so a harness that forgot to say is caught.
        self.runs: list[str] = []

    def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolObservation:
        self.calls.append((tool_name, arguments))
        self.runs.append(run_id)
        if not self._answers:
            raise AssertionError(f"the harness called {tool_name} more times than the script allows")
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self) -> None:  # pragma: no cover - nothing to close on a stub
        return


def read(tool_name: str, **arguments: Any) -> dict[str, Any]:
    return {"kind": READ_TOOL, "tool_name": tool_name, "arguments": arguments, "reasoning": "looking"}


def propose(action: str = "REFUND", **extra: Any) -> dict[str, Any]:
    return {
        "kind": PROPOSE,
        "recommended_action": action,
        "reason_codes": ["LOST_IN_TRANSIT"],
        "summary": "the trace shows the parcel was never delivered",
        **extra,
    }


def run(model: MockModelClient, tools: StubTools, **kwargs: Any) -> Any:
    return AgentScopeRunner(model=model, tools=tools, facts=FACTS, **kwargs).run()


# ------------------------------------------------------------------ the loop itself


def test_one_read_then_a_proposal_is_two_model_calls_and_one_tool_call() -> None:
    """The shape of one investigation: model asks, tool answers, model decides.

    Two model calls — one to choose the read, one to decide after seeing it. A harness that already knew the
    route would need one, and that difference is the whole claim.
    """
    model = MockModelClient([read("get_order_context"), propose()])
    tools = StubTools(observation())

    result = run(model, tools)

    assert result.completed is True
    assert result.reason_code == REASON_COMPLETED
    assert result.decision is not None
    assert result.decision.recommended_action == "REFUND"
    assert model.calls == 2
    assert tools.calls == [("get_order_context", {})]
    assert tools.runs == [RUN_ID]
    assert len(result.observations) == 1


def test_the_observation_reaches_the_next_model_call() -> None:
    """``docs/agent-harness.md:9``: the next action follows **from the Observation**.

    The mechanism, not the outcome: the second model call must be handed what the tool actually saw, and the
    tool's arguments must be the ones the *model* chose. Asserting only "a proposal came out" would pass for a
    harness that ignored the observation entirely.
    """
    model = MockModelClient([read("get_shipment_trace", limit=3), propose()])
    tools = StubTools(observation("get_shipment_trace", carrier_conclusion="IN_TRANSIT"))

    run(model, tools)

    # What the model chose is what ran, arguments and all.
    assert tools.calls == [("get_shipment_trace", {"limit": 3})]
    # And the tool's answer is in the input of the model's next call. Read through `input_text_of` rather than
    # `model.packets`, because the loop's input shape can be the evidence packet or the P0–P4 context packet and this
    # claim is about neither of them: what matters is that the shipment conclusion the tool returned is visible to the
    # second call. (Reaching into `packets` is what made this test fail when the default flipped; the claim was fine,
    # the access path was not.) That the same fact *also* reaches the model as a rendered `key=value` P2 line is the
    # other shape's business, and `tests/integration/test_context_wiring.py` asserts it with the builder on.
    second = input_text_of(model, 1)
    assert "IN_TRANSIT" in second, f"the second model call did not carry the first call's observation: {second}"


def test_a_proposal_ends_the_run_without_another_model_call() -> None:
    """PROPOSE is terminal (``docs/agent-harness.md:25``): the loop must not ask the model what to do next."""
    model = MockModelClient([propose("MANUAL_REVIEW")])
    tools = StubTools()

    result = run(model, tools)

    assert model.calls == 1
    assert tools.calls == []
    assert result.decision is not None
    assert result.decision.recommended_action == "MANUAL_REVIEW"


def test_a_failed_read_is_handed_back_to_the_model_as_an_observation() -> None:
    """``docs/agent-harness.md:51``: an error observation goes back to the model, it does not end the run.

    A tool that could not observe has not decided anything, so the run continues and the model sees the
    failure. Ending the run here would turn "the shop was unreachable" into a conclusion.
    """
    model = MockModelClient([read("get_shipment_trace"), propose("MANUAL_REVIEW")])
    tools = StubTools(failed_observation("get_shipment_trace"))

    result = run(model, tools)

    assert result.completed is True
    assert model.calls == 2
    # The failure is visible to the next call, as an error observation — read through the shared accessor so the
    # claim does not depend on which input shape the loop is using.
    handed_back = input_text_of(model, 1)
    assert "NOT_FOUND" in handed_back, f"the failed read was not handed back: {handed_back}"
    # A failure is still an attempt: the budget that bounds the loop counts it.
    assert result.spend.tool_attempts == 1


# ------------------------------------------------------------------ the budget


def test_the_model_call_budget_stops_the_loop_and_says_which_budget_ran_out() -> None:
    """``docs/agent-spec.md:40``: at most 12 model calls. A loop that cannot end is not bounded.

    The model here never decides, so only the budget can end the run. Every read answers with *new* bytes, so
    the no-progress rule never fires: were it otherwise, this test would be proving that bound instead, and the
    reason code would be the wrong one. The count is the assertion — a harness that stopped after 3 calls would
    also "stop the loop", and would be a different product.
    """
    model = MockModelClient.always(read("get_order_context"))
    tools = StubTools(*[fresh_observation(index=index) for index in range(50)])

    result = run(model, tools)

    assert result.completed is False
    assert result.reason_code == REASON_BUDGET_MODEL_CALLS
    assert model.calls == 12, "the spec's cap is 12 model calls, including repairs and retries"
    assert result.spend.model_calls == 12


def test_the_tool_attempt_budget_stops_the_loop_and_says_which_budget_ran_out() -> None:
    """``docs/agent-spec.md:40``: at most 16 external tool attempts.

    Forced with a smaller cap than the spec's, so the test says what it means: the *limit* is what stops the
    loop, and it stops at the limit rather than one past it.
    """
    model = MockModelClient.always(read("get_order_context"))
    tools = StubTools(*[fresh_observation(index=index) for index in range(50)])

    # `model_calls=8`, not the default 12: one model call per tool attempt plus the turns the SDK takes around
    # a refusal, so the cap is modest enough that the **tool-attempt** bound fires first. A larger cap would let
    # the input estimate exhaust the 40000-token budget first.
    result = run(model, tools, budget=_bound_under_test(tool_attempts=3, model_calls=8))

    assert result.completed is False
    assert result.reason_code == REASON_BUDGET_TOOL_ATTEMPTS
    assert result.spend.tool_attempts == 3
    assert len(tools.calls) == 3, "a tool call past the budget would be a 17th attempt"


def test_the_default_budget_is_the_one_the_spec_declares() -> None:
    """The numbers are the spec's, stated in one place so a drift is a red test rather than a surprise.

    ``docs/agent-spec.md:40``: 12 model calls, 16 tool attempts, 8 local reads, 40000 input / 4000 output
    tokens; ``docs/agent-harness.md:37``: 8192 per-step input, 1024 per-step output.
    """
    budget = RunBudget()
    assert (budget.model_calls, budget.tool_attempts, budget.local_reads) == (12, 16, 8)
    assert (budget.input_tokens, budget.output_tokens) == (40000, 4000)
    assert (budget.step_input_tokens, budget.step_output_tokens) == (8192, 1024)


def test_a_single_step_over_the_per_step_token_cap_is_refused() -> None:
    """``docs/agent-harness.md:37``: a step may not exceed the per-step input cap.

    Checked *before* the call is recorded as spent, because the point of the cap is that the request never
    goes out: a harness that refused afterwards would have paid for the call it refused.
    """
    guard = BudgetGuard(RunBudget(step_input_tokens=100))
    with pytest.raises(BudgetExhaustedError) as refusal:
        guard.reserve_model_call(input_tokens=101, output_tokens=10)
    assert "step" in str(refusal.value).lower()


def test_the_guard_counts_before_it_spends() -> None:
    """The eleventh call is allowed and the twelfth is allowed; the thirteenth is not.

    An off-by-one here is invisible in a passing suite and shows up as a run that made one call more than it
    promised. Written as the boundary rather than as a count so it fails on either side.
    """
    guard = BudgetGuard(RunBudget(model_calls=2))
    guard.reserve_model_call(input_tokens=1, output_tokens=1)
    guard.reserve_model_call(input_tokens=1, output_tokens=1)
    with pytest.raises(BudgetExhaustedError):
        guard.reserve_model_call(input_tokens=1, output_tokens=1)


def test_the_cumulative_token_budget_is_enforced_across_steps() -> None:
    """A per-step cap alone would let twelve steps of 8192 tokens through a 40000 budget."""
    guard = BudgetGuard(RunBudget(input_tokens=1500, step_input_tokens=8192))
    guard.reserve_model_call(input_tokens=1000, output_tokens=10)
    with pytest.raises(BudgetExhaustedError) as refusal:
        guard.reserve_model_call(input_tokens=600, output_tokens=10)
    assert "input" in str(refusal.value).lower()


# ------------------------------------------------------------------ no progress


def test_two_identical_actions_without_new_evidence_are_reported_then_stopped() -> None:
    """``docs/agent-spec.md:44``: 连续重复同动作且无新证据，两次反馈NO_PROGRESS，第三次停止.

    The script asks for the *same* read every time and the tool answers with the same thing, so no new
    evidence ever arrives. The third identical action ends the run rather than being executed, and the reason
    says so — a run that stopped for "no progress" under a budget reason would be a different story told
    about the same events.
    """
    model = MockModelClient.always(read("get_order_context"))
    tools = StubTools(*[observation() for _ in range(20)])

    result = run(model, tools, budget=_bound_under_test(model_calls=12))

    assert result.completed is False
    assert result.reason_code == REASON_NO_PROGRESS
    # Exactly three reads ran: the first, then the two repeats the spec feeds back, and then the refusal. A
    # fourth call would mean the third repeat was executed and *then* stopped — spending an attempt on the
    # action it was supposed to refuse, which is the boundary this test exists to pin down.
    assert len(tools.calls) == 3, f"the third repeat should be refused before it runs: {tools.calls}"
    # The boundary is stated against the constant rather than against "2", so a spec change moves both together
    # and this test keeps asserting the rule (two feedbacks, then the stop) instead of a remembered number.
    assert result.spend.no_progress_rounds == MAX_NO_PROGRESS_ROUNDS
    assert len(tools.calls) == MAX_NO_PROGRESS_ROUNDS + 1, "two repeats ran, the third was refused"
    # And the model was told, twice, before it was stopped: a stop the model never saw is a surprise, not a bound.
    assert sum(1 for notice in result.notices if notice.startswith("NO_PROGRESS")) == 2


def test_a_different_page_is_not_mistaken_for_no_progress() -> None:
    """``docs/agent-spec.md:44``: 不同版本/下一页不误判.

    Continuing a shipment trace asks the same tool for different arguments, so it is a different action. A
    progress rule that keyed on the tool name alone would stop a run that is legitimately paging.
    """
    model = MockModelClient(
        [
            read("get_shipment_trace", limit=2),
            read("get_shipment_trace", limit=2, cursor="cGFnZT0y"),
            propose("MANUAL_REVIEW"),
        ]
    )
    tools = StubTools(observation("get_shipment_trace"), observation("get_shipment_trace"))

    result = run(model, tools)

    assert result.completed is True
    assert len(tools.calls) == 2


# ------------------------------------------------------------------ what the model may not do


@pytest.mark.parametrize(
    "decision",
    [
        # 未知动作: a kind that is not in the ABI (docs/agent-spec.md:2).
        {"kind": "EXECUTE_REFUND", "tool_name": "refund", "arguments": {}},
        # 写工具: the whitelist is read-only (docs/agent-spec.md:22).
        {"kind": READ_TOOL, "tool_name": "issue_refund", "arguments": {}},
        # 任意URL: a source is a controlled reference, never a requestable address (docs/core-contracts.md:61).
        {"kind": READ_TOOL, "tool_name": "get_order_context", "arguments": {"url": "http://evil.example/x"}},
        # 身份字段: the run's subject is not the model's to supply (docs/core-scope.md invariant).
        {"kind": READ_TOOL, "tool_name": "get_order_context", "arguments": {"line_id": "7002"}},
        {"kind": READ_TOOL, "tool_name": "get_order_context", "arguments": {"case_id": CASE_ID}},
        {"kind": READ_TOOL, "tool_name": "get_order_context", "arguments": {"run_id": RUN_ID}},
        {"kind": READ_TOOL, "tool_name": "get_order_context", "arguments": {"merchant_id": "M-9999"}},
    ],
)
def test_an_action_the_model_may_not_take_is_refused(decision: dict[str, Any]) -> None:
    """The refusals of ``docs/agent-spec.md:22``: 未知动作、身份字段、任意URL或写工具拒绝."""
    with pytest.raises(ActionRefusedError):
        validate_decision(decision)


def test_a_refused_action_ends_the_run_instead_of_being_executed() -> None:
    """A refusal must not reach the tool: the harness stops and records why."""
    model = MockModelClient([{"kind": "EXECUTE_REFUND", "arguments": {"amount_minor": 2599}}])
    tools = StubTools()

    result = run(model, tools)

    assert tools.calls == []
    assert result.completed is False
    assert result.reason_code == "ACTION_REFUSED"


def test_the_whitelist_is_the_specs_five_tools() -> None:
    """A model naming a tool outside ``docs/agent-spec.md:26-32`` is refused, whatever the server would do.

    The MCP server enforces the same list, and that is not redundant: the server's list is what a *client* can
    call, while this one is what the run will *ask* for, and a run that asked a deployment for a tool the spec
    does not allow would be relying on the deployment to say no.
    """
    for name in (
        "get_order_context",
        "get_shipment_trace",
        "get_refund_status",
        "get_case_evidence",
        "get_policy_manifest",
    ):
        validate_decision(read(name))
    with pytest.raises(ActionRefusedError):
        validate_decision(read("get_shipment_trace_v2"))


# ------------------------------------------------------------------ the decision's own shape


def test_ask_customer_is_allowed_and_ends_the_run() -> None:
    """ASK_CUSTOMER is a terminal action of the ABI: the run stops and waits for a new revision."""
    model = MockModelClient(
        [
            {
                "kind": ASK_CUSTOMER,
                "questions": [{"question_id": "q1", "prompt": "which parcel?"}],
                "reason_codes": ["NEEDS_EVIDENCE"],
            }
        ]
    )
    result = run(model, StubTools())

    assert result.completed is True
    assert result.decision is not None
    assert result.decision.kind == ASK_CUSTOMER


def test_more_than_three_questions_is_refused() -> None:
    """``docs/agent-spec.md:18``: ASK_CUSTOMER takes 最多3个聚合问题."""
    decision = {
        "kind": ASK_CUSTOMER,
        "questions": [{"question_id": f"q{index}", "prompt": "?"} for index in range(4)],
        "reason_codes": ["NEEDS_EVIDENCE"],
    }
    with pytest.raises(ActionRefusedError):
        validate_decision(decision)


def test_an_unknown_decision_kind_is_refused_by_the_decision_type() -> None:
    """The model's reply is validated before it is acted on, so a malformed action is a refusal, not a crash."""
    with pytest.raises(ValidationError):
        ModelDecision.model_validate({"kind": "WANDER", "arguments": {}})


def test_a_model_reply_carries_its_usage_so_the_budget_is_not_guessed() -> None:
    """Token accounting comes from the reply, and a reply that reports none must not be counted as free."""
    reply = ModelReply(decision=propose(), usage=ModelUsage(input_tokens=120, output_tokens=30))
    assert reply.usage.total_tokens == 150


# ------------------------------------------------------------------ the model client contract


def test_the_scripted_model_is_asked_once_per_step_and_runs_out_loudly() -> None:
    """A script that is exhausted raises rather than inventing a decision.

    A mock that quietly returned a default would let a harness bug look like a passing test: the run would end
    for a reason nobody wrote down.
    """
    model = MockModelClient([read("get_order_context")])
    model.packets.clear()
    # The client protocol speaks AgentScope messages (AS02.1), so the turn is a real `Msg` carrying the packet as
    # a JSON text block rather than a dict with the packet as its content.
    turn = messenger_message({"run": {"run_id": "r"}, "step": 1, "observations": []})
    with pytest.raises(AssertionError):
        model.decide(system="s", messages=[turn])
        model.decide(system="s", messages=[turn])
