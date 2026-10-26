"""Real temporary PG and child processes; provider/facts remain explicitly synthetic."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from scripts.evaluation.customer_harness_context_v1 import build_dataset, public_case
from scripts.evaluation.customer_harness_crash_v1 import execute_job
from scripts.evaluation.customer_harness_measurement_v1 import (
    PARAMETERS,
    MeasuredModel,
    SendAllowance,
    mock_decision,
    mock_provider,
    prepared_request,
    run_turn,
)

from resolveflow.runtime.db import Database, create_schema, drop_schema


@pytest.fixture
def measurement_db(postgres_dsn):
    import uuid
    schema = 't_hctx_' + uuid.uuid4().hex[:12]
    create_schema(postgres_dsn, schema)
    db = Database(postgres_dsn, schema=schema)
    try:
        db.migrations()
        yield db
    finally:
        db.close()
        drop_schema(postgres_dsn, schema)


def test_both_context_arms_persist_actual_sse_bodies_and_reuse_completed_results(measurement_db):
    case = public_case(build_dataset()['context_cases'][0])
    for variant in ('raw', 'layered'):
        previous = None
        for index in (0, 1):
            req = prepared_request(case, index, variant, previous=previous,
                                   deadline=datetime.now(UTC) + timedelta(seconds=120))
            model = MeasuredModel(endpoint='https://synthetic.invalid', provider='deepseek',
                model_id='deepseek-flash', parameters=PARAMETERS,
                stream_transport=httpx.MockTransport(mock_provider(mock_decision)),
                allowance=SendAllowance(2), save=lambda: None, transport_scope='MOCK_SSE')
            row = run_turn(measurement_db, req, variant, model)
            previous = row['result']
            assert previous['status'] == 'SUCCEEDED', previous['reason']
            assert row['usage']['provider_requests'] == 2
            before = len(model.records)
            assert run_turn(measurement_db, req, variant, model)['result'] == previous
            assert len(model.records) == before
            with measurement_db.connection() as c:
                saved = c.execute("SELECT request_json FROM support_agent_call WHERE run_id=%s AND kind='model' "
                                  'ORDER BY position', (req.run_id,)).fetchall()
                assert [r['request_json'] for r in saved] == [m['body'] for m in model.records]
                packet = json.loads(saved[0]['request_json']['messages'][-1]['content'])
                assert 'rubrics' not in json.dumps(packet)
                assert packet['context_layout']['version'] == (
                    'evaluation-raw-oldest-drop-v1' if variant == 'raw' else 'support-layered-v2')


@pytest.mark.parametrize('window', ['model_returned_not_saved', 'model_saved', 'business_tool_saved'])
def test_real_process_exit_and_new_fence_match_current_journal_contract(measurement_db, tmp_path, window):
    case = build_dataset()['recovery_cases'][0]
    row = execute_job(measurement_db, case, window, 'resume', tmp_path / window)
    assert row['prefix']['exit_code'] == 73 and row['post']['exit_code'] == 0
    assert row['expected_contract'], row['post']['record']
    assert row['deadline_kept'] and row['spend_monotonic'] and row['stale_writer_rejected']
    assert row['after']['run']['fence'] == row['before']['run']['fence'] + 1
    if window == 'model_returned_not_saved':
        assert row['post']['record']['models'] == []
        assert row['post']['record']['result']['reason'] == 'UNKNOWN_MODEL_RESULT'
    else:
        assert len(row['post']['record']['models']) < 3


def test_redo_uses_new_run_but_carries_spend_and_original_deadline(measurement_db, tmp_path):
    row = execute_job(measurement_db, build_dataset()['recovery_cases'][0], 'business_tool_saved', 'redo',
                      tmp_path / 'redo')
    assert row['expected_contract'] and row['same_run'] is False
    assert len(row['post']['record']['models']) == 3
    assert row['spend_monotonic'] and row['deadline_kept'] and row['stale_writer_rejected']
