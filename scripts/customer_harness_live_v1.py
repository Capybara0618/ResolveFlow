"""Freeze/check/run bounded current-customer evaluations. Freeze and check never contact a provider."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from resolveflow.runtime.db import Database, create_schema, drop_schema
from resolveflow.support.protocol import SupportInput

from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot
from scripts.customer_rag_live_v2 import persist
from scripts.evaluation import customer_harness_crash_v1 as crash
from scripts.evaluation import customer_harness_measurement_v1 as measurement
from scripts.evaluation.customer_harness_budget_v1 import BudgetSession, reserve
from scripts.evaluation.customer_harness_budget_v1 import read as read_ledger
from scripts.evaluation.customer_harness_context_v1 import (
    DATA,
    RECOVERY_WINDOWS,
    ROOT,
    VARIANTS,
    public_case,
    validate_dataset,
    write_new,
)
from scripts.evaluation.customer_harness_measurement_v1 import (
    PARAMETERS,
    MeasuredModel,
    SendAllowance,
    prepared_request,
    run_turn,
)

VERSION = 'customer-harness-live-v1'
CONTEXT_LIMIT, RECOVERY_LIMIT, TOTAL_LIMIT = 400, 300, 700
PLAN = ROOT / 'evals/customer-harness-context-v1/live-manifest.json'
USAGE = ROOT / 'tmp/evaluation-live-budget.json'
ENDPOINT = 'https://api.deepseek.com/chat/completions'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dataset():
    value = json.loads(DATA.read_text(encoding='utf-8'))
    validate_dataset(value)
    return value


def create_manifest():
    # Original material and implementation hashes remain frozen; this is a new execution version.
    preparation = ROOT / 'reports/customer-harness-context-v1/preparation.json'
    frozen = json.loads(preparation.read_text(encoding='utf-8'))['hashes']
    for name, expected in frozen.items():
        if digest(ROOT / name) != expected:
            raise ValueError('original preparation changed: ' + name)
    dataset()
    names = set(frozen) | {
        preparation.relative_to(ROOT).as_posix(), 'scripts/customer_harness_live_v1.py',
        'scripts/evaluation/customer_harness_budget_v1.py',
        'scripts/evaluation/customer_harness_measurement_v1.py', 'scripts/evaluation/customer_harness_crash_v1.py',
        'scripts/customer_rag_live_v2.py', 'scripts/customer_rag_diagnostic.py', 'scripts/evaluation/models.py',
        'docs/customer-harness-live-v1.md', 'agent/tests/unit/test_customer_harness_live_v1.py',
        'agent/tests/integration/test_customer_harness_live_v1.py',
    }
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'agent/src/resolveflow').rglob('*.py'))
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'agent/src/resolveflow/runtime/migrations').glob('*.sql'))
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'agent/src/resolveflow/assets').rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts)
    return {'version': VERSION, 'files': {n: digest(ROOT / n) for n in sorted(names)},
            'context_turns': 64, 'recovery_pairs': 15, 'repeats': 1,
            'limits': {'context': CONTEXT_LIMIT, 'recovery': RECOVERY_LIMIT}, 'total_requests': TOTAL_LIMIT,
            'model': 'deepseek-flash', 'endpoint': ENDPOINT, 'parameters': PARAMETERS,
            'input_cap': 8192, 'output_cap': 1024, 'provider_capacity': 32768, 'deadline_seconds': 120,
            'synthetic': True, 'holdout': False, 'baseline': 'same SDK/raw history/oldest-first eviction',
            'facts': 'synthetic delivered/order32900; recovery application NOT_SHIPPED/PAID',
            'policy': 'three synthetic clauses / complete small set / not a RAG experiment',
            'recovery_unknown_response': 'UNKNOWN_MODEL_RESULT is a failed recovery, not saved-cost success'}


def load_plan(path=PLAN):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if value != create_manifest():
        raise ValueError('execution manifest differs from current implementation/material')
    return value


def context_slots():
    return [{'case_id': case['id'], 'variant': variant, 'checkpoint': index + 1}
            for n, case in enumerate(dataset()['context_cases'])
            for variant in (VARIANTS if n % 2 == 0 else VARIANTS[::-1]) for index in (0, 1)]


def validate_prefix(rows, slots):
    if len(rows) > len(slots):
        raise ValueError('saved prefix exceeds planned matrix')
    for row, wanted in zip(rows, slots, strict=False):
        if any(row.get(k) != v for k, v in wanted.items()):
            raise ValueError('saved prefix identity/order differs')
        if row.get('state') != 'COMPLETE' or row.get('result') is None:
            raise ValueError('in-flight row requires source/journal audit before continuation')
        if any(m.get('state') not in {'COMPLETE', 'ERROR'} for m in row.get('models', [])):
            raise ValueError('in-flight model response cannot be silently retried')
    return len(rows)


def review_template():
    return {'version': VERSION, 'review_kind': 'CODEX_NONBLIND_SOURCE_REVIEW',
            'context': [{**slot, 'pass': None, 'checks': None, 'reason': None, 'evidence': None}
                        for slot in context_slots()],
            'recovery': [{'case_id': c['id'], 'window': w, 'arm': arm,
                          'result_correct': None, 'reason': None, 'evidence': None}
                         for c in dataset()['recovery_cases'] for w in RECOVERY_WINDOWS for arm in ('resume', 'redo')],
            'summary': None}


def model_for(allowance, records, save, *, transport_scope='REAL_PROVIDER', transport=None):
    if transport_scope == 'REAL_PROVIDER' and transport is not None:
        raise ValueError('real-provider records must not use a supplied mock transport')
    key = os.environ.get('RESOLVEFLOW_MODEL_API_KEY', '') if transport_scope == 'REAL_PROVIDER' else ''
    if transport_scope == 'REAL_PROVIDER' and not key:
        raise ValueError('model credential missing; no request sent')
    model = MeasuredModel(endpoint=ENDPOINT if transport_scope == 'REAL_PROVIDER' else 'https://synthetic.invalid',
        provider='deepseek', model_id='deepseek-flash', api_key=key, parameters=PARAMETERS,
        allowance=allowance, save=save, transport_scope=transport_scope, stream_transport=transport)
    model.records = records
    return model


def context_phase(database, report_path, report, session, *, factory=model_for, max_rows=None):
    cases = {c['id']: public_case(c) for c in dataset()['context_cases']}
    slots = context_slots()
    rows = report.setdefault('context', [])
    at = validate_prefix(rows, slots)
    if max_rows is not None:
        slots = slots[:max_rows]  # Only an injected test caller may shorten the fixed execution matrix.
    for slot in slots[at:]:
        case = cases[slot['case_id']]
        index = slot['checkpoint'] - 1
        previous = rows[-1]['result'] if index == 1 else None
        req = prepared_request(case, index, slot['variant'], previous=previous,
                               deadline=datetime.now(UTC) + timedelta(seconds=120))
        row = {**slot, 'state': 'STARTED', 'models': [], 'input': req.model_dump(mode='json')}
        rows.append(row)
        save = lambda: persist(report_path, report)
        save()  # Immutable input/deadline are recorded before a provider reservation.
        allowance = SendAllowance(CONTEXT_LIMIT, consumed=lambda: reserve(
            session.ledger, session.session_id, session.token, 'context'))
        model = factory(allowance, row['models'], save)
        value = run_turn(database, req, slot['variant'], model)
        row.update(value, state='COMPLETE')
        save()
        if value['result'].get('reason') == 'EVALUATION_ALLOWANCE_EXHAUSTED':
            report['state'] = 'BUDGET_EXHAUSTED'
            save()
            return


@contextmanager
def recovery_sources():
    """Preserve raw fixtures except the explicitly unshipped recovery task's authoritative facts."""
    original = measurement.source_client
    @contextmanager
    def bound(request, records):
        with original(request, records) as (base, index):
            def route(call):
                response = base.send(base.build_request(call.method, str(call.url)))
                if request.context.get('evaluation_order_unshipped') and response.status_code == 200:
                    data = response.json()
                    if call.url.path.endswith('/facts/order'):
                        data['order_line']['status'] = 'PAID'
                    elif call.url.path.endswith('/facts/shipment'):
                        data['lines'][0].update(status='NOT_SHIPPED', carrier_conclusion='NOT_SHIPPED')
                    if records and records[-1]['path'] == call.url.path:
                        records[-1]['result'] = deepcopy(data)
                    return httpx.Response(200, json=data)
                return response
            with httpx.Client(transport=httpx.MockTransport(route)) as client:
                yield client, index
    with patch.object(measurement, 'source_client', bound):
        yield


def crash_child(spec_path, record_path, *, factory=model_for):
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    if not spec['schema'].startswith('t_hctx_'):
        raise ValueError('only isolated experiment schemas allowed')
    request = SupportInput.model_validate(spec['input'])
    row = {'phase': spec['phase'], 'state': 'STARTED', 'models': [],
           'transport_scope': spec.get('transport_scope', 'REAL_PROVIDER')}
    write_new(record_path, row)
    save = lambda: persist(record_path, row)
    allowance = SendAllowance(12, consumed=lambda: reserve(Path(os.environ['HCTX_LEDGER']),
        os.environ['HCTX_SESSION'], os.environ['HCTX_OWNER_TOKEN'], 'recovery'))
    model = factory(allowance, row['models'], save)
    def journal(original):
        return crash.FaultJournal(original, window=spec['window'], target=spec['target'], marker=Path(spec['marker']))
    database = Database(os.environ['HCTX_TEST_DSN'], schema=spec['schema'])
    try:
        with recovery_sources():
            row.update(run_turn(database, request, 'layered', model,
                journal_factory=journal if spec['phase'] == 'prefix' else None, inherited=spec.get('inherited')))
        row.update(state='COMPLETE', send_reservations=allowance.used)
        save()
    finally:
        database.close()


def real_launch(spec, directory, name, dsn):
    spec_path, record_path = directory / (name + '-spec.json'), directory / (name + '-record.json')
    actual = deepcopy(spec) | {'transport_scope': 'REAL_PROVIDER'}
    write_new(spec_path, actual)
    environment = dict(os.environ, HCTX_TEST_DSN=dsn, PYTHONIOENCODING='utf-8')
    command = [sys.executable, '-m', 'scripts.customer_harness_live_v1', 'child',
               '--spec', str(spec_path), '--record', str(record_path)]
    with (directory / (name + '.log')).open('xb') as log:
        result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=150,
            check=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    record = json.loads(record_path.read_text(encoding='utf-8')) if record_path.exists() else None
    return {'exit_code': result.returncode, 'record': record}


def recovery_phase(database, directory, report_path, report, session):
    rows = report.setdefault('recovery', [])
    slots = [(c, w, arm) for c in dataset()['recovery_cases'] for w in RECOVERY_WINDOWS for arm in ('resume', 'redo')]
    for row, (case, window, arm) in zip(rows, slots, strict=False):
        if ((row.get('case_id'), row.get('window'), row.get('arm')) != (case['id'], window, arm)
                or row.get('state') not in {'PROBED', 'FAULT_NOT_REACHED'}):
            raise ValueError('unfinished/foreign recovery prefix; audit before continuation')
    original_request = crash.recovery_request
    def request(case, **kwargs):
        req = original_request(case, **kwargs)
        req.context['evaluation_order_unshipped'] = case['id'] == 'application'
        return req
    with patch.dict(os.environ, {'HCTX_LEDGER': str(session.ledger), 'HCTX_SESSION': session.session_id,
                                 'HCTX_OWNER_TOKEN': session.token}), patch.object(crash, 'launch', real_launch), patch.object(
                                     crash, 'recovery_request', request):
        for case, window, arm in slots[len(rows):]:
            job_dir = directory / f'{case["id"]}-{window}-{arm}'
            # A previous launch not yet in report must be reviewed, never silently rerun.
            if job_dir.exists():
                raise ValueError('in-flight recovery directory exists; audit preserved records')
            row = crash.execute_job(database, case, window, arm, job_dir)
            row.pop('real_provider_requests', None)  # Old offline helper's placeholder is not a live metric.
            row.update(transport_scope='REAL_PROVIDER')
            rows.append(row)
            report['state'] = 'RUNNING'
            persist(report_path, report)
            counts = read_ledger(session.ledger)['hctx_sessions'][session.session_id]['used_by_phase']
            if counts['recovery'] >= RECOVERY_LIMIT:
                report['state'] = 'BUDGET_EXHAUSTED'
                persist(report_path, report)
                return


def export_database(database, path):
    with database.connection() as c:
        runs = c.execute('SELECT * FROM support_agent_run ORDER BY run_id').fetchall()
        calls = c.execute('SELECT * FROM support_agent_call ORDER BY run_id,kind,position').fetchall()
    persist(path, {'schema': database.schema, 'runs': runs, 'calls': calls})


def execute(output, expected_start, *, dsn, ledger=USAGE):
    plan = load_plan()
    if not os.environ.get('RESOLVEFLOW_MODEL_API_KEY'):
        raise ValueError('model credential missing; no requests sent')
    output = Path(output).resolve()
    report_path = output / 'runtime.json'
    plan_hash = digest(PLAN)
    session_id = VERSION + ':' + hashlib.sha256(str(output).encode()).hexdigest()[:20]
    # Bounds are fixed before creating a schema or contacting a model. New output cannot reset shared counters.
    with BudgetSession(ledger, session_id, plan_hash, expected_start=expected_start,
                       limits=plan['limits'], total=TOTAL_LIMIT) as session:
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding='utf-8'))
            if (report.get('plan_sha256') != plan_hash or report.get('session_id') != session_id
                    or report.get('schema_dropped')):
                raise ValueError('execution result/plan differs or has already been finalized')
            validate_prefix(report.get('context', []), context_slots())
        else:
            output.mkdir(parents=True, exist_ok=False)
            report = {'version': VERSION, 'plan_sha256': plan_hash, 'session_id': session_id,
                      'usage_start': expected_start, 'schema': 't_hctx_' + uuid.uuid4().hex[:12],
                      'state': 'PREPARED', 'context': [], 'recovery': [], 'semantic_scores': None,
                      'schema_dropped': False, 'transport_scope': 'REAL_PROVIDER'}
            write_new(report_path, report)
            write_new(output / 'review-template.json', review_template())
            write_new(output / 'execution-plan.json', plan)
        schema = report['schema']
        if not schema.startswith('t_hctx_'):
            raise ValueError('foreign schema refused')
        public = ReadOnlyDatabase(dsn)
        before = snapshot(public)
        if 'public_before' not in report:
            report['public_before'] = before
            persist(report_path, report)
        elif report['public_before'] != before:
            raise ValueError('retained public data changed before continuation')
        create_schema(dsn, schema)
        database = Database(dsn, schema=schema)
        try:
            database.migrations()
            context_phase(database, report_path, report, session)
            if report['state'] != 'BUDGET_EXHAUSTED':
                recovery_phase(database, output / 'jobs', report_path, report, session)
            if len(report['context']) == 64 and len(report['recovery']) == 30:
                report['state'] = 'FINISHED_NEEDS_SOURCE_REVIEW'
        except BaseException as error:
            report.update(state='ERROR', error_type=type(error).__name__)
            raise
        finally:
            export_database(database, output / 'database.json')
            database.close()
            after = snapshot(public)
            public.close()
            report.update(public_after=after, public_equal=report['public_before'] == after,
                          usage_after=read_ledger(ledger)['used'],
                          used_by_phase=read_ledger(ledger)['hctx_sessions'][session_id]['used_by_phase'])
            if report['state'] == 'FINISHED_NEEDS_SOURCE_REVIEW':
                drop_schema(dsn, schema)
                report['schema_dropped'] = True
            # Errors/budget stops retain their isolated schema for audit; never wipe a partial run.
            persist(report_path, report)
        if not report['public_equal']:
            raise AssertionError('retained public records changed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze', 'check', 'execute', 'child'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--expected-start', type=int)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--record', type=Path)
    args = parser.parse_args()
    if args.command == 'freeze':
        write_new(PLAN, create_manifest())
        print('Frozen 64 context turns / 15 recovery pairs; 400+300=700 request maximum. No model calls.')
    elif args.command == 'check':
        load_plan()
        print('Execution manifest verified. No model calls.')
    elif args.command == 'child':
        crash_child(args.spec, args.record)
    else:
        if args.output is None or args.expected_start is None:
            raise ValueError('explicit new output and original ledger start required')
        if not os.environ.get('HCTX_TEST_DSN'):
            raise ValueError('explicit isolated test database DSN required')
        execute(args.output, args.expected_start, dsn=os.environ['HCTX_TEST_DSN'])


if __name__ == '__main__':
    main()
