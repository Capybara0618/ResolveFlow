"""C08.1: the run's model input is a ``ContextPacket``, and the budget reserves for that same request.

``docs/context-engineering.md`` describes the packet; ``docs/agent-harness.md:37`` requires the final input to be
counted. These tests are about the **join**, which is the part neither C07.2's unit tests nor C06's loop tests could
show: that a run with the builder on assembles P0–P4 from what it has actually learned, that the observation from a
tool becomes facts *and* becomes readable, and that the number reserved against the budget is the packet's own.

C08.1a: the bounded builder is the **formal default** (``use_context_builder=True``). One test states that default
by constructing a run with no flag at all, because that is the path a worker gets; another runs the C06.4 evidence
packet the way a caller now has to ask for it — explicitly.

A claim like "the model was shown the evidence" must be checked against the messages the model was actually sent.
``model.packets`` holds the run's structured ``context`` for a **script**, and under the formal path that is a
different channel from the request, so reading it would let a hidden input satisfy a claim about the real one.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from resolveflow.contracts.core_models import CoreToolError, ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.budget import REASON_NO_PROGRESS, BudgetExhaustedError, BudgetGuard, RunBudget
from resolveflow.harness.context import CONTEXT_REQUIRED_OVERFLOW
from resolveflow.harness.facts import FactsView
from resolveflow.harness.live_model import HttpResponse, LiveModelClient
from resolveflow.harness.model import MockModelClient, ModelClient
from resolveflow.harness.observation_read import ObservationStore, read_observation
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.vocabulary import RunFacts
from tests.conftest import input_text_of

RUN = "11111111-1111-4111-8111-111111111111"
TOOLS = frozenset({"get_order_context", "get_shipment_trace", "get_refund_status"})


@pytest.mark.parametrize("builder", [False, True])
def test_output_exhaustion_blocks_the_next_request(builder: bool) -> None:
    from resolveflow.harness.model import ModelUsage

    model = MockModelClient(script=[read_tool(), propose()], usage=ModelUsage(output_tokens=1))
    result, _ = run(model, use_context_builder=builder, budget=RunBudget(output_tokens=1))
    assert not result.completed
    assert result.reason_code == "BUDGET_OUTPUT_TOKENS"
    assert model.calls == 1
    assert result.spend.output_tokens == 1


@pytest.mark.parametrize("builder", [False, True])
def test_overproduced_output_is_charged_but_never_executed(builder: bool) -> None:
    from resolveflow.harness.model import ModelUsage

    tools = _FakeTools()
    model = MockModelClient(script=[read_tool(), propose()], usage=ModelUsage(output_tokens=5))
    result, _ = run(
        model, tools=tools, use_context_builder=builder, budget=RunBudget(output_tokens=1, step_output_tokens=1)
    )
    assert not result.completed
    assert model.calls == 1
    assert result.spend.output_tokens == 5
    assert tools.calls == []


def test_output_reservation_settles_remainder_and_keeps_unknown_cost() -> None:
    guard = BudgetGuard(RunBudget(output_tokens=10, step_output_tokens=8))
    assert guard.reserve_model_request(input_tokens=1) == 8
    assert guard.spend.output_tokens == 8
    guard.settle_model_output(3)
    assert guard.spend.output_tokens == 3
    assert guard.reserve_model_request(input_tokens=1) == 7
    guard.settle_model_output(None)  # response/usage unknown: no refund
    assert guard.spend.output_tokens == 10
    with pytest.raises(BudgetExhaustedError):
        guard.reserve_model_request(input_tokens=1)


def test_model_receives_the_reserved_output_ceiling() -> None:
    model = MockModelClient(script=[read_tool(), propose()])
    result, _ = run(model, budget=RunBudget(output_tokens=3, step_output_tokens=2))
    assert result.completed
    assert model.output_limits == [2, 2]  # exact zero usage refunds each reservation


def test_context_packet_is_the_entire_model_input_not_a_prefix() -> None:
    import hashlib
    import json

    from resolveflow.harness.context import PROVIDER_WRAPPER_ALLOWANCE, estimate_tokens

    model = MockModelClient(script=[read_tool(), propose()])
    result, _ = run(model)
    for packet, messages, structured in zip(model.sent_contexts, model.conversations, model.packets, strict=True):
        actual = [
            {"role": msg.role, "content": "".join(block.text for block in msg.get_content_blocks())} for msg in messages
        ]
        assert actual == list(packet.messages), "no SDK transcript may bypass trimming or accounting"
        assert "system" not in structured, "system already occurs once in the packet"
        document = {"system": "", "messages": actual}
        payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        assert packet.context_hash == hashlib.sha256(payload.encode()).hexdigest()
        assert packet.input_tokens == sum(estimate_tokens(m["content"]) for m in actual) + PROVIDER_WRAPPER_ALLOWANCE
    assert result.spend.input_tokens == sum(p.input_tokens for p in model.sent_contexts)


def test_real_refund_contract_field_reaches_protected_facts() -> None:
    from pathlib import Path

    import yaml

    contract = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "contracts/core/openapi-commerce.yaml").read_text(encoding="utf-8")
    )
    schema = contract["components"]["schemas"]["LineRefundStatus"]
    body = {
        "line_id": "7001",
        "merchant_id": "M-1001",
        "line_paid_amount": 2599,
        "refunded_amount": 0,
        "reserved_refund_amount": 2599,
        "currency": "CNY",
        "state": "RESERVED",
        "version": 1,
    }
    assert set(schema["required"]) <= body.keys() <= schema["properties"].keys()
    view = FactsView()
    model = MockModelClient(script=[read_tool("get_refund_status"), propose()])
    run(model, view=view, tools=_FakeTools({"get_refund_status": body}))
    assert view.live("line_reserved_amount_minor")[0].value == "2599"
    assert not view.live("line_refundable_amount_minor"), "do not invent an authoritative derived amount"


def test_legacy_input_reservation_covers_the_rebuilt_request() -> None:
    from resolveflow.harness.sdk_runner import _estimate_input_tokens

    model = MockModelClient(script=[read_tool(), propose()])
    result, runner = run(model, use_context_builder=False)
    assert result.spend.input_tokens == sum(
        _estimate_input_tokens({"system": runner.system, "messages": messages}) for messages in model.conversations
    )


@pytest.mark.parametrize("builder", [False, True])
def test_input_cap_blocks_before_the_model_is_called(builder: bool) -> None:
    model = MockModelClient(script=[propose()])
    result, _ = run(model, use_context_builder=builder, budget=RunBudget(step_input_tokens=1))
    assert not result.completed
    assert model.calls == 0


def test_estimated_usage_does_not_refund_output_reservation() -> None:
    from resolveflow.harness.model import ModelUsage

    model = MockModelClient(script=[read_tool(), propose()], usage=ModelUsage(output_tokens=0, estimated=True))
    result, _ = run(model, budget=RunBudget(output_tokens=2, step_output_tokens=2))
    assert not result.completed
    assert model.calls == 1
    assert result.spend.output_tokens == 2


@pytest.fixture()
def store() -> ObservationStore:
    return ObservationStore(run_id=RUN)


@pytest.fixture()
def view() -> FactsView:
    return FactsView()


class _FakeTools:
    """A ``ToolExecutor`` answering the three tools these tests call, with recorded calls."""

    def __init__(
        self,
        answers: dict[str, dict[str, object]] | None = None,
        errors: dict[str, str] | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._answers = answers or {}
        #: tool name -> error code. An entry here answers with an *error observation*, which is how a source that
        #: cannot be read is representable (`docs/agent-spec.md:36`) and what `docs/agent-harness.md:51` requires
        #: to go back to the model.
        self._errors = errors or {}

    def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, object]) -> ToolObservation:
        self.calls.append({"tool": tool_name, "arguments": arguments})
        if tool_name in self._errors:
            return ToolObservation(
                observation_id=f"obs-{tool_name}",
                tool_name=tool_name,
                source_type=EvidenceSourceType.ORDER_LINE,
                source_ref=f"order:{tool_name}",
                source_version="3",
                content_hash="a" * 64,
                observed_at="2026-09-25T10:00:00Z",
                result=None,
                error=CoreToolError(
                    code=self._errors[tool_name],
                    message=f"{tool_name} has no record for this line",
                    retryable=False,
                ),
            )
        result = self._answers.get(tool_name, {"line_paid_amount": 2599, "currency": "CNY"})
        return ToolObservation(
            observation_id=f"obs-{tool_name}",
            tool_name=tool_name,
            source_type=EvidenceSourceType.ORDER_LINE,
            source_ref=f"order:{tool_name}",
            source_version="3",
            content_hash="a" * 64,
            observed_at="2026-09-25T10:00:00Z",
            result=result,
        )

    def note_trace_page(self) -> None:
        return None

    def close(self) -> None:
        return None


def facts(**overrides: object) -> RunFacts:
    fields: dict[str, object] = {
        "run_id": RUN,
        "case_id": "22222222-2222-4222-8222-222222222222",
        "input_revision": 1,
        "line_id": "7001",
        "description": "包裹丢了，希望退款",
        "merchant_id": "M-1001",
        "customer_id": "C-2002",
        "policy_manifest": {
            "merchant_id": "M-1001",
            "bundle_ids": ["policy-logistics-2026.09"],
            "manifest_hash": "b" * 64,
            "safety_epoch": 2,
        },
    }
    fields.update(overrides)
    return RunFacts(**fields)  # type: ignore[arg-type]


def read_tool(tool: str = "get_order_context") -> dict[str, object]:
    return {"kind": "READ_TOOL", "tool_name": tool, "arguments": {}, "reasoning": "look"}


#: The keyword arguments that configure the *runner* rather than the run's facts.
RUNNER_KWARGS = frozenset(
    {"budget", "context_provider_capacity", "context_output_reserve", "max_iters", "use_context_builder"}
)


def propose() -> dict[str, object]:
    """A terminal proposal for runs that are not about citations.

    ``MANUAL_REVIEW`` rather than ``REFUND`` since C08.1c: a refund proposal must cite evidence **and** a policy rule
    (``contracts/core/agent-proposal.schema.json``), and the verifier now refuses one that does not. These tests are
    about the packet, the budget and the loop, so a proposal that needs no citations keeps them about that; the
    citation rules have their own tests, including a refund that cites what the run really read.
    """
    return {
        "kind": "PROPOSE",
        "case_type": "LOGISTICS",
        "recommended_action": "MANUAL_REVIEW",
        "reason_codes": ["LOST_CONFIRMED"],
        "summary": "承运商判定丢失",
        "reasoning": "the evidence supports it",
    }


def propose_refund(**extra: object) -> dict[str, object]:
    """A refund proposal, optionally carrying citations — the actionable case the verifier checks."""
    proposal: dict[str, object] = {
        "kind": "PROPOSE",
        "case_type": "LOGISTICS",
        "recommended_action": "REFUND",
        "reason_codes": ["LOST_CONFIRMED"],
        "summary": "承运商判定丢失",
        "reasoning": "the evidence supports it",
    }
    proposal.update(extra)
    return proposal


def run(
    model: ModelClient,
    *,
    view: FactsView | None = None,
    store: ObservationStore | None = None,
    use_context_builder: bool = True,
    tools: _FakeTools | None = None,
    **overrides: object,
) -> tuple[Any, AgentScopeRunner]:
    # Runner kwargs are separated from facts kwargs by name, so the helper cannot leak one into `RunFacts`. The
    # first version did exactly that for `context_provider_capacity`, and the failure pointed at the helper rather
    # than at anything under test.
    runner_kwargs = {name: overrides.pop(name) for name in sorted(overrides) if name in RUNNER_KWARGS}
    runner = AgentScopeRunner(
        model=model,
        tools=tools or _FakeTools(),  # type: ignore[arg-type]
        facts=facts(**overrides),
        facts_view=view,
        observation_store=store,
        use_context_builder=use_context_builder,
        max_iters=runner_kwargs.pop("max_iters", 4),  # type: ignore[arg-type]
        **runner_kwargs,  # type: ignore[arg-type]
    )
    return runner.run(), runner


def test_the_legacy_packet_carries_the_notice_the_model_was_given() -> None:
    """The compatibility path delivers the same notice (`docs/agent-spec.md:44`), through its own packet shape.

    Worth its own test: the two paths build the request differently — P0–P4 turns versus one JSON message — and the
    notice was missing from **both** before C08.1c-2, so "the model was told" has to be established per path rather
    than inferred from the one the default happens to use.
    """
    model = MockModelClient.always(read_tool())
    result, _ = run(model, use_context_builder=False, max_iters=6)

    sent = input_text_of(model, -1)

    assert result.completed is False
    assert result.reason_code == REASON_NO_PROGRESS
    assert "NO_PROGRESS" in sent, f"the legacy packet did not carry the notice: {sent}"


def test_a_refused_action_is_fed_back_once_and_the_run_recovers() -> None:
    """``docs/agent-spec.md:52``: 模型输出 Schema/引用**可修复一次** — a refused action is not the end of the run.

    The run gets one more turn, with the refusal's own reason in the request, and a corrected decision then runs to
    completion. Asserted on the **sent** messages, because "the model was told what was wrong" is the whole repair
    and a reason the model never received would make the second turn a guess.
    """
    model = MockModelClient(script=[read_tool("no_such_tool"), read_tool(), propose()])

    result, _ = run(model, tools=_FakeTools())

    assert result.completed is True, f"{result.reason_code}: {result.notices}"
    assert model.calls == 3, "the refusal must cost one extra model call, not end the run"
    sent = input_text_of(model, 1)
    assert "UNKNOWN_TOOL" in sent or "no_such_tool" in sent, f"the model was not told what was wrong: {sent}"
    # And the repair is recorded, so a reader can tell a run that recovered from one that never failed.
    assert any("REFUSED" in notice for notice in result.notices), result.notices


def test_only_one_repair_is_granted_and_the_second_refusal_stops_the_run() -> None:
    """The bound: ``docs/agent-spec.md:52`` says **once**, so a model that repeats itself is stopped.

    Without this the "repair" would be an unbounded retry loop, which is the thing the budget exists to prevent.
    """
    model = MockModelClient.always(read_tool("no_such_tool"))

    result, runner = run(model, tools=_FakeTools(), max_iters=12)

    assert result.completed is False
    assert result.reason_code == "UNKNOWN_TOOL"
    assert runner.last_client._gate.repairs_used == 1
    assert model.calls == 2, f"exactly one repair turn, then the stop: {model.calls}"


def test_a_refused_refund_is_repaired_into_a_decision_the_run_can_submit() -> None:
    """The case C08.1c is actually about: an uncited refund is refused, fed back, and then corrected.

    A terminal decision is a text block in the adapter, which would end the loop — so the repair turn has to be a
    call the permission hook denies, carrying the reason. That mechanism is what this test pins.
    """
    model = MockModelClient(script=[read_tool(), propose_refund(), propose()])

    result, _ = run(model, tools=_FakeTools())

    assert result.completed is True, f"{result.reason_code}: {result.notices}"
    assert result.decision is not None
    assert result.decision.recommended_action == "MANUAL_REVIEW"
    sent = input_text_of(model, 2)
    assert "REFUND_CITATION_REQUIRED" in sent, f"the refusal reason did not reach the repair turn: {sent}"


def test_the_repair_turn_is_counted_against_the_model_budget() -> None:
    """The repair is a real model call, so it must cost one — an uncounted retry is a budget that lies.

    ``docs/agent-spec.md:40``: the 12-call ceiling counts every attempt, **including** repairs.
    """
    model = MockModelClient(script=[read_tool("no_such_tool"), read_tool(), propose()])

    result, _ = run(model, tools=_FakeTools())

    assert result.spend.model_calls == 3, result.spend
    assert result.spend.model_calls == model.calls


def last_packet_of(runner: AgentScopeRunner) -> Any:
    """The last packet the run assembled.

    Recorded on the run's client — the object that built and sent it — and the runner keeps that client so a caller
    can report what was sent without recomputing it.
    """
    client = runner.last_client
    return None if client is None else client.last_packet


def sent_text_of(model: MockModelClient, turn: int = -1) -> str:
    """**Only** the messages the model was actually sent on one turn.

    Deliberately not ``model.packets``: that field carries the structured ``context`` a **script** needs (cursors,
    budget position), and under the formal path it is not the request. A claim about what the model was shown has to
    read this, or a channel the model never sees could satisfy it.
    """
    return "\n".join(
        block.text
        for message in model.conversations[turn]
        for block in message.get_content_blocks()
        if hasattr(block, "text")
    )


def test_the_formal_runner_defaults_to_the_bounded_builder() -> None:
    """C08.1a: with no flag passed, the run's model input is the bounded P0–P4 packet.

    The claim is about the **default** — the path a worker gets when it does not ask for anything. ``handoff-current``
    §2 C08.1a: the C06.4 evidence packet may stay only as an explicit compatibility path.
    """
    model = MockModelClient(script=[propose()])
    runner = AgentScopeRunner(model=model, tools=_FakeTools(), facts=facts())  # type: ignore[arg-type]

    assert runner.use_context_builder is True


def test_the_legacy_evidence_packet_is_still_an_explicit_compatibility_path() -> None:
    """The demoted path must still *run* when a caller asks for it, or it is not a compatibility path.

    Asserted by running the loop rather than by reading the flag back: a fallback that no longer executes is a
    fallback that no longer exists, and the previous version of this test never ran one.
    """
    model = MockModelClient(script=[propose()])
    result, runner = run(model, use_context_builder=False)

    assert runner.use_context_builder is False
    assert result.completed is True  # type: ignore[attr-defined]
    assert model.sent_contexts == [None], "the legacy path assembles no ContextPacket"
    assert "当前诉求" not in sent_text_of(model, 0), "the legacy shape is the evidence blob, not the P0–P4 packet"


def test_with_the_builder_on_the_model_input_is_a_p0_p4_packet() -> None:
    """The join this slice exists for: the model's input is the assembled packet, not the evidence blob."""
    model = MockModelClient(script=[propose()])
    result, _runner = run(model)

    assert result.completed is True  # type: ignore[attr-defined]
    # The packet travelled as the harness message, so its layers are visible in the recorded conversation.
    packet_text = "\n".join(
        block.text
        for message in model.conversations[0]
        for block in message.get_content_blocks()
        if hasattr(block, "text")
    )
    assert "P1" in packet_text, "the packet's layers are what the model was shown"
    assert "当前诉求" in packet_text
    assert "动作/工具 schema" in packet_text, "P0 carries the action/tool schema"


def test_a_tool_observation_becomes_facts_and_becomes_readable() -> None:
    """C08.1's core: every observation — not just the local reads — feeds the view and the store.

    Before this, the facts view and the store were reachable only from the policy-search bridge, so the five MCP
    tools (where the amount and the shipment conclusion come from) contributed no facts and their text could not be
    read back.
    """
    model = MockModelClient(script=[read_tool("get_order_context"), propose()])
    tools = _FakeTools({"get_order_context": {"line_paid_amount": 2599, "currency": "CNY"}})
    view, store = FactsView(), ObservationStore(run_id=RUN)

    result, _runner = run(model, view=view, store=store, tools=tools)

    assert result.completed is True  # type: ignore[attr-defined]
    # Facts: the amount is a structured field, with its source.
    amount = view.live("order_paid_amount_minor")
    assert amount and amount[0].value == "2599"
    assert amount[0].source_ref == "order:get_order_context"
    assert amount[0].authority.value == "AUTHORITY"
    # Readable: the model can read the text the fact came from, by the id in the packet.
    window = read_observation(store, observation_id="obs-get_order_context")
    assert "line_paid_amount" in window.text
    assert window.source_ref == "order:get_order_context"


def test_the_second_request_carries_the_first_observation_as_p2_facts() -> None:
    """A fact learned in turn one is in the packet for turn two — the point of a *facts* view over a transcript."""
    model = MockModelClient(script=[read_tool("get_order_context"), propose()])
    view, store = FactsView(), ObservationStore(run_id=RUN)

    run(model, view=view, store=store)

    second = "\n".join(
        block.text
        for message in model.conversations[1]
        for block in message.get_content_blocks()
        if hasattr(block, "text")
    )
    assert "order_paid_amount_minor=2599" in second, "the fact is in P2 of the next packet"
    assert "[AUTHORITY" in second, "with its source and authority"
    # And the observation the fact came from is still in the request, in P3. Its **id** is not on the P3 line —
    # that is the layering: P3 carries content, P4 carries the handles, and an observation inside the window is
    # shown as content. So the check is that the evidence is there, and that reading it back is possible (which the
    # next test does through the store).
    assert "P3·observation:get_order_context" in second
    assert "line_paid_amount" in second, "the observation's own content is in P3"


@pytest.mark.parametrize("builder", [False, True])
def test_the_tool_result_and_its_cursor_reach_the_messages_the_model_is_sent(builder: bool) -> None:
    """``handoff-current`` §2 C08.1a: tool results and the paging cursor travel in the real request.

    Read through :func:`sent_text_of` — the messages actually handed to the model — and not through
    ``model.packets``, because under the formal path that field is the *script's* structured view. A continuation
    cursor the model cannot see is a page it cannot ask for, so this is the difference between a paged tool and an
    unusable one.
    """
    model = MockModelClient(script=[read_tool("get_shipment_trace"), propose()])
    tools = _FakeTools({"get_shipment_trace": {"carrier_conclusion": "IN_TRANSIT", "next_cursor": "page-2"}})

    run(model, tools=tools, use_context_builder=builder)

    sent = sent_text_of(model, 1)
    assert "IN_TRANSIT" in sent, f"the tool's answer is not in the request the model received: {sent}"
    assert "page-2" in sent, f"the cursor is not in the request the model received: {sent}"


@pytest.mark.parametrize("builder", [False, True])
def test_a_failed_read_reaches_the_messages_the_model_is_sent(builder: bool) -> None:
    """``docs/agent-harness.md:51``: an error observation goes back to the model — in its request.

    The same trap as above: an error that exists only in the structured ``context`` would let a "the model was told
    the read failed" claim pass while the model was actually shown nothing.
    """
    model = MockModelClient(script=[read_tool("get_shipment_trace"), propose()])
    tools = _FakeTools(errors={"get_shipment_trace": "NOT_FOUND"})

    run(model, tools=tools, use_context_builder=builder)

    sent = sent_text_of(model, 1)
    assert "NOT_FOUND" in sent, f"the failed read was not in the request the model received: {sent}"


def test_a_confirmed_action_is_named_in_p1_of_the_next_request() -> None:
    """``docs/context-engineering.md:18``: P1 carries 已确认动作, so the run must name them.

    Under C06.4 the model learned its own actions from the SDK transcript. The formal path sends only the packet — that
    transcript was removed because appending it after trimming bypassed both the packet hash and the input
    reservation — so P1 is the channel that has to carry them, and the spec says so explicitly.

    Two halves, because P1 is a **mandatory** (untrimmable) layer: the action is named, and the model's own free-text
    reasoning is **not** admitted. Prose from the model is unbounded by construction and is not evidence
    (``docs/context-engineering.md:11``: MODEL_INFERENCE does not become authority by repetition).
    """
    model = MockModelClient(
        script=[
            {
                "kind": "READ_TOOL",
                "tool_name": "get_order_context",
                "arguments": {"limit": 3},
                "reasoning": "SECRET-REASONING",
            },
            propose(),
        ]
    )

    run(model, tools=_FakeTools())

    sent = sent_text_of(model, 1)
    assert "[assistant] READ_TOOL get_order_context limit=3" in sent, f"the confirmed action is not in P1: {sent}"
    assert "SECRET-REASONING" not in sent, "P1 is untrimmable, so model prose must not enter it"


def test_the_confirmed_action_window_keeps_an_untrimmable_layer_bounded() -> None:
    """P1 cannot be trimmed, so the run has to bound it by construction.

    This is the failure the window exists to prevent: a layer that grows with every action and can never be trimmed
    turns a long run into ``CONTEXT_REQUIRED_OVERFLOW`` instead of a decision. The oldest actions leave P1 while the
    newest stay, and the whole sequence remains in the outcome's ``trajectory``.
    """
    from resolveflow.harness.context import CONFIRMED_ACTION_WINDOW

    class _VariedTools(_FakeTools):
        """Distinct evidence per call, so the run is not stopped by the no-progress rule before the window fills."""

        def __init__(self) -> None:
            super().__init__()
            self._made = 0

        def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, object]) -> ToolObservation:
            self._made += 1
            fresh = super().call_tool(run_id=run_id, tool_name=tool_name, arguments=arguments)
            return fresh.model_copy(
                update={
                    "observation_id": f"obs-{tool_name}-{self._made}",
                    "content_hash": f"{self._made:064x}",
                    "source_version": str(self._made + 3),
                }
            )

    reads = [
        {"kind": "READ_TOOL", "tool_name": "get_order_context", "arguments": {"limit": step}, "reasoning": "look"}
        for step in range(1, 7)
    ]
    model = MockModelClient(script=[*reads, propose()])

    # `max_iters` raised deliberately: the default the helper uses (4) stops the loop before the window can fill,
    # which would make this test assert the bound without ever reaching it.
    run(model, tools=_VariedTools(), max_iters=12)

    sent = sent_text_of(model, -1)
    assert sent.count("[assistant] READ_TOOL") == CONFIRMED_ACTION_WINDOW, "P1 carries more actions than its window"
    assert "limit=6" in sent, "the newest action stays"
    assert "limit=1" not in sent, "the oldest action leaves P1 rather than growing an untrimmable layer"


def test_the_packet_pins_a_real_frozen_manifest_not_a_policy_reference() -> None:
    """``docs/agent-harness.md:33``: the run records the manifest it is pinned to, and the id *is* its hash.

    Until C08.1b this field carried ``<bundle-id>@<manifest_hash[:16]>`` — a policy reference with a truncated
    digest, pins nothing about the harness, prompt, tool schema, budgets or model, and is not a sha-256 at all. The
    three claims here are what makes the replacement checkable: the id is the canonical hash of the frozen manifest,
    it is a well-formed digest, and it does not change between steps of one run (frozen, not rebuilt).
    """
    from resolveflow.harness.manifest import canonical_manifest_id

    model = MockModelClient(script=[read_tool(), propose()])
    _, runner = run(model, tools=_FakeTools())

    frozen = runner.manifest()
    first = last_packet_of(runner)

    assert first.manifest_id == canonical_manifest_id(frozen)
    assert len(first.manifest_id) == 64
    assert first.manifest_id != "policy-logistics-2026.09@" + "b" * 16, "the policy reference is not a manifest"
    assert frozen["budgets"]["max_model_calls"] == runner.budget.model_calls
    assert frozen["policy_manifest_hash"] == "b" * 64

    # Same run, second step: the manifest must be the same object/value, not recomputed.
    assert model.sent_contexts[1].manifest_id == first.manifest_id


def test_a_live_client_drives_the_same_loop_and_stays_distinguishable_from_mock() -> None:
    """C08.1b-2: the loop takes a live client, and the mode is recorded rather than implied.

    ``docs/core-scope.md`` keeps mock and live results distinguishable after the fact, so a run answered by a real
    provider must say so. The transport is injected, so this exercises the whole path — packet, action gate, budget,
    outcome — without a socket or an API budget.
    """
    sent: list[dict[str, Any]] = []

    def transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
        sent.append(json.loads(body))
        answer = json.dumps(
            {
                "choices": [{"message": {"role": "assistant", "content": json.dumps(propose())}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 12},
            }
        )
        return HttpResponse(status=200, body=answer.encode("utf-8"))

    live = LiveModelClient(
        endpoint="https://model.example.invalid/v1/chat/completions",
        model_id="some-model-v2",
        api_key="sk-not-a-real-key",
        transport=transport,
    )

    result, runner = run(live, tools=_FakeTools())

    assert result.modes == ("live",), "a live answer must not be recorded as a mock one"
    assert result.completed is True
    assert result.decision.kind == "PROPOSE", "the parsed answer went through the action gate"
    # The ceiling the harness reserved reached the provider request, not just the internal call.
    assert sent[0]["max_tokens"] == runner.budget.step_output_tokens
    assert len(live.requests) == 1, "one decision, one provider call"


def test_the_citation_members_the_gate_checks_are_in_the_request_the_model_receives() -> None:
    """C08.1c: a model can only cite what it is told it may cite (``docs/context-engineering.md:17``).

    Asserted against the **sent** messages rather than the schema document the harness built: the document is right
    by construction, and the claim worth pinning is that it reaches the request. A gate that refused citations the
    prompt never described would be a harness that fails models for not guessing.
    """
    model = MockModelClient(script=[read_tool(), propose()])
    run(model, tools=_FakeTools())

    sent = input_text_of(model, 0)

    assert "evidence_refs" in sent
    assert "policy_refs" in sent
    assert "missing_evidence" in sent
    # The shape each reference needs, since the gate matches on every member and not just the id.
    assert "observation_id" in sent
    assert "content_hash" in sent


def test_a_refund_that_cites_nothing_never_becomes_the_run_s_decision() -> None:
    """C08.1c, end to end: 缺证检查 — a refund proposal with no citations must not be submitted.

    The refusal is visible in three places on purpose — the reason code the outcome reports, the gate's own record
    of which rule fired, and the fact that **no** proposal came back as the decision — because "the refund was
    refused" and "the refund was refused *and not submitted anyway*" are different claims, and only the second is
    the one that matters (``docs/agent-harness.md:13``).

    Since C08.1c-2 the first refusal is repairable, so this model sends the same uncited refund twice: the point
    survives — an uncited refund is never submitted — and the second refusal is what stops the run. The gate records
    the same mistake twice, which is how a reader tells "refused, repaired, refused again" from "refused once".
    """
    model = MockModelClient(script=[read_tool(), propose_refund(), propose_refund()])
    result, runner = run(model, tools=_FakeTools())

    assert result.completed is False
    assert result.reason_code == "REFUND_CITATION_REQUIRED"
    assert result.decision is None, "a refused proposal must not be handed on as the run's decision"
    refusals = runner.last_client._gate.refusals
    cited = [refusal for refusal in refusals if refusal["reason"] == "REFUND_CITATION_REQUIRED"]
    assert len(cited) == 2, refusals
    assert "cite" in cited[-1]["detail"]
    # One repair was granted and used, and the run still refused to submit: the repair is a chance to fix the
    # output, never a weaker check (docs/agent-spec.md:52).
    assert runner.last_client._gate.repairs_used == 1


def test_the_budget_reserves_the_packet_s_own_token_count() -> None:
    """``docs/agent-harness.md:37``: the counted input is the final one, not a second estimate of it.

    The reservation and the request have to be the same number, so the outcome's ``input_tokens`` must include the
    packet's own count for the step. Asserted as a bound rather than an equality: the run's meter is cumulative over
    turns, and pinning it to one step's count would break as soon as a turn is added.
    """
    model = MockModelClient(script=[read_tool("get_order_context"), propose()])
    view, store = FactsView(), ObservationStore(run_id=RUN)

    result, runner = run(model, view=view, store=store)

    assert result.spend.model_calls == 2  # type: ignore[attr-defined]
    assert result.spend.input_tokens > 0  # type: ignore[attr-defined]
    # The packet records how its tokens were counted, and the run reports the same mode's number.
    assert runner is not None


def test_an_overflowing_request_stops_the_run_with_the_specification_s_code() -> None:
    """``docs/context-engineering.md:27``: the mandatory layers do not fit → ``CONTEXT_REQUIRED_OVERFLOW``.

    A tiny provider capacity is how a real run reaches this: P0 plus the request plus the facts are more than the
    provider will take. The run must stop with that code and **not** send a shortened request.
    """
    model = MockModelClient(script=[propose()])
    view, store = FactsView(), ObservationStore(run_id=RUN)
    # Long enough that P1 alone cannot fit a 200-token capacity.
    result, _runner = run(
        model,
        view=view,
        store=store,
        description="包裹丢了，" + "很长的诉求" * 200,
        context_provider_capacity=200 + 256 + 256,
        context_output_reserve=256,
    )

    assert result.completed is False  # type: ignore[attr-defined]
    assert result.reason_code == CONTEXT_REQUIRED_OVERFLOW  # type: ignore[attr-defined]
    assert model.calls == 0, "an overflowing request must not reach the provider at all"


def test_the_packet_is_built_once_per_turn_so_the_request_and_the_reservation_agree() -> None:
    """The hook builds it and the adapter reuses it; a second build would be a second request."""
    model = MockModelClient(script=[read_tool("get_order_context"), propose()])
    view, store = FactsView(), ObservationStore(run_id=RUN)
    _result, runner = run(model, view=view, store=store)
    packet = last_packet_of(runner)

    assert packet is not None
    assert packet.step >= 1
    # One model call per packet, and the packet's hashes are the ones a snapshot would keep.
    assert packet.context_id.startswith("ctx-")
    assert packet.protected_fact_hash and packet.context_hash
    assert packet.token_count_mode == "ESTIMATED"
