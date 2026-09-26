"""裁剪前后演示: trimming changes the request without changing what is protected (C07.2).

``docs/context-engineering.md:41`` asks for 一个裁剪前后演示，验证必保留字段一致. It is a test rather than a script
because it is a *property*, and a script would stop being run.

What the demonstration shows, in order:

1. **Which sections were dropped and why**, from ``omitted_refs`` — a trim that recorded only that it trimmed would
   leave a reviewer unable to tell a dropped duplicate from a dropped contradiction.
2. **That every P2 fact survived byte for byte**, which is ``:19``'s 禁止生成式重写 made checkable.
3. **That ``protected_fact_hash`` is identical before and after** — ``:35``'s claim, that the trimming did not alter
   a preserved value, source, version or conflict, and explicitly *not* that the facts are correct (``:37``).
4. **That the facts view was not mutated by building a packet.** A builder that trimmed by editing the view would
   make a second packet's hash differ from the first, which is the failure this ordering exists to catch.

The caps are **measured**, not chosen: see ``tmp/c071-probe/measure_demo_layers.py``'s output quoted beside them.
Guessing produced four wrong caps while this was written, because the framing allowance (256) dominates a small
cap and the mandatory layers are cheaper than they look.
"""

from __future__ import annotations

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.context import ContextBuilder, OverflowRefusedError
from resolveflow.harness.facts import facts_hash
from tests.unit.context_fixtures import MANIFEST, RUN, build_packet, load

SYSTEM = "You are investigating one after-sales case for one order line."
TOOL_SCHEMA = {"READ_TOOL": {"tools": ["get_order_context", "get_shipment_trace", "get_refund_status"]}}

#: The fixture used, and why: it holds a protected fact (a live shipment conclusion) that must survive, and its
#: observations are large enough that a tight cap genuinely has to choose.
DEMO = "long_logistics"


def _earlier_reads(count: int = 4) -> list[ToolObservation]:
    """The observation history the demo needs.

    The fixture alone has two observations, and with ``OBSERVATION_WINDOW`` at two they **both** land in P3 — so P4
    is empty and a trimming demonstration could only show P3 losing a section. These extra reads are what the
    scenario is about: a run that has read several things before the ones it is working from, which is exactly when
    the index exists and exactly what a tight cap has to drop first. They are built here rather than added to the
    fixture so the fixture keeps testing what it was written for.
    """
    return [
        ToolObservation(
            observation_id=f"obs-earlier-{index}",
            tool_name="get_order_context",
            source_type=EvidenceSourceType.ORDER_LINE,
            source_ref=f"order:earlier-{index}",
            source_version=str(index),
            content_hash=f"{index}" * 64,
            observed_at="2026-09-25T09:00:00Z",
            result={"line_paid_amount": 100 * index, "currency": "CNY"},
        )
        for index in range(count)
    ]


def _build(scenario, view, observations, *, cap: int | None):
    builder = ContextBuilder(
        system_prompt=SYSTEM,
        **(dict(provider_capacity=cap + 512, output_reserve=256) if cap is not None else {}),
    )
    return builder.build(
        run_id=RUN,
        case_id="22222222-2222-4222-8222-222222222222",
        step=1,
        input_revision=1,
        line_id="7001",
        description="包裹丢了，希望退款",
        manifest_id=MANIFEST,
        view=view,
        observations=observations,
        tool_schema=TOOL_SCHEMA,
    )


def _smallest_cap_that_keeps_everything(scenario, view, observations) -> int:
    """The input cap at which nothing has to be dropped, found by search.

    This exists because **five successive caps in this file were guessed wrong** — the framing allowance dominates a
    small cap, the mandatory layers cost less than they look, and each fixture's numbers differ. A demonstration
    whose "tight" cap happens to fit everything compares two identical packets, and that is a failure that looks
    like a pass unless the test checks. So the cap is a measurement of the thing under test: binary-search the
    smallest cap with no omissions, then step one token below it.
    """
    low, high = 1, 8192
    while low < high:
        middle = (low + high) // 2
        try:
            packet = _build(scenario, view, observations, cap=middle)
        except OverflowRefusedError:
            low = middle + 1
            continue
        if packet.omitted_refs:
            low = middle + 1
        else:
            high = middle
    return low


def test_the_demo_has_both_states_and_the_tight_cap_really_trims() -> None:
    """A demonstration needs two different requests, and the tight one must actually drop something.

    The first version of this file asserted the packets differed and they did not: its "tight" cap still fitted
    every section, so the assertion failed. That is the test doing its job — a demonstration comparing two
    identical packets demonstrates nothing.
    """
    scenario = load(DEMO)
    _generous_packet, view, _store = build_packet(scenario)
    observations = [*scenario.observations, *_earlier_reads()]

    smallest = _smallest_cap_that_keeps_everything(scenario, view, observations)
    generous = _build(scenario, view, observations, cap=smallest)
    tight = _build(scenario, view, observations, cap=smallest - 1)

    assert generous.omitted_refs == (), "the 'generous' cap keeps everything by construction"
    assert tight.omitted_refs, "one token less forces a drop"
    assert generous.messages != tight.messages, "the two requests must differ"
    # Both trimmable layers are exercised: the fixture's own two observations are P3, the earlier reads are P4.
    assert "P4" in generous.layers, "the demo has an index to trim"
    assert {entry["layer"] for entry in tight.omitted_refs} <= {"P3", "P4"}


def test_trimming_drops_only_optional_sections_and_preserves_every_protected_field() -> None:
    """The demonstration itself: same facts, two caps, one protected hash."""
    scenario = load(DEMO)
    _generous_packet, view, _store = build_packet(scenario)
    observations = [*scenario.observations, *_earlier_reads()]
    before = facts_hash(view)

    smallest = _smallest_cap_that_keeps_everything(scenario, view, observations)
    generous = _build(scenario, view, observations, cap=smallest)
    tight = _build(scenario, view, observations, cap=smallest - 1)

    # 1. Only trimmable layers lost anything, and every omission says why.
    assert all(entry["layer"] in {"P3", "P4"} for entry in tight.omitted_refs)
    assert all(entry["reason"] for entry in tight.omitted_refs)
    assert tight.input_tokens <= tight.input_cap

    # 2. Every P2 fact survived, unchanged, and is still rendered.
    generous_facts = {fact["key"]: fact["value"] for fact in generous.facts}
    tight_facts = {fact["key"]: fact["value"] for fact in tight.facts}
    assert generous_facts, "there is something to preserve"
    assert generous_facts == tight_facts, "no fact may be added, dropped or rewritten by trimming"
    for key, value in generous_facts.items():
        assert f"{key}={value}" in tight.messages[1]["content"], f"{key} is still rendered in P2"

    # 3. The protected hash is identical, and it is the view's own hash rather than a second computation.
    assert tight.protected_fact_hash == generous.protected_fact_hash == before

    # 4. Building a packet did not mutate the view.
    assert facts_hash(view) == before

    # The demonstration's numbers, so a reader of a report sees the shape without re-running anything.
    print(
        "\n  trim demo (fixture=long_logistics, +4 earlier reads):"
        f"\n    generous: cap={generous.input_cap:>5} tokens={generous.input_tokens:>4} "
        f"layers={generous.layers} omitted={len(generous.omitted_refs)}"
        f"\n    tight:    cap={tight.input_cap:>5} tokens={tight.input_tokens:>4} "
        f"layers={tight.layers} omitted={len(tight.omitted_refs)} "
        f"dropped={[entry['label'] for entry in tight.omitted_refs]}"
        f"\n    protected_fact_hash: {before[:16]}… (equal in both: "
        f"{tight.protected_fact_hash == generous.protected_fact_hash})"
        f"\n    P2 facts preserved: {len(generous_facts)}"
    )


def test_the_facts_view_is_a_pure_input_to_the_builder() -> None:
    """``protected_fact_hash`` is only meaningful if building a packet cannot change the view it describes."""
    scenario = load(DEMO)
    _packet, view, _store = build_packet(scenario)
    before = facts_hash(view)
    snapshot = [fact.as_dict() for fact in view.facts]
    observations = [*scenario.observations, *_earlier_reads()]

    mandatory = _build(scenario, view, [], cap=None).input_tokens
    for cap in (None, mandatory + 100, mandatory):
        _build(scenario, view, observations, cap=cap)

    assert facts_hash(view) == before
    assert [fact.as_dict() for fact in view.facts] == snapshot
