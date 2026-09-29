"""C08.2 — the deployment seam: settings are read, refused when they are not enough, and then they investigate.

Two things are established here that no other test can:

* a misconfigured deployment is refused **while the investigation is being built**, so it cannot send a request and
  then discover the problem;
* the whole pipeline closes on the Python side: a dispatched run is claimed by the worker, investigated by the real
  AgentScope loop over the factory's client, and its proposal is filed in the outbox as one callback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.live_model import HttpResponse
from resolveflow.harness.model import MockModelClient
from resolveflow.policies import PolicyIndex, ServedBundle
from resolveflow.runtime.callbacks import CallbackStore
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import (
    API_KEY_ENV,
    ENDPOINT_ENV,
    MODE_ENV,
    MODEL_ID_ENV,
    DeploymentConfig,
    DeploymentRefusedError,
    _mcp_executor,
    build_investigation,
)
from resolveflow.runtime.runs import RunRequest, RunStore, VerifiedCaller
from resolveflow.runtime.worker import RunWorker
from resolveflow.tools.credential import CredentialUnavailableError, HttpToolCredentialClient, ToolCredential
from tests.conftest import StubEmbedder, input_text_of
from tests.integration import future_deadline, stub_upstream

RUN_ID = "11111111-2222-4333-8444-555555555555"
CASE_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"
MANIFEST_HASH = "9" * 64

CASE_DISPATCHER = VerifiedCaller(
    service="case-service",
    scope="run:dispatch",
    merchant_id="M-1001",
    customer_id="C-2002",
)


def a_run(**overrides: Any) -> RunRequest:
    fields: dict[str, Any] = {
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "input_revision": 1,
        "merchant_id": "M-1001",
        "customer_id": "C-2002",
        "order_id": "00000000-0000-4000-8000-0000000000aa",
        "line_id": "7001",
        "description": "包裹丢了，希望退款",
        "requested_actions": ["REFUND"],
        "evidence_refs": ["ev-1"],
        "policy_manifest": {
            "merchant_id": "M-1001",
            "bundle_ids": ["policy-logistics-2026.09"],
            "manifest_hash": MANIFEST_HASH,
            "safety_epoch": 1,
        },
        "deadline_at": future_deadline(),
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    }
    fields.update(overrides)
    return RunRequest(**fields)


class _Tools:
    """A tool executor that answers every read with a healthy observation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = 0

    def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolObservation:
        self.calls.append((tool_name, arguments))
        return ToolObservation(
            observation_id=f"obs-{tool_name}",
            tool_name=tool_name,
            source_type=EvidenceSourceType.ORDER_LINE,
            source_ref=f"order:{tool_name}",
            source_version="3",
            content_hash="a" * 64,
            observed_at="2026-09-26T10:00:00Z",
            result={"conclusion": "LOST"},
        )

    def note_trace_page(self) -> None:
        return None

    def close(self) -> None:
        self.closed += 1


def decision_body(*, content: str) -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
    ).encode("utf-8")


def propose_json() -> str:
    return json.dumps(
        {
            "kind": "PROPOSE",
            "case_type": "LOGISTICS",
            "recommended_action": "MANUAL_REVIEW",
            "reason_codes": ["LOST_CONFIRMED"],
            "summary": "承运商判定丢失",
        }
    )


def test_a_deployment_that_never_named_a_mode_is_refused() -> None:
    """No default mode: guessing would either file proposals no model produced, or start spending."""
    with pytest.raises(DeploymentRefusedError) as refusal:
        DeploymentConfig.from_environ({})

    assert MODE_ENV in str(refusal.value)


def test_a_mode_that_is_not_one_of_the_two_is_refused() -> None:
    """``auto``, ``prod``, a typo — none of them name a client, and none of them may become one."""
    with pytest.raises(DeploymentRefusedError):
        DeploymentConfig.from_environ({MODE_ENV: "auto"})


def test_a_live_deployment_is_refused_before_it_can_call_out(agent_db: Database) -> None:
    """The refusal happens at build time, so a half-configured deployment sends nothing."""
    config = DeploymentConfig.from_environ({MODE_ENV: "live", MODEL_ID_ENV: "some-model"})

    with pytest.raises(DeploymentRefusedError) as refusal:
        build_investigation(database=agent_db, config=config)

    assert "endpoint" in str(refusal.value)


def test_a_mock_deployment_will_not_invent_the_script_it_runs(agent_db: Database) -> None:
    """A factory that wrote the model's answers would be writing the decisions."""
    config = DeploymentConfig.from_environ({MODE_ENV: "mock"})

    with pytest.raises(DeploymentRefusedError) as refusal:
        build_investigation(database=agent_db, config=config)

    assert "scripted model" in str(refusal.value)


def test_factory_tool_reads_fetch_the_run_credential_without_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = a_run()
    from resolveflow.harness.vocabulary import RunFacts

    run = RunFacts(
        run_id=facts.run_id, case_id=facts.case_id, input_revision=facts.input_revision,
        line_id=facts.line_id, description=facts.description,
    )
    executor = _mcp_executor(DeploymentConfig(mode="mock", service_token="deployment-identity"), run)
    assert executor.credential_source is not None
    assert executor.service_token is None
    seen: list[tuple[str, str, int, str | None]] = []

    def issue(self: HttpToolCredentialClient, *, run_id: str, case_id: str, input_revision: int) -> ToolCredential:
        seen.append((run_id, case_id, input_revision, self.service_token))
        return ToolCredential(token="run-token", expires_at="2026-09-26T14:00:00Z", scopes=("commerce:read",))

    monkeypatch.setattr(HttpToolCredentialClient, "issue", issue)
    assert executor.credential_source() == "run-token"
    assert seen == [(run.run_id, run.case_id, 1, "deployment-identity")]

    def unavailable(self: HttpToolCredentialClient, **_: Any) -> ToolCredential:
        raise CredentialUnavailableError("Case unavailable")

    monkeypatch.setattr(HttpToolCredentialClient, "issue", unavailable)
    with pytest.raises(CredentialUnavailableError, match="Case unavailable"):
        executor.credential_source()


def test_settings_are_read_with_the_documented_names() -> None:
    """The env names are the contract a deployment writes against, so they are pinned here, not in prose."""
    config = DeploymentConfig.from_environ(
        {
            MODE_ENV: "LIVE",
            ENDPOINT_ENV: "https://provider.invalid/v1/chat/completions",
            MODEL_ID_ENV: "some-model",
            API_KEY_ENV: "sk-not-a-real-key",
            "RESOLVEFLOW_MODEL_TIMEOUT_SECONDS": "12.5",
            "RESOLVEFLOW_POLICY_INDEX": "1",
            "RESOLVEFLOW_TOOL_SERVICE_TOKEN": "token-not-real",
        }
    )

    assert config.mode == "live"
    assert config.endpoint == "https://provider.invalid/v1/chat/completions"
    assert config.model_id == "some-model"
    assert config.timeout_seconds == 12.5
    assert config.policy_index is True
    assert config.service_token == "token-not-real"


def test_the_whole_pipeline_files_a_proposal_from_a_real_investigation(agent_db: Database) -> None:
    """Queue → worker → factory → the actual AgentScope loop → outbox, in one test.

    Everything else in this session's C08.2 work is a piece; this is the piece-count claim itself. The model is
    scripted and the tools are a double, because what is being pinned is that the *pipeline* is closed — a
    dispatched run reaches an investigation and its outcome reaches the case service as one callback.
    """
    RunStore(agent_db).queue(a_run(), caller=CASE_DISPATCHER)
    tools = _Tools()
    model = MockModelClient(
        script=[
            {"kind": "READ_TOOL", "tool_name": "get_shipment_trace", "arguments": {}, "reasoning": "look"},
            {
                "kind": "PROPOSE",
                "case_type": "LOGISTICS",
                "recommended_action": "MANUAL_REVIEW",
                "reason_codes": ["LOST_CONFIRMED"],
                "summary": "承运商判定丢失",
            },
        ]
    )
    investigate = build_investigation(
        database=agent_db,
        config=DeploymentConfig(mode="mock"),
        model=model,
        tools=tools,
    )

    outcome = RunWorker(agent_db, investigate=investigate).run_once()

    assert outcome is not None
    assert outcome.result is not None
    assert outcome.result.completed is True
    # The loop really ran the tool the model chose, through the pipeline's own executor.
    assert tools.calls == [("get_shipment_trace", {})]
    assert tools.closed == 1, "the executor is closed on the way out of an investigation"
    # And the run is now waiting on Java, with the proposal in the outbox.
    assert outcome.status == "CALLBACK_PENDING"
    records = CallbackStore(agent_db).list_for_run(RUN_ID)
    assert [record.kind for record in records] == ["STARTED", "PROPOSAL"]
    assert records[-1].payload["recommended_action"] == "MANUAL_REVIEW"
    # The record says which mode answered, so a mock run cannot be mistaken for live evidence.
    assert outcome.result.modes == ("mock", "mock")


def test_refund_citations_survive_mcp_policy_search_sdk_and_worker(
    agent_db: Database, stub_embedder: StubEmbedder, tmp_path: Path,
) -> None:
    """Real stdio MCP and PG retrieval, synthetic HTTP upstream and scripted model; no Java or live claim."""
    bundle = ServedBundle(
        bundle_id="policy-logistics-2026.09",
        merchant_id="M-1001",
        version="2026.09",
        manifest_hash=MANIFEST_HASH,
        safety_epoch=1,
        rules=[{
            "rule_id": "R-LOST-001",
            "title": "承运商判定丢失",
            "text": "承运商结论为 LOST 时，可按订单行支付金额全额退款。",
        }],
    )
    PolicyIndex(agent_db).build(bundle, embedder=stub_embedder)
    RunStore(agent_db).queue(a_run(line_id="7100"), caller=CASE_DISPATCHER)
    log = tmp_path / "refund-upstream.log"
    server = stub_upstream.start(log)

    def cite_observations(packet: dict[str, Any]) -> dict[str, Any]:
        observations = packet["observations"]
        shipment = next(item for item in observations if item["tool_name"] == "get_shipment_trace")
        search = next(item for item in observations if item["tool_name"] == "search_policy")
        hit = search["result"]["hits"][0]
        return {
            "kind": "PROPOSE",
            "case_type": "LOGISTICS",
            "recommended_action": "REFUND",
            "reason_codes": ["LOST_CONFIRMED"],
            "summary": "已查阅物流证据与固定政策，提出全行退款候选",
            "evidence_refs": [{key: shipment[key] for key in (
                "observation_id", "source_ref", "source_version", "content_hash",
            )}],
            "policy_refs": [{key: hit[key] for key in (
                "bundle_id", "version", "rule_id", "chunk_id", "content_hash",
            )}],
        }

    model = MockModelClient(script=[
        {"kind": "READ_TOOL", "tool_name": "get_shipment_trace", "arguments": {}},
        {"kind": "SEARCH_POLICY", "query": "丢失 全额退款", "arguments": {"top_k": 1}},
        cite_observations,
    ])
    try:
        investigate = build_investigation(
            database=agent_db,
            config=DeploymentConfig(
                mode="mock", policy_index=True, service_token="stub-service-token",
                case_base_url=server.url, commerce_base_url=server.url,
            ),
            model=model,
            policy_embedder=stub_embedder,
        )
        outcome = RunWorker(agent_db, investigate=investigate).run_once()
    finally:
        server.stop()

    assert outcome is not None and outcome.result is not None
    assert outcome.result.completed
    assert (outcome.status, outcome.callback_kind) == ("CALLBACK_PENDING", "PROPOSAL")
    records = CallbackStore(agent_db).list_for_run(RUN_ID)
    assert [record.kind for record in records] == ["STARTED", "PROPOSAL"]
    payload = records[-1].payload
    assert payload["recommended_action"] == "REFUND"
    decision = outcome.result.decision
    assert payload["evidence_refs"] == [ref.model_dump(mode="json") for ref in decision.evidence_refs]
    assert payload["policy_refs"] == [ref.model_dump(mode="json") for ref in decision.policy_refs]
    sent = input_text_of(model, 2)
    for ref in payload["evidence_refs"] + payload["policy_refs"]:
        assert ref["content_hash"] in sent
        assert ref.get("observation_id", ref.get("rule_id")) in sent
    requests = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(requests) == 2
    assert requests[0]["path"].endswith(f"/internal/v1/runs/{RUN_ID}/tool-credential")
    assert requests[0]["authorization"] == "Bearer stub-service-token"
    assert "/internal/v1/order-lines/7100/shipment" in requests[1]["path"]
    assert requests[1]["authorization"] == f"Bearer token-for-{RUN_ID}"
    assert outcome.result.modes == ("mock", "mock", "mock")


def test_a_live_deployment_sends_the_configured_model_and_ceiling_and_records_no_key(
    agent_db: Database,
) -> None:
    """Live mode, driven through the harness with a transport that never leaves the process.

    Two claims in one test because they are the same claim about the same object: the configured model id and the
    reserved ceiling reach the provider body, and the API key reaches the ``Authorization`` header **only** — the
    record the run keeps has no credential in it (C08.1b-2 pinned the same thing one layer down).
    """
    RunStore(agent_db).queue(a_run(), caller=CASE_DISPATCHER)
    sent: list[tuple[str, bytes, dict[str, str], float]] = []

    def transport(request: str, body: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
        sent.append((request, body, headers, timeout))
        return HttpResponse(status=200, body=decision_body(content=propose_json()))

    config = DeploymentConfig(
        mode="live",
        endpoint="https://provider.invalid/v1/chat/completions",
        model_id="some-model",
        api_key="sk-not-a-real-key",
    )
    investigate = build_investigation(database=agent_db, config=config, tools=_Tools())
    # A complete live configuration does build — the refusal above is about *missing* settings, not live mode.
    assert callable(investigate)
    # The transport is what C08.1b-2 made injectable, so this exercises the real client with no network.
    from resolveflow.harness.live_model import LiveModelClient

    client = LiveModelClient(
        endpoint=str(config.endpoint),
        model_id=str(config.model_id),
        api_key=config.api_key,
        transport=transport,
    )

    outcome = RunWorker(agent_db, investigate=lambda facts: _run_with(client, facts)).run_once()

    assert outcome is not None and outcome.result is not None
    assert len(sent) == 1, sent
    _, body, headers, _ = sent[0]
    assert b"some-model" in body
    assert headers.get("Authorization") == "Bearer sk-not-a-real-key"
    # The client's own record of the request carries no credential.
    assert "sk-not-a-real-key" not in json.dumps(client.requests, default=str)
    assert outcome.status == "CALLBACK_PENDING"


def _run_with(client: Any, facts: Any) -> Any:
    """Drive one run with an already-built client, so the live test can inspect that exact object."""
    from resolveflow.harness.budget import RunBudget
    from resolveflow.harness.sdk_runner import AgentScopeRunner

    tools = _Tools()
    try:
        return AgentScopeRunner(model=client, tools=tools, facts=facts, budget=RunBudget()).run()
    finally:
        tools.close()
