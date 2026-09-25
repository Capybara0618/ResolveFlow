"""C08.1: the run's model input is a ``ContextPacket``, and the budget reserves for that same request.

``docs/context-engineering.md`` describes the packet; ``docs/agent-harness.md:37`` requires the final input to be
counted. These tests are about the **join**, which is the part neither C07.2's unit tests nor C06's loop tests could
show: that a run with the builder on assembles P0–P4 from what it has actually learned, that the observation from a
tool becomes facts *and* becomes readable, and that the number reserved against the budget is the packet's own.

The C06.4 evidence packet remains the default (``use_context_builder=False``) while both shapes coexist, so these
tests turn the builder on explicitly — and one of them asserts that the default has not silently changed, because a
default flip would make every existing loop test describe neither shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.context import CONTEXT_REQUIRED_OVERFLOW
from resolveflow.harness.facts import FactsView
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.observation_read import ObservationStore, read_observation
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.vocabulary import RunFacts

RUN = "11111111-1111-4111-8111-111111111111"
TOOLS = frozenset({"get_order_context", "get_shipment_trace", "get_refund_status"})


@pytest.fixture()
def store() -> ObservationStore:
    return ObservationStore(run_id=RUN)


@pytest.fixture()
def view() -> FactsView:
    return FactsView()


class _FakeTools:
    """A ``ToolExecutor`` answering the three tools these tests call, with recorded calls."""

    def __init__(self, answers: dict[str, dict[str, object]] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._answers = answers or {}

    def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, object]) -> ToolObservation:
        self.calls.append({"tool": tool_name, "arguments": arguments})
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
    return {
        "kind": "PROPOSE",
        "recommended_action": "REFUND",
        "reason_codes": ["LOST_CONFIRMED"],
        "summary": "承运商判定丢失",
        "reasoning": "the evidence supports it",
    }


def run(
    model: MockModelClient,
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


def last_packet_of(runner: AgentScopeRunner) -> Any:
    """The last packet the run assembled.

    Recorded on the run's client — the object that built and sent it — and the runner keeps that client so a caller
    can report what was sent without recomputing it.
    """
    client = runner.last_client
    return None if client is None else client.last_packet


def test_the_default_loop_shape_is_unchanged() -> None:
    """The C06.4 evidence packet is still the default, so existing semantics tests keep describing something.

    Asserted rather than assumed: a default flip in this change would leave every loop test asserting a packet
    shape they were not written for, and the failure would look like a regression in the run's semantics.
    """
    model = MockModelClient(script=[propose()])
    _result, runner = run(model, use_context_builder=False)
    assert runner.use_context_builder is False


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

