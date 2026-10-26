"""SupportStore crash/restart probe. The CLI deliberately exposes MOCK_SSE only."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from resolveflow.runtime.db import Database
from resolveflow.support.protocol import SupportFailure, SupportInput
from resolveflow.support.store import SupportJournal

from scripts.customer_rag_live_v2 import persist
from scripts.evaluation.customer_harness_context_v1 import (
    DATA,
    RECOVERY_WINDOWS,
    write_new,
)
from scripts.evaluation.customer_harness_measurement_v1 import (
    PARAMETERS,
    MeasuredModel,
    SendAllowance,
    run_turn,
)
from scripts.evaluation.customer_harness_measurement_v1 import (
    mock_provider as provider_for,
)

EXIT_CODE = 73
VERSION = 'customer-harness-crash-v1'


def recovery_request(case, *, deadline):
    return SupportInput(run_id=str(uuid.uuid4()), conversation_id=str(uuid.uuid4()), input_version=1,
        merchant_id='M-EVAL', customer_id='C-EVAL', line_id='line-recovery-' + case['id'], deadline_at=deadline,
        context={'current_request': case['text'], 'history': [], 'product': {'name': '合成故障验证商品'},
                 'policy_manifest': {'merchant_id': 'M-EVAL', 'bundle_ids': ['synthetic-policy'],
                                     'manifest_hash': 'synthetic-policy-v1'}})


def mock_decision(packet):
    if packet['stage']['phase'] == 'UNDERSTAND':
        return {'kind': 'TURN_UNDERSTANDING', 'focus': [{'id': 'q', 'intent': 'OTHER', 'request': '故障接线验证',
                    'needs': ['ORDER', 'SHIPMENT', 'POLICY'], 'goal': 'EXPLAIN'}],
                'dialogue_events': [{'change': 'ADD', 'task_id': 'q', 'reference': 'CURRENT',
                                    'quote': packet['current_request']}]}
    if packet['stage']['phase'] == 'INVESTIGATE':
        return {'kind': 'READ_FACTS', 'tools': ['get_order_context', 'get_shipment_trace'],
                'policy_query': '合成签收争议与退款核验政策'}
    return {'kind': 'RESPOND', 'parts': [{'task_id': 'q', 'text': '已读取合成来源，仅用于恢复接线验证。',
                                         'citations': ['P1']}]}


class FaultJournal(SupportJournal):
    def __init__(self, original, *, window, target, marker):
        super().__init__(original.database, original.run_id, original.fence)
        self.window, self.target, self.marker = window, target, marker

    def crash(self, kind, position):
        write_new(self.marker, {'window': self.window, 'kind': kind, 'position': position,
                               'run_id': self.run_id, 'fence': self.fence, 'exit_code': EXIT_CODE})
        os._exit(EXIT_CODE)

    def complete(self, kind, position, response, spend):
        if self.window == 'model_returned_not_saved' and kind == 'model' and position == 1:
            self.crash(kind, position)
        super().complete(kind, position, response, spend)
        if self.window == 'model_saved' and kind == 'model' and position == 1:
            self.crash(kind, position)
        if (self.window == 'business_tool_saved' and kind == 'tool'
                and any(row.get('source_type') == self.target for row in response)):
            self.crash(kind, position)


def child(spec_path, record_path):
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    if spec['transport_scope'] != 'MOCK_SSE' or not spec['schema'].startswith('t_hctx_'):
        raise ValueError('this process driver only permits isolated-schema MOCK_SSE probes')
    request = SupportInput.model_validate(spec['input'])
    row = {'transport_scope': 'MOCK_SSE', 'phase': spec['phase'], 'state': 'STARTED', 'models': []}
    write_new(record_path, row)
    save = lambda: persist(record_path, row)
    allowance = SendAllowance(12)
    model = MeasuredModel(endpoint='https://synthetic.invalid', provider='deepseek', model_id='deepseek-flash',
        allowance=allowance, save=save, transport_scope='MOCK_SSE', parameters=PARAMETERS,
        stream_transport=httpx.MockTransport(provider_for(mock_decision)))
    model.records = row['models']
    def journal_factory(original):
        return FaultJournal(original, window=spec['window'], target=spec['target'], marker=Path(spec['marker']))
    database = Database(os.environ['HCTX_TEST_DSN'], schema=spec['schema'])
    try:
        row.update(run_turn(database, request, 'layered', model,
            journal_factory=journal_factory if spec['phase'] == 'prefix' else None,
            inherited=spec.get('inherited')))
        row.update(state='COMPLETE', script_sends=allowance.used)
        save()
    finally:
        database.close()


def launch(spec, directory, name, dsn):
    spec_path, record_path = directory / (name + '-spec.json'), directory / (name + '-record.json')
    write_new(spec_path, spec)
    command = [sys.executable, '-m', 'scripts.evaluation.customer_harness_crash_v1', 'child',
               '--spec', str(spec_path), '--record', str(record_path)]
    environment = dict(os.environ, HCTX_TEST_DSN=dsn, PYTHONIOENCODING='utf-8')
    with (directory / (name + '.log')).open('xb') as log:
        result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=55, check=False,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    record = json.loads(record_path.read_text(encoding='utf-8')) if record_path.exists() else None
    return {'exit_code': result.returncode, 'record': record}


def database_record(database, run_id):
    with database.connection() as c:
        run = c.execute('SELECT * FROM support_agent_run WHERE run_id=%s', (run_id,)).fetchone()
        calls = c.execute('SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY kind,position',
                          (run_id,)).fetchall()
    return {'run': run, 'calls': calls}


def execute_job(database, case, window, arm, directory):
    if window not in RECOVERY_WINDOWS or arm not in {'resume', 'redo'}:
        raise ValueError('unknown fault window/arm')
    if not database.schema.startswith('t_hctx_'):
        raise ValueError('only this experiment\'s isolated schemas may be modified')
    directory.mkdir(parents=True, exist_ok=False)
    request = recovery_request(case, deadline=datetime.now(UTC) + timedelta(seconds=120))
    marker = directory / 'fault.json'
    spec = {'schema': database.schema, 'transport_scope': 'MOCK_SSE', 'window': window,
            'phase': 'prefix', 'target': case['business_fault_source'], 'input': request.model_dump(mode='json'),
            'marker': str(marker)}
    prefix = launch(spec, directory, 'prefix', database.dsn)
    before = database_record(database, request.run_id)
    if prefix['exit_code'] != EXIT_CODE or not marker.exists():
        return {'case_id': case['id'], 'window': window, 'arm': arm, 'state': 'FAULT_NOT_REACHED',
                'prefix': prefix, 'before': before, 'post': None}
    witness = json.loads(marker.read_text(encoding='utf-8'))
    old = SupportJournal(database, request.run_id, witness['fence'])
    # Expire only this crashed experiment run's lease; never any business run or manifest.
    with database.connection() as c, c.transaction():
        c.execute("UPDATE support_agent_run SET lease_until=now()-interval '1 second' WHERE run_id=%s",
                  (request.run_id,))
    post_spec = deepcopy(spec) | {'phase': 'post'}
    if arm == 'redo':
        post_request = request.model_copy(update={'run_id': str(uuid.uuid4())})
        post_spec.update(input=post_request.model_dump(mode='json'), inherited=before['run']['spend_json'])
    else:
        post_request = request
    post = launch(post_spec, directory, 'post', database.dsn)
    after = database_record(database, post_request.run_id)
    deadline_kept = after['run']['deadline_at'] == before['run']['deadline_at']
    stale_rejected = False
    try:
        old.spend()
    except SupportFailure as error:
        stale_rejected = error.reason == 'STALE_FENCE'
    before_spend = before['run']['spend_json']
    after_spend = after['run']['spend_json']
    monotonic = all(after_spend.get(key, 0) >= value for key, value in before_spend.items())
    result = post['record'].get('result') if post['record'] else None
    expected = ('FAILED' if arm == 'resume' and window == 'model_returned_not_saved' else 'SUCCEEDED')
    expected_reason = ('UNKNOWN_MODEL_RESULT' if expected == 'FAILED' else None)
    row = {'case_id': case['id'], 'window': window, 'arm': arm, 'state': 'PROBED',
           'fault': witness, 'prefix': prefix, 'before': before, 'post': post, 'after': after,
           'deadline_kept': deadline_kept, 'spend_monotonic': monotonic, 'stale_writer_rejected': stale_rejected,
           'expected_contract': bool(result and result['status'] == expected
                                     and result['reason'] == expected_reason),
           'same_run': request.run_id == post_request.run_id,
           'semantic_quality': None, 'real_provider_requests': 0}
    if not deadline_kept or not monotonic or not stale_rejected:
        raise AssertionError('recovery changed deadline/spend or allowed a stale writer')
    if arm == 'resume' and after['run']['fence'] <= before['run']['fence']:
        raise AssertionError('resume did not acquire a newer fence')
    # Retain the exact database records in this job before any caller removes its test schema.
    persist(directory / 'audit.json', row)
    return row


def offline_matrix(database, output):
    if output.exists():
        raise FileExistsError('never overwrite an existing fault experiment')
    cases = json.loads(DATA.read_text(encoding='utf-8'))['recovery_cases']
    report = {'version': VERSION, 'transport_scope': 'MOCK_SSE', 'state': 'RUNNING', 'rows': [],
              'real_provider_requests': 0, 'semantic_quality': None, 'live_recovery_metrics': None}
    write_new(output, report)
    directory = output.with_suffix('')
    directory.mkdir(exist_ok=False)
    for case in cases:
        for window in RECOVERY_WINDOWS:
            for arm in ('resume', 'redo'):
                row = execute_job(database, case, window, arm, directory / f'{case["id"]}-{window}-{arm}')
                report['rows'].append(row)
                persist(output, report)
    report.update(state='FINISHED', actual_fault_exits=sum(r.get('prefix', {}).get('exit_code') == EXIT_CODE
                                                         for r in report['rows']))
    persist(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('child', 'offline'))
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--record', type=Path)
    parser.add_argument('--schema')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'child':
        child(args.spec, args.record)
    else:
        if not args.schema or not args.schema.startswith('t_hctx_') or not args.output:
            raise ValueError('isolated schema and new output are required')
        database = Database(os.environ['HCTX_TEST_DSN'], schema=args.schema)
        try:
            offline_matrix(database, args.output)
        finally:
            database.close()


if __name__ == '__main__':
    main()
