"""Bounded formal driver with synthetic SSE and real PG; test ledger never touches shared usage."""

import json
import os
import subprocess
import sys

import httpx
import pytest
from scripts import customer_harness_live_v1 as driver
from scripts.customer_rag_live_v2 import persist
from scripts.evaluation.customer_harness_budget_v1 import BudgetSession, read, reserve
from scripts.evaluation.customer_harness_measurement_v1 import mock_decision, mock_provider

from resolveflow.runtime.db import Database, create_schema, drop_schema
from resolveflow.support.protocol import SupportFailure


@pytest.fixture
def live_db(postgres_dsn):
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


def factory(allowance, records, save):
    return driver.model_for(allowance, records, save, transport_scope='MOCK_SSE',
                            transport=httpx.MockTransport(mock_provider(mock_decision)))


def test_parent_two_turns_and_child_share_count_and_restart_cannot_reset_it(live_db, tmp_path):
    ledger, report_path = tmp_path / 'usage.json', tmp_path / 'runtime.json'
    ledger.write_text(json.dumps({'used': 31}), encoding='utf-8')
    report = {'state': 'RUNNING', 'context': []}
    persist(report_path, report)
    with BudgetSession(ledger, 'session', 'plan', expected_start=31,
                       limits={'context': 6, 'recovery': 1}, total=7) as session:
        driver.context_phase(live_db, report_path, report, session, factory=factory, max_rows=1)
        assert read(ledger)['used'] == 33
        # Continue from a complete first-checkpoint prefix. It must not send that turn again.
        driver.context_phase(live_db, report_path, report, session, factory=factory, max_rows=2)
        assert read(ledger)['used'] == 35
        code = ('import os; from pathlib import Path; '
                'from scripts.evaluation.customer_harness_budget_v1 import reserve; '
                'reserve(Path(os.environ["TEST_LEDGER"]),"session",os.environ["TEST_OWNER"],"recovery")')
        child = subprocess.run([sys.executable, '-c', code], env=dict(os.environ, TEST_LEDGER=str(ledger),  # noqa: S603 - fixed test code, no shell
            TEST_OWNER=session.token), capture_output=True, timeout=20, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        assert child.returncode == 0, child.stderr.decode(errors='replace')
        assert read(ledger)['used'] == 36
    with BudgetSession(ledger, 'session', 'plan', expected_start=31,
                       limits={'context': 6, 'recovery': 1}, total=7) as session:
        reserve(ledger, session.session_id, session.token, 'context')
        reserve(ledger, session.session_id, session.token, 'context')
        with pytest.raises(SupportFailure, match='EVALUATION_ALLOWANCE_EXHAUSTED'):
            reserve(ledger, session.session_id, session.token, 'context')
    assert read(ledger)['used'] == 38
    assert len(report['context']) == 2 and all(r['state'] == 'COMPLETE' for r in report['context'])


def test_budget_exhaustion_finishes_current_failure_without_sending_extra_turns(live_db, tmp_path):
    ledger, path = tmp_path / 'usage.json', tmp_path / 'runtime.json'
    ledger.write_text(json.dumps({'used': 0}), encoding='utf-8')
    report = {'state': 'RUNNING', 'context': []}
    persist(path, report)
    with BudgetSession(ledger, 's', 'plan', expected_start=0, limits={'context': 1}, total=1) as session:
        driver.context_phase(live_db, path, report, session, factory=factory, max_rows=2)
    assert read(ledger)['used'] == 1 and len(report['context']) == 1
    assert report['state'] == 'BUDGET_EXHAUSTED'
    assert report['context'][0]['result']['reason'] == 'EVALUATION_ALLOWANCE_EXHAUSTED'
    assert sum(m['send_reserved'] for m in report['context'][0]['models']) == 1


def test_new_unshipped_recovery_source_matches_application_without_changing_original(live_db):
    from datetime import UTC, datetime, timedelta

    from scripts.evaluation.customer_harness_crash_v1 import recovery_request

    from resolveflow.support.sources import BoundSources
    req = recovery_request({'id': 'application', 'text': '未发货申请退款'},
                           deadline=datetime.now(UTC) + timedelta(seconds=120))
    req.context['evaluation_order_unshipped'] = True
    def statuses():
        records = []
        # Resolve function dynamically to observe the explicit evaluation-only patch.
        from scripts.evaluation import customer_harness_measurement_v1 as module
        with module.source_client(req, records) as (client, index):
            bound = BoundSources(req, token='test', case_url='http://synthetic.invalid', client=client, index=index)
            order, shipment = bound.read('get_order_context', {}), bound.read('get_shipment_trace', {})
        return order['data']['order_line']['status'], shipment['data']['lines'][0]['status'], records
    with driver.recovery_sources():
        order, shipment, rows = statuses()
        assert (order, shipment) == ('PAID', 'NOT_SHIPPED')
        assert rows[-1]['result']['lines'][0]['status'] == 'NOT_SHIPPED'
    assert statuses()[:2] == ('DELIVERED', 'DELIVERED')


def test_child_is_still_bound_when_parent_context_ablation_uses_real_pg(live_db, tmp_path):
    """Actual new child's run body/fault executes against the same journal and parent's ledger."""
    from datetime import UTC, datetime, timedelta

    from scripts.evaluation.customer_harness_crash_v1 import recovery_request
    req = recovery_request({'id': 'policy', 'text': '请说明签收争议政策'},
                           deadline=datetime.now(UTC) + timedelta(seconds=120))
    spec = {'schema': live_db.schema, 'input': req.model_dump(mode='json'), 'phase': 'post',
            'window': 'model_saved', 'target': 'POLICY', 'marker': str(tmp_path / 'fault.json'),
            'transport_scope': 'MOCK_SSE'}
    spec_path, record_path, ledger = tmp_path / 'spec.json', tmp_path / 'record.json', tmp_path / 'ledger.json'
    spec_path.write_text(json.dumps(spec), encoding='utf-8')
    ledger.write_text(json.dumps({'used': 0}), encoding='utf-8')
    with BudgetSession(ledger, 'child', 'plan', expected_start=0, limits={'recovery': 3}, total=3) as session:
        with pytest.MonkeyPatch.context() as changes:
            changes.setenv('HCTX_LEDGER', str(ledger))
            changes.setenv('HCTX_SESSION', session.session_id)
            changes.setenv('HCTX_OWNER_TOKEN', session.token)
            changes.setenv('HCTX_TEST_DSN', live_db.dsn)
            driver.crash_child(spec_path, record_path, factory=factory)
    row = json.loads(record_path.read_text(encoding='utf-8'))
    assert row['result']['status'] == 'SUCCEEDED' and read(ledger)['used'] == 2
    assert row['models'][0]['body']['stream'] is True


def test_execute_exports_and_retains_partial_schema_without_replaying_prefix(postgres_dsn, tmp_path, monkeypatch):
    ledger, plan_path, output = tmp_path / 'ledger.json', tmp_path / 'plan.json', tmp_path / 'output'
    ledger.write_text(json.dumps({'used': 0}), encoding='utf-8')
    plan = {'limits': {'context': 400, 'recovery': 300}, 'test_scope': 'mock-only'}
    plan_path.write_text(json.dumps(plan), encoding='utf-8')
    monkeypatch.setattr(driver, 'PLAN', plan_path)
    monkeypatch.setattr(driver, 'load_plan', lambda: plan)
    monkeypatch.setenv('RESOLVEFLOW_MODEL_API_KEY', 'test-not-a-provider-key')
    real_context = driver.context_phase
    def context(db, path, report, session):
        real_context(db, path, report, session, factory=factory, max_rows=2)
    monkeypatch.setattr(driver, 'context_phase', context)
    monkeypatch.setattr(driver, 'recovery_phase', lambda *args: None)
    report = driver.execute(output, 0, dsn=postgres_dsn, ledger=ledger)
    schema = report['schema']
    try:
        assert report['public_equal'] and report['schema_dropped'] is False
        exported = json.loads((output / 'database.json').read_text(encoding='utf-8'))
        assert len(exported['runs']) == 2 and len(exported['calls']) == 6
        assert read(ledger)['used'] == 4
        resumed = driver.execute(output, 0, dsn=postgres_dsn, ledger=ledger)
        assert len(resumed['context']) == 2 and read(ledger)['used'] == 4
        assert 'test-not-a-provider-key' not in (output / 'runtime.json').read_text(encoding='utf-8')
    finally:
        drop_schema(postgres_dsn, schema)
