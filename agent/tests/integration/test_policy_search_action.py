"""C07.1: the run's ``SEARCH_POLICY`` action actually executes, against the run's own pinned index.

The gap this closes was structural, not a missing feature: ``actions._check_policy_search`` validated the
action's shape and ``budget.reserve_local_read`` existed with the comment "policy search and READ_OBSERVATION,
which are not MCP calls", but **nothing executed either** — a validated ``SEARCH_POLICY`` had no executor and the
local-read budget was unspendable. So these tests are about the wiring: that the action reaches the index, that
it spends the budget it is supposed to spend, that the model is shown citable rules, and that the refusal paths
report *their own* reason rather than a generic tool failure.

They drive the **real loop** (``AgentScopeRunner`` over AgentScope) with a scripted model, because "the executor
is registered with the SDK's toolkit and the permission gate lets it through" is a claim about the loop, and a
test that called the bridge's ``call`` directly would pass even if it had never been registered.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.control import REASON_POLICY_INDEX_UNAVAILABLE
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.vocabulary import RunFacts
from resolveflow.policies import PolicyIndex, ServedBundle
from resolveflow.runtime.db import Database
from tests.conftest import input_text_of

BUNDLE = ServedBundle(
    bundle_id="policy-logistics-2026.09",
    merchant_id="M-1001",
    version="2026.09",
    manifest_hash="b" * 64,
    safety_epoch=2,
    rules=[
        {
            "rule_id": "R-LOST-001",
            "title": "承运商判定丢失",
            "text": "承运商结论为 LOST 且无有效签收记录时，可按该订单行支付金额全额退款。",
        },
        {
            "rule_id": "R-SIGNED-001",
            "title": "已签收",
            "text": "存在有效签收记录时不予退款；客户主张未收到时须由人工核验后再决定。",
        },
    ],
)


class _NoTools:
    """A ``ToolExecutor`` that fails loudly: a policy search must never reach the MCP boundary."""

    def call_tool(self, **_: object) -> object:
        raise AssertionError("a policy search reached the MCP tool executor; it is a local read")

    def note_trace_page(self) -> None:
        raise AssertionError("a policy search is not a paged tool read")

    def close(self) -> None:
        return None


def facts(**overrides: object) -> RunFacts:
    fields: dict[str, object] = {
        "run_id": "11111111-1111-4111-8111-111111111111",
        "case_id": "22222222-2222-4222-8222-222222222222",
        "input_revision": 1,
        "line_id": "7001",
        "description": "包裹丢了，希望退款",
        "merchant_id": "M-1001",
        "customer_id": "C-2002",
        "policy_manifest": {
            "merchant_id": BUNDLE.merchant_id,
            "bundle_ids": [BUNDLE.bundle_id],
            "manifest_hash": BUNDLE.manifest_hash,
            "safety_epoch": BUNDLE.safety_epoch,
        },
    }
    fields.update(overrides)
    return RunFacts(**fields)  # type: ignore[arg-type]


def propose() -> dict[str, object]:
    """A terminal proposal for runs about *searching*, not about refunding.

    ``MANUAL_REVIEW`` rather than ``REFUND`` since C08.1c: a refund must cite an evidence observation **and** a policy
    rule, and this file's runs have no tools at all (``_NoTools``), so a refund here could only be refused. The
    citation rules are checked in ``tests/unit/test_proposal_verifier.py``; what this file proves is that the rule a
    search returned carries every member a citation needs, and that the model was shown them.
    """
    return {
        "kind": "PROPOSE",
        "case_type": "LOGISTICS",
        "recommended_action": "MANUAL_REVIEW",
        "reason_codes": ["LOST_CONFIRMED"],
        "summary": "根据检索条款建议商家复核现有材料",
        "reasoning": "policy says refund",
    }


def search(query: str, **arguments: object) -> dict[str, object]:
    return {"kind": "SEARCH_POLICY", "query": query, "arguments": dict(arguments), "reasoning": "look it up"}


@pytest.fixture()
def index(agent_db: Database, stub_embedder: object) -> PolicyIndex:
    built = PolicyIndex(agent_db)
    built.build(BUNDLE, embedder=stub_embedder)  # type: ignore[arg-type]
    return built


def run(index: PolicyIndex, model: MockModelClient, stub_embedder: object, **overrides: object) -> object:
    budget = overrides.pop("budget", RunBudget())
    runner = AgentScopeRunner(
        model=model,
        tools=_NoTools(),  # type: ignore[arg-type]
        facts=facts(**overrides),
        budget=budget,  # type: ignore[arg-type]
        policy_index=index,
        policy_embedder=stub_embedder,
    )
    return runner.run()


def test_a_search_policy_action_executes_and_the_rules_reach_the_model(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """The whole point: a validated ``SEARCH_POLICY`` now has somewhere to go, and its result is visible."""
    model = MockModelClient(script=[search("承运商判定丢失 全额退款"), propose()])

    result = run(index, model, stub_embedder)

    assert result.completed is True  # type: ignore[attr-defined]
    # The observation the run records is a policy read, not an MCP call.
    assert len(result.observations) == 1  # type: ignore[attr-defined]
    observation = result.observations[0]  # type: ignore[attr-defined]
    assert observation.source_type.value == "POLICY_RULE"
    assert observation.source_ref == f"policy:{BUNDLE.bundle_id}"
    assert observation.result is not None and observation.result["hit_count"] >= 1
    trace = next(t for t in result.trajectory if t.get("action") == "search_policy")
    assert trace["hits"] == len(observation.result["hits"]) == observation.result["hit_count"]

    hit = observation.result["hits"][0]
    # Every member a citation needs, and they are the *index's* values, not something this side re-derived from
    # the model's answer (docs/agent-spec.md:52: ref must be actually visible).
    assert set(hit) >= {"bundle_id", "version", "rule_id", "chunk_id", "content_hash", "source_ref"}
    assert hit["bundle_id"] == BUNDLE.bundle_id
    assert hit["version"] == BUNDLE.version
    assert hit["source_ref"] == f"policy:{BUNDLE.bundle_id}/{hit['chunk_id']}"

    # Mandatory P2 renders a run-local P# alias; its expansion must bind every
    # original citation member. Full hashes are retained, not repeated in prompts.
    sent = input_text_of(model, 1)
    assert hit["rule_id"] in sent, f"the cited rule is not in the request the model received: {sent}"
    aliases = model.sent_contexts[1].references
    alias = next(key for key, value in aliases.items()
                 if value["kind"] == "policy" and value["ref"]["rule_id"] == hit["rule_id"])
    if "【P2·policy_table】" in sent:
        import json
        table = json.loads(sent.split("【P2·policy_table】", 1)[1].splitlines()[1])
        rows = [dict(zip(table["fields"], row, strict=True)) for row in table["rows"]]
        visible = next(row for row in rows if row["ref"] == alias)
        assert visible["rule_id"] == hit["rule_id"] and visible["text"] == hit["text"]
        assert table["bundle_id"] == hit["bundle_id"] and table["version"] == hit["version"]
    else:
        assert f'"ref":"{alias}"' in sent, "a citation alias must be visible in the actual request"
    assert aliases[alias]["ref"] == {key: hit[key] for key in
                                    ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")}


def test_a_search_spends_a_local_read_and_a_search_attempt(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """``docs/agent-spec.md:40`` budgets 16 attempts and 8 local reads, and this action is counted in both."""
    model = MockModelClient(script=[search("承运商判定丢失"), propose()])

    result = run(index, model, stub_embedder)

    # Before C07.1 the outcome derived `tool_attempts` from the observation list and read `local_reads` off a
    # counter nothing incremented, so a policy search would have been invisible in the local-read budget.
    assert result.spend.tool_attempts == 1  # type: ignore[attr-defined]
    assert result.spend.local_reads == 1  # type: ignore[attr-defined]


def test_small_bound_set_reaches_investigation_whole_even_when_topk_is_one(index, stub_embedder):
    model = MockModelClient(script=[search("普通在途", top_k=1), propose()])
    result = run(index, model, stub_embedder)
    observation = result.observations[0]
    assert observation.result["retrieval_context"] == {"mode": "COMPLETE_SMALL_SET", "count": 2}
    assert {hit["rule_id"] for hit in observation.result["hits"]} == {"R-LOST-001", "R-SIGNED-001"}
    sent = input_text_of(model, 1)
    assert all(rule["text"] in sent and rule["title"] in sent for rule in BUNDLE.rules)
    assert "不能扩大条款的适用对象或情形" in sent
    assert result.spend.local_reads == 1 and result.spend.tool_attempts == 1


def test_the_budget_position_reaches_the_client_but_not_the_provider_request(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """Where the local-read position is visible, and where it deliberately is not (C08.1a).

    The run's structured view — the ``context`` a :class:`~resolveflow.harness.model.ModelClient` is called with — is
    the channel that exists for the run's own bookkeeping, so the position is asserted there. It is **not** in the
    provider request, and that is the design rather than an omission: ``docs/context-engineering.md:15-21`` fixes the
    request to P0–P4 (system/schema, request, facts, current observations, older index) and no layer carries a budget,
    while the bound itself is the harness's to enforce — ``docs/agent-harness.md:3`` puts budget and termination in
    the domain Harness rather than in the model.

    Both halves are pinned so a future change to either is deliberate: the assertion kept its subject (the budget is
    counted and visible) and gained the boundary that the model is not asked to police its own budget.
    """
    model = MockModelClient(script=[search("承运商判定丢失"), propose()])

    run(index, model, stub_embedder, budget=RunBudget(local_reads=3))

    context = model.contexts[1]
    assert context is not None, "the run's structured view is what a client is handed"
    assert context["budget"]["local_reads_made"] == 1
    assert context["budget"]["local_reads_allowed"] == 3
    assert "local_reads_allowed" not in input_text_of(model, 1), "the request is P0–P4, not the run's ledger"


def test_the_local_read_bound_stops_the_run_and_names_itself(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """The bound that ran out has to be the bound the outcome reports (``docs/agent-harness.md:45``)."""
    model = MockModelClient.always(search("承运商判定丢失"))

    result = run(index, model, stub_embedder, budget=RunBudget(local_reads=1))

    assert result.completed is False  # type: ignore[attr-defined]
    assert result.reason_code == "BUDGET_LOCAL_READS"  # type: ignore[attr-defined]
    assert result.spend.local_reads == 1  # type: ignore[attr-defined]


def test_a_run_whose_policy_is_not_indexed_stops_with_its_own_reason(
    index: PolicyIndex, stub_embedder: object, agent_db: Database
) -> None:
    """索引未就绪不搜旧版本 — and the run says *that*, rather than reporting a broken tool.

    ``POLICY_INDEX_NOT_READY`` is its own code because ``docs/policy-rag.md:23`` gives it its own handling: the
    run may retry until its deadline or escalate. A caller reading ``TOOL_FAILED`` would treat it as an
    environment fault that will not improve, which is the opposite of what it is.
    """
    model = MockModelClient.always(search("承运商判定丢失"))
    # The pin names a hash nobody indexed: the bundle is READY, at a different version.
    pinned = facts(
        policy_manifest={
            "merchant_id": BUNDLE.merchant_id,
            "bundle_ids": [BUNDLE.bundle_id],
            "manifest_hash": "f" * 64,
            "safety_epoch": BUNDLE.safety_epoch,
        }
    )

    result = run(index, model, stub_embedder, **{"policy_manifest": pinned.policy_manifest})

    assert result.reason_code == REASON_POLICY_INDEX_UNAVAILABLE  # type: ignore[attr-defined]
    assert result.spend.local_reads == 1  # type: ignore[attr-defined]
    trajectory = [entry for entry in result.trajectory if entry["action"] == "search_policy"]  # type: ignore[attr-defined]
    # `REFUSED` with the run's own reason code, rather than a distinct outcome label per refusal kind. The
    # refactor that put both local reads on one base class unified the labels, and the reason code plus
    # `hash_mismatch` carry the same information in a form that is consistent across the two actions.
    assert trajectory and trajectory[0]["outcome"] == "REFUSED"
    assert trajectory[0]["reason_code"] == REASON_POLICY_INDEX_UNAVAILABLE
    assert trajectory[0]["hash_mismatch"] is True


def test_a_search_that_matches_nothing_is_a_successful_read_not_an_error(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """ "The policy is silent" and "the source was unreachable" are different facts and must not look alike."""
    model = MockModelClient(script=[search("完全不相关的查询词"), propose()])

    result = run(index, model, stub_embedder)

    observation = result.observations[0]  # type: ignore[attr-defined]
    # The observation is *about* policy whether or not anything matched. (With two short rules a fuzzy stub
    # embedder may still return something, so the assertion is on the shape, not on hit_count == 0.)
    assert observation.source_type.value == "POLICY_RULE"
    assert observation.result is not None
    assert "hits" in observation.result and "query" in observation.result


def test_the_model_cannot_choose_which_merchant_or_version_is_searched(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """The ABI refuses identity members in a ``SEARCH_POLICY``'s arguments, so a run cannot widen its scope.

    ``validate_decision`` rejects ``merchant_id``/``bundle_ids`` as identity members before the action runs; this
    asserts the refusal still fires *through the loop*, which is where it matters — the check is only a boundary
    if the loop actually consults it.
    """
    model = MockModelClient.always(
        {
            "kind": "SEARCH_POLICY",
            "query": "承运商判定丢失",
            "arguments": {"merchant_id": "M-2002"},
            "reasoning": "try another merchant",
        }
    )

    result = run(index, model, stub_embedder)

    assert result.completed is False  # type: ignore[attr-defined]
    assert result.reason_code == "IDENTITY_REFUSED"  # type: ignore[attr-defined]
    assert result.observations == ()  # type: ignore[attr-defined]


def test_encoder_mismatch_becomes_named_safe_handover(index, stub_embedder):
    # A complete small-set read does not use an encoder. Exercise the ranked path
    # with a genuinely larger policy rather than requiring irrelevant embedding.
    index.build(replace(BUNDLE, rules=[{**BUNDLE.rules[0], "rule_id": f"large-{i}"}
                                      for i in range(9)]), embedder=stub_embedder)
    model = MockModelClient(script=[search("物流没送到")])
    result = run(index, model, replace(stub_embedder, revision="mismatched-query-model"))
    assert result.completed is False
    assert result.reason_code == REASON_POLICY_INDEX_UNAVAILABLE
    assert model.calls == 1
    assert not result.observations


def test_large_set_keeps_dense_topk_and_original_rule_bytes(index, stub_embedder):
    rules = [{**BUNDLE.rules[0], "rule_id": f"large-{i}"} for i in range(9)]
    index.build(replace(BUNDLE, rules=rules), embedder=stub_embedder)
    model = MockModelClient(script=[search("丢失", top_k=1), propose()])
    result = run(index, model, stub_embedder)
    observation = result.observations[0]
    assert observation.result["retrieval_context"] == {"mode": "RANKED"}
    assert len(observation.result["hits"]) == 1
    assert observation.result["hits"][0]["text"] == BUNDLE.rules[0]["text"]
