"""The ContextBuilder: layers, the input cap, trimming, and the two hashes (C07.2).

The tests are organised around the three things ``docs/context-engineering.md`` asks for that a plausible
implementation gets wrong:

* **P0 is never trimmed** — so a request that does not fit is *refused*, not shortened (``:27``);
* **P2 is exact fields with sources, not prose** — and a conflict reaches the model as two disagreeing lines
  (``:19``, ``:11``);
* **trimming does not change what is protected** — the property the 裁剪前后演示 exists to show (``:41``), asserted
  here on the hashes rather than by eye.
"""

from __future__ import annotations

import json

import pytest

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.context import (
    CONTEXT_REQUIRED_OVERFLOW,
    DEFAULT_INPUT_CAP,
    ContextBuilder,
    OverflowRefusedError,
    estimate_tokens,
    extract_facts,
)
from resolveflow.harness.facts import FactsView, facts_hash

HASH_A = "a" * 64
HASH_B = "b" * 64


def test_chinese_token_estimate_is_not_characters_divided_by_three() -> None:
    assert estimate_tokens("退款金额与政策冲突") >= len("退款金额与政策冲突")


def test_repeated_material_headers_are_compacted_without_losing_sources_or_answers() -> None:
    import copy
    materials = [{"evidence_id": f"e-{i}", "source_type": "CUSTOMER_STATEMENT",
                  "source_ref": f"customer:case-1:e-{i}", "source_version": str(i),
                  "content_hash": "a" * 64, "input_revision": i, "content": f"原始材料 {i}"}
                 for i in range(6)]
    materials[4]["question_id"] = "q-1"
    materials[5].update(question_id="q-2", verification_result=None, future_metadata={"retained": True})
    snapshot = {"materials": materials, "questions": [{"question_id": "q-1", "questions": ["问题原文"]}],
                "future_field": {"unchanged": True}}
    before = copy.deepcopy(snapshot)
    packet = build(review_context=snapshot)
    text = "\n".join(message["content"] for message in packet.messages)
    assert "material_tables" in text
    document = json.JSONDecoder().raw_decode(text[text.index('{"future_field"'):])[0]
    restored = [dict(zip(table["fields"], row, strict=True)) for table in document.pop("material_tables")
                for row in table["rows"]]
    document["materials"] = restored
    assert document == before
    assert snapshot == before


def test_material_tables_do_not_truncate_oversized_customer_text() -> None:
    materials = [{"content": "长材料原文" * 2000, "source_ref": "customer:a", "content_hash": HASH_A},
                 {"content": "第二份原文", "source_ref": "customer:b", "content_hash": HASH_B}]
    with pytest.raises(OverflowRefusedError):
        build(review_context={"materials": materials})
    assert materials[0]["content"] == "长材料原文" * 2000


SYSTEM = "You are investigating one after-sales case for one order line."
TOOL_SCHEMA = {"READ_TOOL": {"tools": ["get_order_context", "get_shipment_trace"]}}


def observation(
    *,
    tool: str = "get_order_context",
    source_type: EvidenceSourceType = EvidenceSourceType.ORDER_LINE,
    source_ref: str = "order:7001",
    content_hash: str = HASH_A,
    observation_id: str = "obs-1",
    result: dict[str, object] | None = None,
) -> ToolObservation:
    fields: dict[str, object] = {
        "observation_id": observation_id,
        "tool_name": tool,
        "source_type": source_type,
        "source_ref": source_ref,
        "observed_at": "2026-09-25T10:00:00Z",
        "content_hash": content_hash,
        "source_version": "3",
        "result": result if result is not None else {"line_paid_amount": 2599, "currency": "CNY"},
    }
    return ToolObservation(**fields)


def build(**overrides: object):
    """One packet with sane defaults, so each test states only what it is about.

    ``is None`` rather than ``or`` when applying the defaults: ``FactsView()`` is falsy (it is a dataclass whose
    only field is an empty list), so a helper written with ``or`` silently threw away the view a test had just
    filled in — and the tests that failed were the ones about facts. That is what a truthiness default costs.
    """
    view = overrides.pop("view", None)
    builder = overrides.pop("builder", None)
    arguments: dict[str, object] = {
        "run_id": "11111111-1111-4111-8111-111111111111",
        "case_id": "22222222-2222-4222-8222-222222222222",
        "step": 1,
        "input_revision": 1,
        "line_id": "7001",
        "description": "包裹丢了，希望退款",
        "manifest_id": "policy-logistics-2026.09@b" + "b" * 15,
        "observations": [],
        "tool_schema": TOOL_SCHEMA,
    }
    # Defaults first, then the caller's overrides: the other order let `update` put a popped `view`/`builder`
    # back into the argument mapping, which is how a test's own view was discarded twice over.
    arguments.update(overrides)
    arguments["view"] = view if view is not None else FactsView()
    return (builder if builder is not None else ContextBuilder(system_prompt=SYSTEM)).build(
        **arguments  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- the cap


def test_the_input_cap_is_the_minimum_of_the_three_terms() -> None:
    """``:27`` 输入上限=min(8192, provider容量-输出预留-256, 累计剩余输入).

    Each term is exercised as the smallest one in turn, because a cap that only ever applied one of them would
    pass a test that checked a single case.
    """
    builder = ContextBuilder(system_prompt=SYSTEM, provider_capacity=4096, output_reserve=1024)
    # provider capacity - reserve - wrapper = 4096 - 1024 - 256 = 2816, below the 8192 ceiling.
    assert builder.input_cap() == 2816
    # A cumulative remaining below that wins.
    assert builder.input_cap(cumulative_remaining=1000) == 1000
    # And the 8192 ceiling wins when the provider is generous.
    roomy = ContextBuilder(system_prompt=SYSTEM, provider_capacity=100_000, output_reserve=1024)
    assert roomy.input_cap() == DEFAULT_INPUT_CAP


def test_the_cap_is_never_reported_as_negative() -> None:
    """A reserve larger than the provider's capacity is a misconfiguration, not a negative allowance."""
    builder = ContextBuilder(system_prompt=SYSTEM, provider_capacity=512, output_reserve=1024)
    assert builder.input_cap() == 0
    assert builder.input_cap(cumulative_remaining=-50) == 0


def test_a_request_whose_mandatory_layers_do_not_fit_is_refused_not_shortened() -> None:
    """``:27`` 转索引后仍超限则CONTEXT_REQUIRED_OVERFLOW转人工，**不删约束**.

    P0 is the system prompt and the action schema; P1 is the customer's own request; P2 is the amount. None of
    them may be dropped, so there is nothing left to index and the honest outcome is a refusal a human reads.
    """
    builder = ContextBuilder(system_prompt=SYSTEM, provider_capacity=600, output_reserve=256)

    with pytest.raises(OverflowRefusedError) as refusal:
        build(builder=builder, description="包裹丢了，" + "很长" * 200)

    assert refusal.value.reason_code == CONTEXT_REQUIRED_OVERFLOW
    assert refusal.value.cap < refusal.value.mandatory_tokens
    assert "never trimmed" in str(refusal.value)
    # The message names the largest layer, so an operator knows which input to look at.
    assert "P1" in str(refusal.value)


def test_a_tight_but_sufficient_cap_still_produces_a_packet() -> None:
    """The refusal must not fire for every small cap: a cap that fits the mandatory layers is usable."""
    builder = ContextBuilder(system_prompt=SYSTEM, provider_capacity=3000, output_reserve=256)
    packet = build(builder=builder)
    assert packet.input_tokens <= packet.input_cap


# --------------------------------------------------------------------------- layers


def test_the_system_prompt_and_tool_schema_are_the_system_turns() -> None:
    """P0 reaches the provider as the system message, and the schema is part of it (``:17``)."""
    packet = build()
    system = packet.messages[0]
    assert system["role"] == "system"
    assert SYSTEM in system["content"]
    assert "get_shipment_trace" in system["content"], "the action/tool schema is P0, not decoration"
    assert packet.messages[1]["role"] == "user"


def test_the_tool_schema_hash_changes_with_the_schema() -> None:
    """The snapshot records which tools the model was offered, so the hash has to distinguish them."""
    first = build()
    second = build(tool_schema={"READ_TOOL": {"tools": ["get_order_context"]}})
    assert first.tool_schema_hash != second.tool_schema_hash


def test_the_request_and_the_recent_turns_are_p1() -> None:
    packet = build(history=[{"role": "user", "content": "什么时候能退"}, {"role": "assistant", "content": "正在核实"}])
    body = packet.messages[1]["content"]
    assert "当前诉求：包裹丢了，希望退款" in body
    assert "什么时候能退" in body and "正在核实" in body


def test_p2_facts_are_exact_fields_with_their_source_and_status() -> None:
    """``:19`` 精确字段及来源，禁止生成式重写.

    The assertion is on the *shape* of the line: the value the tool returned, unchanged, with the source it came
    from. A builder that rewrote "2599" into "订单支付 25.99 元" would be doing exactly what the spec forbids, and
    a test that only checked the number was present would not catch it.
    """
    view = FactsView()
    extract_facts(view, observation())
    packet = build(view=view)

    body = packet.messages[1]["content"]
    assert "order_paid_amount_minor=2599" in body
    assert "order_currency=CNY" in body
    assert "[AUTHORITY order:7001@3]" in body
    assert "元" not in body, "the value is not converted or explained"


def test_different_fields_are_not_a_conflict() -> None:
    """Only the **same** field from two sources can disagree.

    Worth asserting because the opposite failure is easy to write: a builder that marked a conflict whenever two
    observations disagreed about anything would flag every run, and the model would learn to ignore the flag.
    """
    view = FactsView()
    extract_facts(view, observation())
    extract_facts(
        view,
        observation(
            # `get_refund_status` contributes `line_refunded_amount_minor`, a different field from the order
            # line's `order_paid_amount_minor`. The first version of this test passed a tool whose configured
            # fields do not include the key it asserted on, so nothing disagreed and the failure looked like a
            # builder bug — it was the assertion, and the per-tool field list was working as designed.
            tool="get_refund_status",
            source_type=EvidenceSourceType.PAYMENT_LEDGER,
            source_ref="ledger:7001",
            content_hash=HASH_B,
            observation_id="obs-2",
            result={"refunded_amount": 2599},
        ),
    )
    packet = build(view=view)

    body = packet.messages[1]["content"]
    assert "order_paid_amount_minor=2599" in body
    assert "line_refunded_amount_minor=2599" in body
    assert "status=CONFLICT" not in body
    assert not view.conflicts()


def test_two_sources_claiming_the_same_field_differently_reach_the_model_as_both() -> None:
    """``:11`` 不同来源冲突同时保留 — the model is shown both, because that is the fact a human needs."""
    view = FactsView()
    view.note(key="refundable_amount_minor", value="2599", observation=observation(source_ref="order:7001"))
    view.note(
        key="refundable_amount_minor",
        value="0",
        observation=observation(
            tool="get_refund_status",
            source_type=EvidenceSourceType.PAYMENT_LEDGER,
            source_ref="ledger:7001",
            content_hash=HASH_B,
            observation_id="obs-2",
        ),
    )
    packet = build(view=view)

    body = packet.messages[1]["content"]
    assert "refundable_amount_minor=2599" in body
    assert "refundable_amount_minor=0" in body
    assert "status=CONFLICT" in body
    # And the value with its source, so a reader can see *which* source claims what.
    assert "order:7001" in body and "ledger:7001" in body


def test_the_recent_observations_are_p3_and_the_earlier_ones_are_p4_index_entries() -> None:
    """P3 is 当前Observation, P4 is 较早工具索引 (``:19-21``) — the two layers are not the same thing twice.

    The first version put every observation in both, with the same ``ref``, and the duplicate rule then deleted
    P4 entirely: the index that exists to make prose reachable was never sent, and no test noticed because none
    asserted the two layers *differ*. This one builds three observations and asserts which layer each is in.
    """
    observations = [observation(observation_id=f"obs-{index}", source_ref=f"order:{index}") for index in range(3)]
    packet = build(observations=observations)
    body = packet.messages[1]["content"]

    # The most recent two carry content; the oldest is an index entry only.
    assert "【P3·observation:get_order_context】" in body
    assert "【P4·index:0】" in body
    assert "obs-0" in body, "the earlier observation is present as a reference"
    # The oldest body is not repeated. Its protected citation and read-back index both survive.
    assert body.count("obs-0") == 2
    assert '"observation_id":"obs-0","source_ref":"order:0","source_version":"3"' in body
    for section in body.split("【P3·")[1:]:
        assert "obs-0" not in section.split("【P4·")[0]
    assert "obs-1" in packet.selected_refs and "index:obs-0" in packet.selected_refs


def test_a_single_observation_is_p3_with_no_p4_entry() -> None:
    """With nothing earlier, P4 is empty rather than repeating P3's ref."""
    packet = build(observations=[observation()])
    body = packet.messages[1]["content"]
    assert "【P3·observation:get_order_context】" in body
    assert "【P4·index:0】" not in body


def test_p3_carries_evidence_citation_members_in_actual_messages() -> None:
    seen = observation(result={"content_hash": HASH_B, "source_version": "invented"})
    body = build(observations=[seen]).messages[1]["content"]
    header = body.split("引用元数据：", 1)[1].split("\n", 1)[0]
    assert json.loads(header) == {
        "observation_id": "obs-1", "source_ref": "order:7001",
        "source_version": "3", "content_hash": HASH_A,
    }


def test_uncitable_p3_does_not_invent_version_or_hash() -> None:
    seen = observation().model_copy(update={"source_version": None, "content_hash": None})
    body = build(observations=[seen]).messages[1]["content"]
    header = body.split("引用元数据：", 1)[1].split("\n", 1)[0]
    assert json.loads(header) == {"observation_id": "obs-1", "source_ref": "order:7001"}


def test_a_long_observation_is_excerpted_and_says_where_the_rest_is() -> None:
    """``docs/agent-spec.md:36`` bounds what the model sees and requires the原文 to stay reachable.

    The bound is applied **per field** rather than by cutting characters, and that is what this asserts: a long
    field becomes a pointer naming the observation and the offset, so the excerpt stays well-formed JSON (the
    illegal provider shape ``docs/context-engineering.md:29`` forbids) and the model is told how to follow it. The
    first version of this test expected the word 截断 from a character cut, which also produced a broken JSON
    fragment and could push the structured fields out of the excerpt entirely.
    """
    big = observation(result={"blob": "字" * 20_000})
    packet = build(observations=[big])

    body = packet.messages[1]["content"]
    assert "字" * 100 not in body, "the long field is not dumped into the prompt"
    assert "已省略" in body and "READ_OBSERVATION" in body, "a pointer replaces it"
    assert "obs-1" in body, "the pointer names the observation the rest can be read from"
    assert "offset=" in body, "and where in that observation the field starts"
    assert len(body) < 20_000
    # The excerpt is still parseable data, which a mid-JSON character cut would not be.
    payload = body.split("get_order_context: ", 1)[1]
    assert json.loads(payload)["blob"].startswith("<20000")


def test_two_observations_with_the_same_id_are_one_entry_and_the_drop_is_recorded() -> None:
    """``:27``'s 去重复, with the omission recorded rather than silent."""
    packet = build(observations=[observation(), observation(result={"line_paid_amount": 1})])

    omitted = [entry for entry in packet.omitted_refs if entry["ref"] == "obs-1"]
    assert omitted and any("duplicate" in entry["reason"] for entry in omitted)
    # The surviving P3 entry is the first read, not the second: order is the run's own observation order.
    body = packet.messages[1]["content"]
    assert "2599" in body


# --------------------------------------------------------------------------- trimming


def test_trimming_drops_the_oldest_sections_and_records_each_one() -> None:
    """``:27`` 超限去重复和最旧非关键段，记录omitted_refs及原因.

    P3 and P4 are the layers that may go, and the drop is **per section from the oldest end**, so the newest
    history survives longest. What must not happen is a half-sent section: an omission is a whole entry, and it
    says why.
    """
    observations = [observation(observation_id=f"obs-{index}", source_ref=f"order:{index}") for index in range(6)]
    # One token below the complete rendered request drops the oldest optional index.
    cap = build(observations=observations).input_tokens - 1
    packet = build(
        observations=observations,
        builder=ContextBuilder(system_prompt=SYSTEM, provider_capacity=cap + 512, output_reserve=256),
    )

    assert packet.omitted_refs, "something had to go at this cap"
    assert all(entry["reason"] for entry in packet.omitted_refs), "every omission says why"
    assert packet.input_tokens <= packet.input_cap
    # Oldest first: the kept index entries are the *later* ones.
    kept_indexes = sorted(section for section in packet.selected_refs if section.startswith("index:"))
    assert kept_indexes, "the newest index entries survive"
    assert "index:obs-0" not in packet.selected_refs, "the oldest index entry is the first to go"
    # And nothing half-sent: every kept P4 line is a whole line.
    body = packet.messages[1]["content"]
    assert "【P4·index:" in body


def test_trimming_does_not_change_the_protected_fact_hash() -> None:
    """The 裁剪前后演示, as an assertion (``:41`` 验证必保留字段一致).

    Two packets built from the **same facts** under a generous cap and a tight one must report the same
    ``protected_fact_hash``: whatever the trimming did to the message body, it did not change a preserved value,
    its source, its version or its conflicts. This is the property ``:35`` says the hash exists for — and it is
    explicitly *not* a claim that the facts are correct (``:37``).
    """
    view = FactsView()
    extract_facts(view, observation())
    extract_facts(
        view,
        observation(
            tool="get_shipment_trace",
            source_type=EvidenceSourceType.SHIPMENT,
            source_ref="shipment:7001",
            content_hash=HASH_B,
            observation_id="obs-2",
            result={"carrier_conclusion": "LOST"},
        ),
    )
    observations = [observation(observation_id=f"obs-x{index}", source_ref=f"ref:{index}") for index in range(6)]

    generous = build(view=view, observations=observations)
    tight = build(
        view=view,
        observations=observations,
        # Keep every protected field, but force at least one optional section out.
        builder=ContextBuilder(
            system_prompt=SYSTEM, provider_capacity=generous.input_tokens - 1 + 512, output_reserve=256
        ),
    )

    assert generous.protected_fact_hash == tight.protected_fact_hash
    # And the two packets really are different requests, or the comparison above would be trivial.
    assert generous.messages != tight.messages
    assert tight.omitted_refs, "the tight cap had to drop something"
    # The facts themselves are still all there: trimming drops P3/P4 entries, not P2.
    assert generous.facts == tight.facts
    # The hash is the one the facts view reports, not a second computation.
    assert generous.protected_fact_hash == facts_hash(view)


def test_the_protected_fact_hash_is_not_a_claim_about_correctness() -> None:
    """``:37`` protected_fact_hash…不证明事实本身正确.

    Demonstrated rather than asserted in prose: a fact that is *wrong* — and even one in conflict — still hashes
    stably. The hash proves what was preserved, and a reader who wanted more from it would be misreading it.
    """
    view = FactsView()
    view.note(key="shipment_status", value="SIGNED", observation=observation(tool="get_shipment_trace"))
    first = facts_hash(view)
    # Re-reading the same wrong value does not change what is protected.
    view.note(key="shipment_status", value="SIGNED", observation=observation(tool="get_shipment_trace"))
    assert facts_hash(view) == first


# --------------------------------------------------------------------------- hashes and identity


def test_the_context_hash_covers_the_actual_request() -> None:
    """``:37`` provider适配后的最终请求hash留存 — so a different request hashes differently."""
    first = build()
    assert first.context_hash == build().context_hash, "the same inputs produce the same request"

    other = build(description="包裹破损了，希望退款")
    assert other.context_hash != first.context_hash

    # The system prompt is part of the request, so changing it changes the hash.
    with_other_prompt = build(builder=ContextBuilder(system_prompt=SYSTEM + " 只读。"))
    assert with_other_prompt.context_hash != first.context_hash


def test_the_context_id_is_stable_for_a_run_step_and_its_facts() -> None:
    """A retry of the same step is recognisably the same context (``docs/agent-spec.md:50``)."""
    view = FactsView()
    extract_facts(view, observation())

    first = build(view=view)
    assert first.context_id == build(view=view).context_id
    assert first.context_id != build(view=view, step=2).context_id
    assert first.context_id.startswith("ctx-")


def test_the_packet_records_how_its_tokens_were_counted() -> None:
    """``docs/agent-spec.md:44`` 缺provider准确计数时标ESTIMATED — the mark travels with the number."""
    packet = build()
    assert packet.token_count_mode == "ESTIMATED"
    assert packet.input_tokens > 0
    # An empty view produces an empty facts list, which is the packet being honest about what it rendered rather
    # than a claim that facts are optional. (The first version of this test asserted `packet.facts` was non-empty
    # here, having never added a fact — the builder was right and the assertion was wrong.)
    assert packet.facts == ()

    view = FactsView()
    extract_facts(view, observation())
    assert build(view=view).facts, "the packet carries the facts it rendered, so a snapshot is self-describing"


def test_the_estimate_is_conservative_for_chinese_text() -> None:
    """The estimator errs high on purpose: under-counting lets an over-long request through.

    Four characters per token (the budget hook's ratio) would count 12 Chinese characters as 3 tokens; the real
    figure is nearer 8-12. This is the direction that matters, so it is asserted rather than assumed.
    """
    chinese = "承运商结论为丢失" * 10
    assert estimate_tokens(chinese) > len(chinese) // 4
    assert estimate_tokens("") == 0
