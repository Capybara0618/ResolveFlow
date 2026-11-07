"""Five reviewer situations, diagnosed against the real loop rather than against a mock's answer.

``docs``: ``tasks/dsh-reviewer/04-agent-rag.md`` section 3 asks for a diagnostic set of five hard
cases — a signing conflict, a unilateral damage claim, no applicable policy, a policy exception, and
a targeted question — and section 5 is explicit about what a scripted model may and may not prove:
mock 能证明数据、结构、限制和保存链路，不能证明模型自主识别冲突. So every assertion here is about the
**request the model was actually sent**, the **filtering retrieval actually applied**, and the
**refusals the ABI actually makes**. None of them asserts that a scripted answer equals a desired
sentence, which would keep passing after the property it stands for had broken.

The cases themselves live in ``agent/tests/fixtures/reviewer_diagnostics.json`` so the set can be
read without reading this file; the ``observed`` blocks in that file record what the offline run
showed, including the one confirmed gap (an answered question does not travel into the next run).
"""

from __future__ import annotations

import json
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

import pytest

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.actions import ActionRefusedError, validate_decision
from resolveflow.harness.budget import RunBudget
from resolveflow.harness.control import REASON_POLICY_INDEX_UNAVAILABLE
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.vocabulary import RunFacts
from resolveflow.policies import PolicyIndex, ServedBundle, chunks_of_bundle
from resolveflow.runtime.db import Database
from resolveflow.runtime.runs import RunRequest
from tests.conftest import input_text_of

ROOT = Path(__file__).resolve().parents[3]
DIAGNOSTICS = json.loads((ROOT / "agent" / "tests" / "fixtures" / "reviewer_diagnostics.json").read_text("utf-8"))
CASES: dict[str, dict[str, Any]] = {case["name"]: case for case in DIAGNOSTICS["cases"]}

RUN_ID = "11111111-1111-4111-8111-111111111111"
CASE_ID = "22222222-2222-4222-8222-222222222222"
MERCHANT = "M-1001"
CUSTOMER = "C-2002"


def observation_of(spec: dict[str, Any]) -> ToolObservation:
    return ToolObservation(
        observation_id=spec["observation_id"],
        tool_name=spec["tool_name"],
        source_type=EvidenceSourceType(spec["source_type"]),
        source_ref=spec["source_ref"],
        source_version=spec["source_version"],
        content_hash=spec["content_hash"],
        observed_at="2026-09-29T00:00:00Z",
        result=spec["result"],
    )


class CaseTools:
    """The case's own materials, answered by tool name — the run's reads, nothing else."""

    def __init__(self, case: dict[str, Any]) -> None:
        self._by_tool: dict[str, ToolObservation] = {
            spec["tool_name"]: observation_of(spec) for spec in case["given"].get("observations", [])
        }
        self.called: list[str] = []

    def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolObservation:
        self.called.append(tool_name)
        if tool_name not in self._by_tool:
            raise AssertionError(f"the diagnostic case has no material for {tool_name}")
        return self._by_tool[tool_name]

    def note_trace_page(self) -> None:
        return None

    def close(self) -> None:
        return None


def facts_of(case: dict[str, Any], **overrides: Any) -> RunFacts:
    policy = case["given"].get("policy")
    fields: dict[str, Any] = {
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "input_revision": 1,
        "line_id": case["given"]["line_id"],
        "description": case["given"]["description"],
        "merchant_id": MERCHANT,
        "buyer_id": CUSTOMER,
        "policy_manifest": {
            "merchant_id": MERCHANT,
            "bundle_ids": [policy["bundle_id"]] if policy else [],
            "manifest_hash": policy["manifest_hash"] if policy else "0" * 64,
            "safety_epoch": 1,
        },
    }
    fields.update(overrides)
    return RunFacts(**fields)  # type: ignore[arg-type]


def bundle_of(case: dict[str, Any], *, manifest_hash: str | None = None) -> ServedBundle:
    policy = case["given"]["policy"]
    return ServedBundle(
        bundle_id=policy["bundle_id"],
        merchant_id=MERCHANT,
        version=policy["version"],
        manifest_hash=manifest_hash or policy["manifest_hash"],
        safety_epoch=1,
        rules=list(policy["rules"]),
    )


@pytest.fixture()
def index(agent_db: Database, stub_embedder: object) -> PolicyIndex:
    """A real index over every diagnostic bundle, each under its own manifest hash."""
    built = PolicyIndex(agent_db)
    for case in CASES.values():
        if "policy" in case["given"]:
            built.build(bundle_of(case), embedder=stub_embedder)  # type: ignore[arg-type]
    # A second merchant's damage bundle, deliberately indexed: the filter has to keep it out.
    built.build(
        ServedBundle(
            bundle_id="policy-damage-2026.09",
            merchant_id="M-2002",
            version="2026.09",
            manifest_hash="c" * 64,
            safety_epoch=1,
            rules=[{"rule_id": "R-DMG-001", "title": "到货破损", "text": "客户提交的到货破损图片经核验有效时，可全额退款。"}],
        ),
        embedder=stub_embedder,  # type: ignore[arg-type]
    )
    return built


def drive(
    case: dict[str, Any],
    script: list[dict[str, Any]],
    *,
    index: PolicyIndex | None = None,
    stub_embedder: object | None = None,
    context_provider_capacity: int = 32768,
    **overrides: Any,
) -> tuple[Any, MockModelClient, CaseTools]:
    model = MockModelClient(script=script)
    tools = CaseTools(case)
    runner = AgentScopeRunner(
        model=model,
        tools=tools,  # type: ignore[arg-type]
        facts=facts_of(case, **overrides),
        budget=RunBudget(),
        context_provider_capacity=context_provider_capacity,
        policy_index=index,
        policy_embedder=stub_embedder,  # type: ignore[arg-type]
    )
    return runner.run(), model, tools


def read(tool_name: str, **arguments: Any) -> dict[str, Any]:
    return {"kind": "READ_TOOL", "tool_name": tool_name, "arguments": arguments, "reasoning": "read"}


def search(query: str, **arguments: Any) -> dict[str, Any]:
    return {"kind": "SEARCH_POLICY", "query": query, "arguments": arguments, "reasoning": "look it up"}


def propose(action: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "PROPOSE",
        "case_type": "LOGISTICS",
        "recommended_action": action,
        "reason_codes": ["DIAGNOSTIC"],
        "summary": "诊断用例",
        "reasoning": "diagnostic",
    }
    body.update(extra)
    return body


def ask(decision: dict[str, Any]) -> dict[str, Any]:
    return decision


# --------------------------------------------------------------------------- the set itself


def test_the_diagnostic_set_names_the_five_cases_the_manual_asks_for() -> None:
    assert [case["name"] for case in DIAGNOSTICS["cases"]] == [
        "signed_conflict",
        "unilateral_damage",
        "no_applicable_policy",
        "policy_exception",
        "targeted_question",
    ]
    for case in DIAGNOSTICS["cases"]:
        assert case["situation"], f"{case['name']} does not say what situation it is"
        assert case["forbidden"], f"{case['name']} does not say what must not happen"
        assert case["expected_retained_sources"], f"{case['name']} does not say what must be kept"
        assert case["observed"]["status"], f"{case['name']} has no recorded observation"


# --------------------------------------------------------------------------- 签收冲突


def test_a_signing_conflict_reaches_the_model_with_both_sources_and_their_versions(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """两来源与版本进入上下文.

    The run reads the shipment and the case's material, searches the pinned policy and hands over.
    What is asserted is the *request*: the carrier's own conclusion with the source it came from,
    the customer's words, and no claim anywhere that the parcel was lost.
    """
    case = CASES["signed_conflict"]
    script = [
        read("get_shipment_trace", limit=3),
        read("get_case_evidence"),
        search("已签收 客户未收到 人工核验", top_k=5),
        propose("MANUAL_REVIEW"),
    ]
    result, model, tools = drive(case, script, index=index, stub_embedder=stub_embedder)

    assert result.completed is True  # type: ignore[attr-defined]
    assert tools.called == ["get_shipment_trace", "get_case_evidence"]
    # Turn 3 is the request that carries both sources and no policy yet: exactly the packet in which a
    # loss claim would have to come from a source rather than from retrieved text.
    two_sources = input_text_of(model, 3)
    for forbidden in case["packet_excludes"]:
        assert forbidden not in two_sources, (
            f"the request contains {forbidden!r}: nothing in this case says the parcel was lost, and a "
            "packet that does is how a claim becomes a carrier conclusion"
        )
    assert "shipment_carrier_conclusion=DELIVERED [AUTHORITY" in two_sources
    # The last request is the one carrying everything the run has: facts, observations and the
    # rules the search returned.
    sent = input_text_of(model, -1)
    for expected in case["packet_contains"]:
        assert expected in sent, f"the request the model received has no {expected!r}"
    # The customer's own words travel as the run's request, which is what makes the contradiction
    # visible to a reader: an authority statement and a claim beside it.
    assert case["given"]["description"] in sent


def test_the_signing_conflict_is_retrieved_from_the_pinned_bundle_only(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """The rule that governs this situation is reachable, and nothing from another bundle is."""
    case = CASES["signed_conflict"]
    script = [search(case["retrieval"]["query"], top_k=case["retrieval"]["top_k"]), propose("MANUAL_REVIEW")]
    result, _model, _tools = drive(case, script, index=index, stub_embedder=stub_embedder)

    hits = result.observations[0].result["hits"]  # type: ignore[attr-defined]
    returned = {hit["rule_id"] for hit in hits}
    assert set(case["retrieval"]["must_include_rules"]) <= returned
    for hit in hits:
        assert hit["bundle_id"] == case["given"]["policy"]["bundle_id"]
        assert hit["bundle_id"] not in case["retrieval"]["must_not_return_bundles"]
        # Every member a citation needs, or the model cannot cite what it was shown.
        assert {"observation_id", "source_ref", "source_version", "content_hash"} <= set(hit) or {
            "bundle_id",
            "version",
            "rule_id",
            "chunk_id",
            "content_hash",
        } <= set(hit)


# --------------------------------------------------------------------------- 单方损坏


def test_a_unilateral_damage_claim_never_reads_as_verified(stub_embedder: object) -> None:
    """材料未核验就只能是材料.

    Nothing in the packet may assert that the damage was confirmed, and the evidence tool hands over
    references rather than text, so there is no body for a reader to over-trust either.
    """
    case = CASES["unilateral_damage"]
    accepted = case["targeted_question"]
    decision = {
        "kind": "ASK_CUSTOMER",
        "reason_codes": ["DAMAGE_NOT_VERIFIED"],
        "questions": [
            {
                "question_id": accepted["question_id"],
                "field": accepted["field"],
                "prompt": "请补充能判断破损事实的材料（破损部位与外包装），并说明核验方式。",
            }
        ],
        "reasoning": "缺一件能判断破损事实的材料",
    }
    result, model, _tools = drive(case, [read("get_case_evidence"), ask(decision)])

    sent = input_text_of(model, -1)
    for expected in case["packet_contains"]:
        assert expected in sent, f"the request has no {expected!r}"
    for forbidden in case["packet_excludes"]:
        assert forbidden not in sent, f"the request claims {forbidden!r}, which nothing in this case supports"
    # The tool's own body carries no material text, which is the honest limit of this read.
    observation = result.observations[0]  # type: ignore[attr-defined]
    assert "text" not in json.dumps(observation.result)
    assert observation.result["evidence"][0]["observation_id"] == "ev-damage-1"


# --------------------------------------------------------------------------- 无适用政策


def test_a_query_without_a_match_returns_nothing_rather_than_the_closest_other_bundle(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """换商户/换最新bundle、随便引用最高分条款 is what must not happen."""
    case = CASES["no_applicable_policy"]
    script = [search(case["retrieval"]["query"], top_k=case["retrieval"]["top_k"]), propose("REQUEST_INFO")]
    result, _model, _tools = drive(case, script, index=index, stub_embedder=stub_embedder)

    observation = result.observations[0]  # type: ignore[attr-defined]
    hits = observation.result["hits"]
    for hit in hits:
        assert hit["bundle_id"] not in case["retrieval"]["must_not_return_bundles"], (
            f"retrieval returned {hit['bundle_id']}, which this case is not pinned to"
        )
        assert hit["bundle_id"] == case["given"]["policy"]["bundle_id"]
    # Zero hits is a successful read, not an error, and the run may still end with a decision.
    assert observation.error is None
    assert observation.result["hit_count"] == len(hits)
    assert result.completed is True  # type: ignore[attr-defined]


def test_an_unindexed_pin_reports_its_own_reason_and_not_a_broken_tool(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """索引未就绪与"政策没有规定"是两件事，必须分开。"""
    case = CASES["no_applicable_policy"]
    script = [search("商品功能异常 退款")]
    result, _model, _tools = drive(
        case,
        script,
        index=index,
        stub_embedder=stub_embedder,
        policy_manifest={
            "merchant_id": MERCHANT,
            "bundle_ids": [case["given"]["policy"]["bundle_id"]],
            "manifest_hash": "f" * 64,
            "safety_epoch": 1,
        },
    )

    assert result.completed is False  # type: ignore[attr-defined]
    assert result.reason_code == REASON_POLICY_INDEX_UNAVAILABLE  # type: ignore[attr-defined]
    assert case["index_not_ready"]["reason_code"] == REASON_POLICY_INDEX_UNAVAILABLE


# --------------------------------------------------------------------------- 政策例外


def test_the_exception_survives_chunking_retrieval_and_the_request(
    index: PolicyIndex, stub_embedder: object
) -> None:
    """条件与例外必须完整保留：切块不切句，检索同时召回，请求里看得见。"""
    case = CASES["policy_exception"]
    stored = {rule["rule_id"]: rule for rule in case["given"]["policy"]["rules"]}

    # 1. Chunking: each rule is one chunk whose text is the stored text, condition and all.
    chunks = {
        chunk.rule_id: chunk
        for chunk in chunks_of_bundle(case["given"]["policy"]["bundle_id"], list(stored.values()))
    }
    for rule_id in case["chunk_text_intact"]:
        assert chunks[rule_id].text == stored[rule_id]["text"], "the exception was cut or reworded by chunking"
        assert "例外" in chunks[rule_id].text

    script = [
        read("get_order_context"),
        read("get_shipment_trace", limit=3),
        search(case["retrieval"]["query"], top_k=case["retrieval"]["top_k"]),
        # MANUAL_REVIEW rather than REFUND: a REFUND must cite the exception rule and an observation,
        # and a static script cannot build a citation whose content hash comes from the index. The
        # diagnostic is about what the request carries, which is the same either way.
        propose("MANUAL_REVIEW"),
    ]
    result, model, _tools = drive(case, script, index=index, stub_embedder=stub_embedder,
                                 context_provider_capacity=32768)

    hits = {hit["rule_id"]: hit for hit in result.observations[2].result["hits"]}  # type: ignore[attr-defined]
    for rule_id in case["retrieval"]["must_include_rules"]:
        assert rule_id in hits, f"{rule_id} was not retrieved for the query that returns the rule it limits"

    sent = input_text_of(model, -1)
    # The facts the exception turns on, with their sources, and the exception text itself.
    assert "order_paid_amount_minor=600000" in sent
    assert "shipment_carrier_conclusion=LOST" in sent
    assert "R-LOST-EXC-001" in sent
    assert "500000" in sent, "the exception's threshold is not in the request the model received"


# --------------------------------------------------------------------------- 针对性追问


def test_a_targeted_question_must_name_its_field_and_a_decision_may_not_ask_four() -> None:
    """提问对应明确缺口；泛泛追问与无穷追问在ABI层就被拒。"""
    case = CASES["targeted_question"]
    rules = case["question_rules"]

    accepted = validate_decision(rules["accepted"])
    assert accepted.kind == "ASK_CUSTOMER"
    assert accepted.questions[0].field
    assert accepted.questions[0].question_id

    for refused in rules["refused"]:
        with pytest.raises((ActionRefusedError, ValueError)) as refusal:
            validate_decision(refused["decision"])
        assert refused["reason_contains"] in str(refusal.value), (
            f"the refusal for {refused['decision']} does not say why: {refusal.value}"
        )
    assert len(rules["accepted"]["questions"]) <= rules["max_questions_per_decision"]


def test_the_dispatch_can_carry_revision_bound_answers_without_changing_citation_identity() -> None:
    """The diagnosed gap now has a bounded optional snapshot; integration tests assert the real packet."""
    case = CASES["targeted_question"]
    assert case["observed"]["status"] == "FIXED_INPUT"

    fields = {field.name for field in dataclass_fields(RunRequest)}
    assert "review_context" in fields
    # What *does* travel, so the gap is stated precisely rather than as "no context at all".
    assert {"description", "requested_actions", "evidence_refs"} <= fields


def test_the_diagnostics_cases_are_independent_of_the_demonstration_samples() -> None:
    """诊断集有自己的数据，不修改第二批演示样本。"""
    sample_ids = {
        spec["observation_id"]
        for case in CASES.values()
        for spec in case["given"].get("observations", [])
    }
    manifest = json.loads((ROOT / "reports" / "reviewer-demo" / "samples.json").read_text("utf-8"))
    demonstration_ids = {sample["case_id"] for sample in manifest["samples"]}
    # The diagnostics name their own observations and their own cases; no case id is reused as an
    # observation id, and the demonstration manifest is read but never written.
    assert sample_ids
    assert not (sample_ids & demonstration_ids)
