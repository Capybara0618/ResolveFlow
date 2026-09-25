"""``READ_OBSERVATION``: the window rules, the per-run boundary, and NOT_FOUND (C07.2).

``docs/context-engineering.md:31`` is one sentence and contains five separate requirements. Each gets its own
test here, because they fail independently and only one of them fails loudly:

* ``offset>=0`` and ``limit<=4000`` — **refused, not clamped**, so a model cannot be handed a window it did not
  ask for;
* 仅访问当前run — a reference from another run is ``NOT_FOUND``, which is also what keeps the Agent from reading
  across subjects;
* 不存在ref返回NOT_FOUND — and nothing is guessed from a similar id;
* 不猜内容 — the text returned is the text that was stored, byte for byte;
* the read-back agrees with what the packet showed, which is what makes it a read-back rather than a second story.
"""

from __future__ import annotations

import pytest

from resolveflow.contracts.core_models import CoreToolError, ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.context import ContextBuilder, extract_facts
from resolveflow.harness.facts import FactsView
from resolveflow.harness.observation_read import (
    MAX_READ_LIMIT,
    ObservationNotFoundError,
    ObservationReadRefusedError,
    ObservationStore,
    read_observation,
)

RUN = "11111111-1111-4111-8111-111111111111"


def observation(
    *,
    observation_id: str = "obs-1",
    result: dict[str, object] | None = None,
    tool: str = "get_shipment_trace",
) -> ToolObservation:
    return ToolObservation(
        observation_id=observation_id,
        tool_name=tool,
        source_type=EvidenceSourceType.SHIPMENT,
        source_ref="shipment:7001",
        source_version="3",
        content_hash="a" * 64,
        observed_at="2026-09-25T10:00:00Z",
        result=result if result is not None else {"carrier_conclusion": "LOST", "status": "IN_TRANSIT"},
    )


def store_with(*observations: ToolObservation) -> ObservationStore:
    store = ObservationStore(run_id=RUN)
    for item in observations:
        store.remember(item)
    return store


# --------------------------------------------------------------------------- windows


def test_a_read_returns_the_stored_text_unchanged() -> None:
    """不猜内容: what comes back is what was stored, which is what a citation will be checked against."""
    store = store_with(observation())
    window = read_observation(store, observation_id="obs-1")

    assert "carrier_conclusion" in window.text and "LOST" in window.text
    assert window.total_length == len(window.text), "the whole text fits in one default window"
    assert window.next_offset is None
    assert window.source_ref == "shipment:7001"


def test_paging_returns_consecutive_windows_with_a_next_offset() -> None:
    """A long trace is read in pages, and each page says where the next one starts."""
    store = store_with(observation(result={"blob": "x" * 500}))
    first = read_observation(store, observation_id="obs-1", offset=0, limit=100)

    assert len(first.text) == 100
    assert first.next_offset == 100
    second = read_observation(store, observation_id="obs-1", offset=first.next_offset or 0, limit=100)
    assert second.text == first.text[:0] + second.text
    assert second.offset == 100

    # Reading to the end reports no next offset, which is how a caller knows it has finished.
    last = read_observation(store, observation_id="obs-1", offset=first.total_length - 10, limit=100)
    assert last.next_offset is None
    assert len(last.text) == 10


def test_a_partial_read_reports_the_total_so_a_caller_can_see_it_is_not_done() -> None:
    store = store_with(observation(result={"blob": "y" * 300}))
    window = read_observation(store, observation_id="obs-1", limit=50)
    assert window.total_length > window.limit
    assert window.as_result()["next_offset"] == 50
    assert window.as_result()["returned"] == 50


@pytest.mark.parametrize("offset", [-1, -100])
def test_a_negative_offset_is_refused(offset: int) -> None:
    """``:31`` offset>=0 — refused rather than treated as the start, so the caller learns its call was wrong."""
    store = store_with(observation())
    with pytest.raises(ObservationReadRefusedError, match="offset must be >= 0"):
        read_observation(store, observation_id="obs-1", offset=offset)


def test_an_offset_past_the_end_is_refused_rather_than_returning_nothing() -> None:
    """An empty window would read as "the observation ends here", which is a different fact from "you overshot"."""
    store = store_with(observation())
    with pytest.raises(ObservationReadRefusedError, match="past the end"):
        read_observation(store, observation_id="obs-1", offset=10_000)


@pytest.mark.parametrize("limit", [0, -5, MAX_READ_LIMIT + 1])
def test_a_limit_outside_the_bound_is_refused_not_clamped(limit: int) -> None:
    """``:31`` limit<=4000字符 — a clamp would return text under a window the caller did not ask for."""
    store = store_with(observation(result={"blob": "z" * 9000}))
    with pytest.raises(ObservationReadRefusedError, match="limit must be"):
        read_observation(store, observation_id="obs-1", limit=limit)


def test_the_maximum_limit_is_allowed() -> None:
    """The bound is inclusive: 4000 is a legal request and must not be refused by an off-by-one."""
    store = store_with(observation(result={"blob": "z" * 9000}))
    window = read_observation(store, observation_id="obs-1", limit=MAX_READ_LIMIT)
    assert len(window.text) == MAX_READ_LIMIT


# --------------------------------------------------------------------------- the run boundary


def test_an_unknown_reference_is_not_found() -> None:
    """``:31`` 不存在ref返回NOT_FOUND，不猜内容."""
    store = store_with(observation())
    with pytest.raises(ObservationNotFoundError) as refusal:
        read_observation(store, observation_id="obs-does-not-exist")

    assert refusal.value.code == "NOT_FOUND"
    assert refusal.value.observation_id == "obs-does-not-exist"
    assert "not an observation this run read" in str(refusal.value)


def test_another_runs_observation_is_not_found_even_if_the_id_looks_right() -> None:
    """仅访问当前run: "obs-1" in another run is not readable here.

    The store is per run and has no case index, so this is refused by construction rather than by a check — which
    is the point, because a check is a thing a later caller can forget to apply.
    """
    other_run = ObservationStore(run_id="99999999-9999-4999-8999-999999999999")
    other_run.remember(observation(observation_id="obs-1", result={"secret": "another case's data"}))

    mine = ObservationStore(run_id=RUN)
    with pytest.raises(ObservationNotFoundError):
        read_observation(mine, observation_id="obs-1")
    assert mine.ids() == [], "an empty store knows nothing, and says so"


def test_a_store_only_offers_the_ids_it_was_given() -> None:
    """``ids()`` is what a model may ask for, and it is exactly the run's own observations."""
    store = store_with(observation(observation_id="obs-a"), observation(observation_id="obs-b"))
    assert store.ids() == ["obs-a", "obs-b"]
    assert "obs-a" in store and "obs-c" not in store


def test_a_failed_observation_reads_back_its_error() -> None:
    """A read that observed nothing still has something to say, and it is the only thing it has."""
    failed = ToolObservation(
        observation_id="obs-fail",
        tool_name="get_shipment_trace",
        source_type=EvidenceSourceType.SHIPMENT,
        source_ref="shipment:7001",
        observed_at="2026-09-25T10:00:00Z",
        error=CoreToolError(code="NOT_FOUND", message="no trace for this line", retryable=False),
    )
    window = read_observation(store_with(failed), observation_id="obs-fail")

    assert "NOT_FOUND" in window.text
    assert "no trace for this line" in window.text


# --------------------------------------------------------------------------- agreement with the packet


def test_reading_back_returns_the_same_text_the_packet_excerpted() -> None:
    """The read-back and the packet are one rendering, which is what makes it a read-back.

    A model that reads a window and compares it with the excerpt it was shown must be looking at the same bytes;
    two renderings that agreed by convention would drift, and the model would be reconciling two stories.
    """
    item = observation(result={"carrier_conclusion": "LOST", "events": ["a", "b", "c"]})
    store = store_with(item)

    packet = ContextBuilder(system_prompt="sys").build(
        run_id=RUN,
        case_id="22222222-2222-4222-8222-222222222222",
        step=1,
        input_revision=1,
        line_id="7001",
        description="包裹丢了",
        manifest_id="m",
        view=FactsView(),
        observations=[item],
        tool_schema={"READ_TOOL": {}},
    )
    body = packet.messages[1]["content"]
    window = read_observation(store, observation_id="obs-1", limit=MAX_READ_LIMIT)

    assert body.rstrip().endswith(window.text), "the packet's P3 line ends with the observation's own text"


def test_a_truncated_excerpt_is_recoverable_by_reading_the_rest() -> None:
    """``:21`` 按需读回 — what the excerpt left out is reachable, which is the whole reason the index exists."""
    item = observation(result={"blob": "字" * 20_000})
    store = store_with(item)

    packet = ContextBuilder(system_prompt="sys").build(
        run_id=RUN,
        case_id="22222222-2222-4222-8222-222222222222",
        step=1,
        input_revision=1,
        line_id="7001",
        description="包裹丢了",
        manifest_id="m",
        view=FactsView(),
        observations=[item],
        tool_schema={"READ_TOOL": {}},
    )
    body = packet.messages[1]["content"]
    assert "已省略" in body, "the excerpt bounded the long field"

    # The whole text is still there, and the pointer the excerpt gave names a real position in it.
    offset = int(body.split("offset=", 1)[1].split(">", 1)[0])
    window = read_observation(store, observation_id="obs-1", offset=offset, limit=MAX_READ_LIMIT)
    assert window.total_length > 20_000, "the full text is retained, not just the excerpt"
    assert window.text.startswith("字"), "the pointer lands on the field's value"
    assert len(window.text) == MAX_READ_LIMIT, "and the window is as large as was asked for"


def test_extracted_facts_and_the_readable_text_come_from_one_observation() -> None:
    """The value in P2 and the prose behind it are one record, which is what ``observation_id`` is for."""
    item = observation()
    view = FactsView()
    extract_facts(view, item)
    fact = view.live("shipment_carrier_conclusion")[0]

    window = read_observation(store_with(item), observation_id=fact.observation_id)

    assert fact.value in window.text, "the fact's value is in the text the fact points at"
    assert window.source_ref == fact.source_ref
