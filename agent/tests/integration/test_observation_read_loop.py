"""C07.2: ``READ_OBSERVATION`` executes inside the run, under the local-read budget.

``test_observation_read.py`` proves the store's window rules. This proves the part only the loop can show: that
the action reaches the store, that it spends the budget ``docs/context-engineering.md:31`` counts it against
(总本地读取<=8次, shared with the policy search), that a refused read names its own reason, and that the
cross-run boundary is real when a model asks for something it should not have.

Driven through the real loop (``AgentScopeRunner`` over AgentScope) with a scripted model, because "the executor
is registered and the gate lets it through" is a claim about the loop — a test calling the bridge directly would
pass even if it had never been registered.
"""

from __future__ import annotations

import pytest

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.budget import RunBudget
from resolveflow.harness.local_reads import ObservationReadBridge
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.observation_read import ObservationStore
from resolveflow.harness.sdk_runner import ActionGateMiddleware, AgentScopeRunner
from resolveflow.harness.vocabulary import RunFacts

RUN = "11111111-1111-4111-8111-111111111111"


class _NoTools:
    """A ``ToolExecutor`` that fails loudly: a local read must never reach the MCP boundary."""

    def call_tool(self, **_: object) -> object:
        raise AssertionError("a local read reached the MCP tool executor")

    def note_trace_page(self) -> None:
        raise AssertionError("a local read is not a paged tool read")

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
    }
    fields.update(overrides)
    return RunFacts(**fields)  # type: ignore[arg-type]


def observation(observation_id: str = "obs-1", *, blob: int = 40) -> ToolObservation:
    return ToolObservation(
        observation_id=observation_id,
        tool_name="get_shipment_trace",
        source_type=EvidenceSourceType.SHIPMENT,
        source_ref="shipment:7001",
        source_version="3",
        content_hash="a" * 64,
        observed_at="2026-09-25T10:00:00Z",
        result={"carrier_conclusion": "LOST", "note": "字" * blob},
    )


def propose() -> dict[str, object]:
    return {
        "kind": "PROPOSE",
        "recommended_action": "REFUND",
        "reason_codes": ["LOST_CONFIRMED"],
        "summary": "承运商判定丢失",
        "reasoning": "the shipment trace says LOST",
    }


def read(observation_id: str = "obs-1", **arguments: object) -> dict[str, object]:
    return {
        "kind": "READ_OBSERVATION",
        "observation_id": observation_id,
        "arguments": dict(arguments),
        "reasoning": "read the trace back",
    }


def run(model: MockModelClient, store: ObservationStore, **overrides: object) -> object:
    budget = overrides.pop("budget", RunBudget())
    runner = AgentScopeRunner(
        model=model,
        tools=_NoTools(),  # type: ignore[arg-type]
        facts=facts(**overrides),
        budget=budget,  # type: ignore[arg-type]
        observation_store=store,
    )
    return runner.run()


@pytest.fixture()
def store() -> ObservationStore:
    filled = ObservationStore(run_id=RUN)
    filled.remember(observation())
    return filled


def test_a_read_observation_action_executes_and_the_text_reaches_the_model(store: ObservationStore) -> None:
    """The whole point: the action has somewhere to go, and what comes back is the evidence itself."""
    model = MockModelClient(script=[read("obs-1"), propose()])

    result = run(model, store)

    assert result.completed is True  # type: ignore[attr-defined]
    assert len(result.observations) == 1  # type: ignore[attr-defined]
    read_back = result.observations[0]  # type: ignore[attr-defined]
    assert read_back.tool_name == "read_observation"
    assert read_back.source_ref == "observation:obs-1"
    assert read_back.result is not None
    assert "LOST" in read_back.result["text"], "the text the run read is in the observation"
    assert read_back.result["total_length"] >= len(read_back.result["text"])

    # And the model was shown it: the second call's packet carries the read-back.
    assert model.packets[1]["observations"], "the second model call was shown no observation"


def test_a_read_spends_a_local_read_and_a_tool_attempt(store: ObservationStore) -> None:
    """``docs/context-engineering.md:31`` counts these against the same 8 the policy search uses."""
    model = MockModelClient(script=[read("obs-1"), propose()])

    result = run(model, store)

    assert result.spend.local_reads == 1  # type: ignore[attr-defined]
    assert result.spend.tool_attempts == 1  # type: ignore[attr-defined]


def test_the_local_read_bound_stops_the_run_and_names_itself(store: ObservationStore) -> None:
    """The bound that ran out is the bound the outcome reports (``docs/agent-harness.md:45``)."""
    model = MockModelClient.always(read("obs-1"))

    result = run(model, store, budget=RunBudget(local_reads=1))

    assert result.completed is False  # type: ignore[attr-defined]
    assert result.reason_code == "BUDGET_LOCAL_READS"  # type: ignore[attr-defined]
    assert result.spend.local_reads == 1  # type: ignore[attr-defined]


def test_an_unknown_reference_stops_with_not_found(store: ObservationStore) -> None:
    """``:31`` 不存在ref返回NOT_FOUND，不猜内容 — and the reason is the code, not a generic tool failure."""
    model = MockModelClient.always(read("obs-does-not-exist"))

    result = run(model, store)

    assert result.completed is False  # type: ignore[attr-defined]
    assert result.reason_code == "NOT_FOUND"  # type: ignore[attr-defined]
    trajectory = [entry for entry in result.trajectory if entry["action"] == "read_observation"]  # type: ignore[attr-defined]
    assert trajectory and trajectory[0]["outcome"] == "REFUSED"
    assert "not an observation this run read" in trajectory[0]["detail"]


def test_an_out_of_bounds_window_is_refused_before_the_read_runs(store: ObservationStore) -> None:
    """``:31``'s bound is enforced, and it is enforced **before execution** — by the SDK, from the tool's schema.

    This is where the bound actually lives when a run is model-driven: AgentScope validates a tool call's input
    against ``input_schema`` and hands the model a correctable error instead of invoking the tool. The first
    version of this test expected the *bridge* to refuse and to set the run's stop reason, and it observed
    ``BUDGET_MODEL_CALLS`` — because the tool never ran at all, so there was no refusal to record and the loop
    retried the same invalid call until the model-call budget ran out. The behaviour underneath is better than the
    assertion: an invalid window costs no local read and never reaches the store.
    """
    model = MockModelClient.always(read("obs-1", limit=99_999))

    result = run(model, store)

    assert result.spend.local_reads == 0, "an invalid window must not spend a local read"
    assert result.observations == (), "and nothing may be observed from a call that was refused"
    assert not [entry for entry in result.trajectory if entry["action"] == "read_observation"]  # type: ignore[attr-defined]


def test_the_tool_schema_carries_the_bound_the_store_enforces(store: ObservationStore) -> None:
    """One bound, two enforcers, and the same number — the schema the SDK validates against is imported from the
    store's constant, so a drifting copy cannot become the real limit without a test noticing."""
    from resolveflow.harness.observation_read import MAX_READ_LIMIT

    bridge = ObservationReadBridge(store, facts(), ActionGateMiddleware(), None, None, None)
    limit = bridge.input_schema["properties"]["limit"]
    assert limit["maximum"] == MAX_READ_LIMIT


def test_an_empty_store_refuses_and_does_not_offer_a_guess() -> None:
    """A run that has read nothing has nothing to read back, and says so."""
    empty = ObservationStore(run_id=RUN)
    model = MockModelClient.always(read("obs-1"))

    result = run(model, empty)

    assert result.reason_code == "NOT_FOUND"  # type: ignore[attr-defined]


def test_a_run_always_has_a_store_and_an_empty_one_answers_not_found() -> None:
    """C08.1: the run creates its own store, so ``READ_OBSERVATION`` is a capability every run has.

    Before this slice, ``observation_store=None`` meant the tool was not registered at all and a model that asked
    for a read got the SDK's tool-not-found error. Now the harness owns the store, so the honest answer to a read
    before anything has been observed is ``NOT_FOUND`` — the same code an unknown id gets, because from the caller's
    side "this run has read nothing" and "this run did not read that" are the same fact.
    """
    model = MockModelClient.always(read("obs-1"))
    runner = AgentScopeRunner(
        model=model,
        tools=_NoTools(),  # type: ignore[arg-type]
        facts=facts(),
        budget=RunBudget(),
        observation_store=None,
    )

    result = runner.run()

    assert result.completed is False  # type: ignore[attr-defined]
    assert result.reason_code == "NOT_FOUND"  # type: ignore[attr-defined]
    assert result.observations == (), "nothing may be observed from a read that found nothing"  # type: ignore[attr-defined]
    assert result.spend.local_reads == 1, "and the attempt is still counted"  # type: ignore[attr-defined]


def test_paging_reaches_the_text_past_the_packet_excerpt(store: ObservationStore) -> None:
    """``:21`` 按需读回: a second read at a later offset returns different characters."""
    big = ObservationStore(run_id=RUN)
    big.remember(observation(blob=5000))
    model = MockModelClient(
        script=[
            read("obs-1", offset=0, limit=100),
            read("obs-1", offset=100, limit=100),
            propose(),
        ]
    )

    result = run(model, big)

    first, second = result.observations[0], result.observations[1]  # type: ignore[attr-defined]
    assert first.result is not None and second.result is not None
    assert first.result["offset"] == 0 and second.result["offset"] == 100
    assert first.result["text"] != second.result["text"], "a later offset is different text"
    # Two different windows are two different observations, so neither is mistaken for a repeat of the other.
    assert first.observation_id != second.observation_id
