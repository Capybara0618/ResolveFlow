"""Three explicit live browser turns on retained synthetic data; no automatic retries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'agent/src')]

import reviewer_demo as demo
from customer_agent_live_acceptance import snapshot
from resolveflow.runtime.db import Database

from scripts.agent_eval import allowance, persist
from scripts.evaluation.models import live_guard

OUT = ROOT / 'reports/chat-stream-live-v1'
PRIVATE = ROOT / 'tmp/chat-stream-live-v1'
LEDGER = ROOT / 'tmp/evaluation-live-budget.json'
TURNS = [
    '这副耳机还没收到，麻烦查一下现在的物流状态。我暂时不申请退款。',
    '如果一直没有收到，店里的售后政策是怎样的？需要我提供哪些材料？先解释政策，不要替我申请。',
    '补充更正一下：我已经找到包裹了，暂时没有发现商品损坏。现在只想知道如何找商家人工咨询，不申请退款。',
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connect():
    settings = demo.settings_from_environ()
    demo.guard(settings)
    assert settings.ports == demo.DEFAULT_PORTS and settings.project == demo.PROJECT
    return settings, Database(settings.agent_dsn)


def prepare():
    assert not (OUT / 'plan.json').exists(), 'frozen plan already exists'
    settings, db = connect()
    try:
        assert not demo.mysql_rows("SELECT run_id FROM case_db.support_agent_turn WHERE status IN ('PENDING','RUNNING')", settings)
        assert not demo.mysql_rows("SELECT run_id FROM case_db.agent_binding WHERE dispatch_status='PENDING'", settings)
        with db.connection() as c:
            assert not c.execute("SELECT run_id FROM agent_run WHERE status IN ('QUEUED','RUNNING')").fetchall()
            assert not c.execute("SELECT run_id FROM support_agent_run WHERE status='RUNNING'").fetchall()
            runs = [str(r['run_id']) for r in c.execute('SELECT run_id FROM support_agent_run').fetchall()]
            attempts = c.execute('SELECT COUNT(*) AS n FROM agent_model_attempt').fetchone()['n']
        samples = json.loads((ROOT / 'reports/customer-agent-design-v1/runtime-samples.json').read_text(encoding='utf-8'))
        sample = next(s for s in samples['samples'] if s['name'] == 'A-DELAYED')
        status, auth = demo.http('POST', settings.frontend_url + '/api/v1/auth/login',
                                 body={'username': 'buyer01', 'password': os.environ.get('RESOLVEFLOW_DEMO_PASSWORD', '123456')})
        assert status == 200
        status, conversation = demo.http('POST', settings.frontend_url + '/api/v1/support/conversations',
                                         token=auth['access_token'], body={'line_id': sample['line_id']})
        assert status == 200
        persist(PRIVATE / 'before.json', {'business': snapshot(settings), 'runs': runs, 'general_model_attempts': attempts,
                                         'conversation': conversation})
        files = ['scripts/accept_support_stream_v1.py', 'scripts/check_support_stream_live_v1.cjs']
        persist(OUT / 'plan.json', {'synthetic_data': True, 'live_provider': 'deepseek-flash', 'not_holdout': True,
            'resume_metrics': False, 'turn_limit': 3, 'model_call_upper_bound': 36, 'automatic_retry': False,
            'line_id': sample['line_id'], 'conversation_id': conversation['conversation_id'], 'turns': TURNS,
            'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'files': {f: digest(ROOT / f) for f in files}})
        print('Prepared three turns; provider requests: 0')
    finally:
        db.close()


def execute():
    plan = json.loads((OUT / 'plan.json').read_text(encoding='utf-8'))
    for path, sha in plan['files'].items():
        assert digest(ROOT / path) == sha, 'source changed after freeze'
    marker = PRIVATE / 'execution-started.json'
    with marker.open('x', encoding='utf-8') as stream:
        json.dump({'started': True}, stream)
    settings, db = connect()
    before = json.loads((PRIVATE / 'before.json').read_text(encoding='utf-8'))
    report = {'plan_sha256': digest(OUT / 'plan.json'), 'success': False}
    try:
        with live_guard(LEDGER):
            usage = allowance(LEDGER)
            report['ledger_before'] = usage['used']
            try:
                # The bundled runtime is under the user profile, independent of system Node.
                runtime = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
                env = {**os.environ, 'NODE_PATH': str(runtime / 'node_modules'),
                       'SUPPORT_STREAM_ACCEPTANCE_DIR': str(OUT)}
                result = subprocess.run([str(runtime / 'bin/node.exe'), 'scripts/check_support_stream_live_v1.cjs'],
                                        cwd=ROOT, env=env, timeout=300, check=False)
                report['browser_exit_code'] = result.returncode
            finally:
                with db.connection() as c:
                    runs = []
                    for row in c.execute('SELECT * FROM support_agent_run ORDER BY created_at').fetchall():
                        if str(row['run_id']) in before['runs']:
                            continue
                        calls = c.execute('SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY created_at,kind,position',
                                          (row['run_id'],)).fetchall()
                        runs.append({'run': row, 'calls': calls})
                    attempts = c.execute('SELECT COUNT(*) AS n FROM agent_model_attempt').fetchone()['n']
                models = [call for r in runs for call in r['calls'] if call['kind'] == 'model']
                known = [call['response_json']['usage'] for call in models if call['status'] == 'COMPLETE']
                report.update(runs=runs, model_attempts=len(models), unknown_model_results=len(models) - len(known),
                              input_tokens=sum(u['input_tokens'] for u in known), output_tokens=sum(u['output_tokens'] for u in known),
                              estimated=any(u['estimated'] for u in known), general_model_attempts_delta=attempts-before['general_model_attempts'])
                usage['used'] += len(models)
                usage['save']()
                report['ledger_after'] = usage['used']
                report['preservation'] = snapshot(settings)
                report['business_unchanged'] = report['preservation'] == before['business']
                report['success'] = (report.get('browser_exit_code') == 0 and len(runs) == 3
                    and all(r['run']['status'] == 'SUCCEEDED' for r in runs)
                    and len(models) <= 36 and not report['unknown_model_results']
                    and not report['general_model_attempts_delta'] and report['business_unchanged'])
                persist(OUT / 'runtime-results.json', report)
    finally:
        db.close()
    print(json.dumps({k: report[k] for k in ['success', 'model_attempts', 'ledger_before', 'ledger_after', 'business_unchanged']}))
    if not report['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'execute'])
    parser.add_argument('--directory', type=Path, default=OUT)
    args = parser.parse_args()
    OUT = args.directory.resolve()
    assert OUT.parent == ROOT / 'reports' and OUT.name.startswith('chat-stream-live-v')
    PRIVATE = ROOT / 'tmp' / OUT.name
    prepare() if args.command == 'prepare' else execute()
