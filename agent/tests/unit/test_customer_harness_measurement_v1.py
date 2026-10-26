"""Actual SSE/body accounting using a transport stub; never a paid request."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from scripts.evaluation.customer_harness_context_v1 import build_dataset, checkpoint_request, public_case
from scripts.evaluation.customer_harness_measurement_v1 import (
    MeasuredModel,
    SendAllowance,
    mock_provider,
    prepared_request,
    source_client,
    usage_summary,
)

from resolveflow.harness.live_model import ModelUnavailableError
from resolveflow.harness.sdk_adapter import messenger_message
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.sources import BoundSources


def client(allowance, transport, save=lambda: None):
    return MeasuredModel(endpoint='https://synthetic.invalid', provider='deepseek', model_id='deepseek-flash',
                         api_key='unit-test-only', stream_transport=transport, allowance=allowance, save=save,
                         transport_scope='MOCK_SSE')


def invoke(model):
    return model.decide(system='', messages=[messenger_message({'step': 1})], max_output_tokens=1024)


def test_allowance_stops_before_sending_and_records_an_unsent_call():
    sent = []
    model = client(SendAllowance(0), httpx.MockTransport(lambda req: sent.append(req)))
    with pytest.raises(SupportFailure, match='EVALUATION_ALLOWANCE_EXHAUSTED'):
        invoke(model)
    assert sent == [] and model.records[0]['send_reserved'] is False
    assert model.records[0]['usage'] is None


def test_sse_counts_one_send_and_retains_exact_body_usage_and_served_model():
    received = []
    decision = {'kind': 'RESPOND', 'parts': [{'task_id': 'q', 'text': '脚本回答。'}]}
    provider = mock_provider(lambda packet: decision, received=received)
    allowance = SendAllowance(1)
    model = client(allowance, httpx.MockTransport(provider))
    reply = invoke(model)
    assert reply.decision == decision and allowance.used == 1
    row = model.records[0]
    assert row['body'] == received[0] and row['body']['stream'] is True
    assert row['body']['max_tokens'] == 1024
    assert 'unit-test-only' not in json.dumps(row)
    assert row['usage_kind'] == 'PROVIDER' and row['usage']['estimated'] is False
    assert row['served_model'] == 'synthetic-sse-model'
    assert usage_summary(model.records)['provider_requests'] == 1


def test_absent_usage_stays_unknown_instead_of_becoming_zero_cost():
    model = client(SendAllowance(1), httpx.MockTransport(mock_provider(
        lambda packet: {'kind': 'RESPOND', 'parts': [{'task_id': 'q', 'text': '脚本回答。'}]}, usage=False)))
    invoke(model)
    summary = usage_summary(model.records)
    assert summary['unknown_usage_requests'] == 1
    assert summary['provider_input_tokens'] is None and summary['provider_output_tokens'] is None


def test_failure_to_persist_initial_record_prevents_network():
    sent = []
    def fail():
        raise PermissionError('synthetic report lock')
    model = client(SendAllowance(1), httpx.MockTransport(lambda req: sent.append(req)), save=fail)
    with pytest.raises(PermissionError):
        invoke(model)
    assert sent == [] and model.allowance.used == 0


def test_http_failure_counts_attempt_but_has_no_fabricated_usage():
    model = client(SendAllowance(1), httpx.MockTransport(lambda req: httpx.Response(500, text='synthetic outage')))
    with pytest.raises(ModelUnavailableError):
        invoke(model)
    row = model.records[0]
    assert row['send_reserved'] and row['usage'] is None and row['state'] == 'ERROR'
    assert usage_summary(model.records)['unknown_usage_requests'] == 1


def test_facts_history_and_policy_are_bound_to_same_request_without_real_http():
    case = public_case(build_dataset()['context_cases'][0])
    req = prepared_request(case, 0, 'raw', deadline=datetime.now(UTC) + timedelta(seconds=120))
    reads = []
    with source_client(req, reads) as (client_, index):
        source = BoundSources(req, case_url='http://synthetic.invalid', token='synthetic', client=client_, index=index)
        source.check_current()
        assert source.read('get_order_context', {})['data']['line_id'] == req.line_id
        assert source.read('get_shipment_trace', {})['data']['lines'][0]['line_id'] == req.line_id
        assert len(source.search('签收争议', 3)) > 0
        assert client_.get('http://synthetic.invalid/internal/v1/support/turns/foreign/current').status_code == 403
    assert reads and all('headers' not in row for row in reads)


def test_accepted_update_cannot_carry_another_runs_memory_or_task_state():
    case = public_case(build_dataset()['context_cases'][0])
    first = checkpoint_request(case, 0, 'layered', deadline=datetime.now(UTC) + timedelta(seconds=120))
    result = {'run_id': first.run_id, 'conversation_id': first.conversation_id,
              'input_version': first.input_version, 'status': 'FAILED', 'answer': None,
              'conversation_update': {'version': 'support-state-v1', 'run_id': 'foreign'}}
    with pytest.raises(ValueError, match='accepted update'):
        prepared_request(case, 1, 'layered', previous=result,
                         deadline=datetime.now(UTC) + timedelta(seconds=120))
