"""Reviewer reads are scoped snapshots and never perform a new tool/model call."""
from typing import Any

from psycopg.types.json import Jsonb

from resolveflow.api.identity import mint_service_token
from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, component_validator, load_json
from resolveflow.runtime.db import Database
from tests.integration.test_run_api import CASE_ID, RUN_ID, SECRET, a_body, post_run
from tests.integration.test_run_api import client as client  # pytest fixture re-export
from tests.integration.test_run_api import dispatcher_token as dispatcher_token  # pytest fixture re-export


def token(merchant="M-1001", customer="C-2002", subject="case-service"):
    return mint_service_token(subject, SECRET, scope="run:review", merchant_id=merchant, customer_id=customer)


def read(client: Any, auth: str, **params):
    return client.get(f"/internal/v1/runs/{RUN_ID}/review-sources", headers={"Authorization": f"Bearer {auth}"},
                      params={"case_id": CASE_ID, "input_revision": 1, **params})


def test_sources_require_case_service_and_exact_subject_binding(client, dispatcher_token):
    assert post_run(client, dispatcher_token, a_body()).status_code == 202
    assert read(client, dispatcher_token).status_code == 403
    assert read(client, token(subject="agent-service")).status_code == 403
    assert read(client, token(merchant="M-2002")).status_code == 404
    assert read(client, token(customer="C-other")).status_code == 404
    assert read(client, token(), input_revision=2).status_code == 404
    assert read(client, token(), case_id="00000000-0000-4000-8000-000000000000").status_code == 404


def test_only_recorded_observations_are_exposed_and_size_limits_are_explicit(
    client, dispatcher_token, agent_db: Database,
):
    assert post_run(client, dispatcher_token, a_body()).status_code == 202
    observation = {"observation_id": "shipment-1", "tool_name": "get_shipment_trace", "source_type": "CARRIER",
                   "source_ref": "line:7001/shipment", "source_version": "2", "content_hash": "a" * 64,
                   "observed_at": "2026-09-28T01:00:00Z", "result": {"conclusion": "LOST"}}
    with agent_db.connection() as conn:
        large = {**observation, "result": {"text": "x" * 40000}}
        for key, value in [("tool-1", observation), ("tool-2", None), ("tool-3", large)]:
            conn.execute("INSERT INTO agent_tool_call(run_id,call_id,request_hash,local_read,observation) "
                         "VALUES (%s,%s,%s,false,%s)",
                         (RUN_ID, key, "a" * 64, Jsonb(value) if value is not None else None))
    response = read(client, token())
    assert response.status_code == 200
    body = response.json()
    validator = component_validator("agent", "ReviewerSources", "contracts/core", CORE_SCHEMA_FILES)
    assert list(validator.error_messages(body)) == []
    assert body["input_revision"] == 1 and body["status"] == "QUEUED"
    assert len(body["observations"]) == 2
    assert body["observations"][0]["result"] == {"conclusion": "LOST"}
    assert body["observations"][1]["body_omitted"] is True
    assert body["observations"][1]["result"] is None
    assert "request_hash" not in str(body)
    with agent_db.connection() as conn:
        assert conn.execute("SELECT version FROM agent_run WHERE run_id=%s", (RUN_ID,)).fetchone()["version"] == 1


def test_shared_investigation_fixture_matches_both_contracts():
    fixture = load_json("contracts/core/fixtures/reviewer-investigation.json")
    for name, schema, body in [("case", "ReviewerInvestigation", fixture),
                               ("agent", "ReviewerSources", fixture["investigation"])]:
        validator = component_validator(name, schema, "contracts/core", CORE_SCHEMA_FILES)
        assert list(validator.error_messages(body)) == []


def test_observation_count_limit_is_reported(client, dispatcher_token, agent_db):
    assert post_run(client, dispatcher_token, a_body()).status_code == 202
    with agent_db.connection() as conn:
        for index in range(41):
            conn.execute("INSERT INTO agent_tool_call(run_id,call_id,request_hash,local_read,observation) "
                         "VALUES (%s,%s,%s,false,%s)", (RUN_ID, str(index), "a" * 64, Jsonb({"result": {}})))
    body = read(client, token()).json()
    assert len(body["observations"]) == 40
    assert body["truncated"] is True
