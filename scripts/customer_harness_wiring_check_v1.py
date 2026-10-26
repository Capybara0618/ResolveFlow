"""Frozen, local SSE/PG/process matrix. No real model option and no credentials in outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

import httpx
from resolveflow.harness.context import canonical_json
from resolveflow.harness.token_counting import counter_for
from resolveflow.runtime.db import Database, create_schema, drop_schema

from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot
from scripts.customer_rag_live_v2 import persist
from scripts.evaluation.customer_harness_context_v1 import ROOT, write_new
from scripts.evaluation.customer_harness_crash_v1 import offline_matrix
from scripts.evaluation.customer_harness_measurement_v1 import (
    PARAMETERS,
    MeasuredModel,
    context_matrix,
    mock_decision,
    mock_provider,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schemas(database):
    with database.connection() as c:
        return [r['nspname'] for r in c.execute('SELECT nspname FROM pg_namespace ORDER BY nspname').fetchall()]


def audit_context(report, database):
    if len(report['rows']) != 64 or report['sends'] != 128:
        raise AssertionError('context matrix differs')
    seen = set()
    for row in report['rows']:
        key = (row['case_id'], row['variant'], row['checkpoint'])
        if key in seen or row['state'] != 'COMPLETE' or row['result']['status'] != 'SUCCEEDED':
            raise AssertionError('duplicate/unfinished scripted context turn')
        seen.add(key)
        if row['semantic_quality'] is not None or len(row['models']) != 2:
            raise AssertionError('scripted rows cannot supply quality scores')
        with database.connection() as c:
            stored = c.execute("SELECT request_json FROM support_agent_call WHERE run_id=%s AND kind='model' "
                               'ORDER BY position', (row['result']['run_id'],)).fetchall()
        if [r['request_json'] for r in stored] != [r['body'] for r in row['models']]:
            raise AssertionError('PG and sent provider bodies differ')
        for model in row['models']:
            if ('rubrics' in canonical_json(model['body']) or model['transport_scope'] != 'MOCK_SSE'
                    or model['state'] != 'COMPLETE' or not model['send_reserved']
                    or model['body']['max_tokens'] != 1024):
                raise AssertionError('request provenance or ceiling differs')
            counter = counter_for(type('CounterScope', (), {'provider': 'deepseek', 'model_id': 'deepseek-flash'})())
            if counter.count(model['body']) + 256 > 8192:
                raise AssertionError('actual provider body exceeds agreed input cap')
    return {'turns': 64, 'scripted_sse_requests': 128, 'all_sent_bodies_equal_pg_requests': True,
            'all_bodies_within_input_cap': True, 'semantic_quality': None}


def audit_crashes(report):
    if len(report['rows']) != 30 or report['actual_fault_exits'] != 30:
        raise AssertionError('fault matrix not complete')
    seen, unknown_stops = set(), 0
    for row in report['rows']:
        key = (row['case_id'], row['window'], row['arm'])
        if key in seen or row['state'] != 'PROBED' or row['post']['exit_code'] != 0:
            raise AssertionError('duplicate/unfinished fault row')
        seen.add(key)
        if not all(row[k] for k in ('deadline_kept', 'spend_monotonic', 'stale_writer_rejected', 'expected_contract')):
            raise AssertionError('fault invariant differs')
        if row['before']['run']['manifest_json'] != row['after']['run']['manifest_json']:
            raise AssertionError('manifest silently changed')
        fault = row['fault']
        stored = next(c for c in row['before']['calls'] if c['kind'] == fault['kind']
                      and c['position'] == fault['position'])
        if row['window'] == 'model_returned_not_saved':
            if stored['status'] != 'STARTED' or stored['response_json'] is not None:
                raise AssertionError('unknown response was fabricated as durable')
            if row['arm'] == 'resume':
                unknown_stops += 1
                if row['post']['record']['models'] or row['post']['record']['result']['reason'] != 'UNKNOWN_MODEL_RESULT':
                    raise AssertionError('unknown result was silently retried')
        elif stored['status'] != 'COMPLETE':
            raise AssertionError('saved result missing at fault')
        elif row['window'] == 'business_tool_saved':
            if not any(r.get('source_type') in {'ORDER', 'SHIPMENT', 'POLICY'} for r in stored['response_json']):
                raise AssertionError('automatic guide was mistaken for business source')
    return {'paired_tasks': 15, 'actual_fault_exits': 30, 'new_processes_after_faults': 30,
            'journal_contract_checks': 30, 'unknown_response_stops': unknown_stops,
            'saved_window_resume_completions': 10, 'redo_completions': 15,
            'semantic_quality': None, 'live_recovery_metrics': None}


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    original = json.loads((ROOT / 'reports/customer-harness-context-v1/preparation.json').read_text(encoding='utf-8'))
    for name, expected in original['hashes'].items():
        if digest(ROOT / name) != expected:
            raise ValueError('original preparation changed: ' + name)
    names = set(original['hashes'])
    names.update({Path(__file__).relative_to(ROOT).as_posix(), 'scripts/customer_rag_live_v2.py',
                  'scripts/customer_rag_diagnostic.py', 'docs/customer-harness-context-wiring-v1.md',
                  'scripts/evaluation/customer_harness_measurement_v1.py',
                  'scripts/evaluation/customer_harness_crash_v1.py',
                  'agent/tests/unit/test_customer_harness_measurement_v1.py',
                  'agent/tests/integration/test_customer_harness_measurement_v1.py'})
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'agent/src/resolveflow').rglob('*.py'))
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'agent/src/resolveflow/runtime/migrations').glob('*.sql'))
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'agent/src/resolveflow/assets').rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts)
    protected = ['docs/engineering.md', 'scripts/verify.ps1', 'scripts/verify.sh',
        'java/commerce-service/src/test/java/com/resolveflow/commerce/refund/RefundAcceptanceApiTest.java',
        'tmp/evaluation-live-budget.json', 'docs/resume-agent-rag-frozen-20261026.md',
        'reports/resume-quantification-v1/recovery/summary.json',
        'reports/customer-workflow-comparison-v2/agent-summary.json',
        'reports/customer-rag-quantification-v3/development.json']
    retained = {n: digest(ROOT / n) for n in protected}
    manifest = {'version': 'hctx-local-wiring-v1', 'transport_scope': 'MOCK_SSE', 'real_provider_requests': 0,
                'context_turns': 64, 'fault_prefixes': 30, 'parameters': PARAMETERS,
                'files': {n: digest(ROOT / n) for n in sorted(names)}}
    write_new(output / 'manifest.json', manifest)
    dsn = os.environ['HCTX_TEST_DSN']
    public = ReadOnlyDatabase(dsn)
    before, before_schemas = snapshot(public), schemas(public)
    schema = 't_hctx_' + uuid.uuid4().hex[:12]
    if schema in before_schemas:
        raise ValueError('new evaluation schema already exists')
    create_schema(dsn, schema)
    database = Database(dsn, schema=schema)
    final = {'state': 'RUNNING', 'schema': schema, 'transport_scope': 'MOCK_SSE', 'real_provider_requests': 0}
    persist(output / 'audit.json', final)
    try:
        database.migrations()
        def factory(allowance, records, save):
            model = MeasuredModel(endpoint='https://synthetic.invalid', provider='deepseek', model_id='deepseek-flash',
                allowance=allowance, save=save, transport_scope='MOCK_SSE', parameters=PARAMETERS,
                stream_transport=httpx.MockTransport(mock_provider(mock_decision)))
            model.records = records
            return model
        context = context_matrix(database, output=output / 'context-mock.json', model_factory=factory, limit=128)
        final['context'] = audit_context(context, database)
        persist(output / 'audit.json', final)
        print('64 context turns / 128 mock SSE sends audited; starting 30 process faults.', flush=True)
        crashes = offline_matrix(database, output / 'crash-mock.json')
        final['recovery'] = audit_crashes(crashes)
        final['state'] = 'VERIFIED_LOCAL_WIRING'
    except Exception as error:
        final.update(state='ERROR', error_type=type(error).__name__)
        raise
    finally:
        try:
            with database.connection() as c:
                runs = c.execute('SELECT * FROM support_agent_run ORDER BY run_id').fetchall()
                calls = c.execute('SELECT * FROM support_agent_call ORDER BY run_id,kind,position').fetchall()
            persist(output / 'database.json', {'schema': schema, 'runs': runs, 'calls': calls})
        finally:
            database.close()
        drop_schema(dsn, schema)  # Only the just-created unique t_hctx_ schema, after its records were exported.
        after, after_schemas = snapshot(public), schemas(public)
        public.close()
        final.update(public_before=before, public_after=after, public_equal=before == after,
                     schemas_preserved=before_schemas == after_schemas,
                     files_preserved=all(digest(ROOT / n) == h for n, h in manifest['files'].items()),
                     protected_before=retained,
                     protected_equal=all(digest(ROOT / n) == h for n, h in retained.items()),
                     evaluation_schema_dropped=schema not in after_schemas)
        persist(output / 'audit.json', final)
    if not all(final[k] for k in ('public_equal', 'schemas_preserved', 'files_preserved', 'protected_equal',
                                  'evaluation_schema_dropped')):
        raise AssertionError('source, retained rows or isolation changed')
    print('Local context/process matrix verified. Real provider requests: 0.', flush=True)
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.output)


if __name__ == '__main__':
    main()
