"""Read retained synthetic browser-acceptance records; never send customer/Agent work."""

from __future__ import annotations

import json
from pathlib import Path

import reviewer_demo as demo
from customer_agent_live_acceptance import digest, save, snapshot
from resolveflow.runtime.db import Database

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'tmp/customer-agent-demo-v2'
OUT = ROOT / 'reports/customer-agent-demo-v2'


def main():
    settings = demo.settings_from_environ()
    demo.guard(settings)
    assert settings.project == demo.PROJECT and settings.ports == demo.DEFAULT_PORTS
    old = set(json.loads((PRIVATE / 'run-ids-before.json').read_text(encoding='utf-8')))
    database = Database(settings.agent_dsn)
    try:
        with database.connection() as conn:
            rows = conn.execute('SELECT * FROM support_agent_run ORDER BY created_at').fetchall()
            runs = []
            for row in rows:
                if str(row['run_id']) in old:
                    continue
                assert row['status'] in {'SUCCEEDED', 'FAILED'}
                calls = conn.execute('SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY created_at,kind,position',
                                     (row['run_id'],)).fetchall()
                assert all(call['status'] == 'COMPLETE' for call in calls)
                runs.append({'run': row, 'calls': calls})
            assert len(runs) == 3
            conversation = str(runs[0]['run']['input_json']['conversation_id'])
            assert all(str(r['run']['input_json']['conversation_id']) == conversation for r in runs)
    finally:
        database.close()

    def call(method, path, token=None, body=None, expected=200):
        status, value = demo.http(method, settings.frontend_url + path, token=token, body=body)
        assert status == expected, (path, status)
        return value

    def login(username):
        return call('POST', '/api/v1/auth/login', body={'username': username, 'password': '123456'})['access_token']

    buyer = call('GET', '/api/v1/support/conversations/' + conversation, login('buyer01'))
    ticket = buyer['ticket']['ticket_id']
    path = '/api/v1/support/tickets/' + ticket
    merchant = call('GET', path, login('admin02'))
    call('GET', path, login('admin01'), expected=404)
    call('GET', '/api/v1/support/conversations/' + conversation, login('buyer02'), expected=404)
    assert merchant['ticket']['status'] == buyer['ticket']['status'] == 'RESOLVED'
    assert len(merchant['ticket']['shared_messages']) == 2
    assert {m['text'] for m in merchant['ticket']['shared_messages']} == {
        r['run']['input_json']['context']['current_request'] for r in runs[:2]}
    assert not merchant['ticket'].get('report')
    assert not any(message['author'] == 'ASSISTANT' for message in merchant['messages'])
    hidden = runs[2]['run']['input_json']['context']['current_request']
    assert hidden in [message['text'] for message in buyer['messages']]
    assert hidden not in json.dumps(merchant, ensure_ascii=False)
    assert 'B店台灯的独立咨询记录。' not in json.dumps(merchant, ensure_ascii=False)
    before = json.loads((PRIVATE / 'before.json').read_text(encoding='utf-8'))
    after = snapshot(settings)
    assert before['business'] == after
    model_calls = [c for r in runs for c in r['calls'] if c['kind'] == 'model']
    tools = [c for r in runs for c in r['calls'] if c['kind'] == 'tool']
    usage = [c['response_json']['usage'] for c in model_calls]
    result = {
        'synthetic_business_data': True, 'model_mode': 'live', 'not_holdout': True,
        'runs': runs, 'buyer': buyer, 'merchant': merchant,
        'checks': {'selected_originals_only': True, 'private_consultation_hidden': True,
                   'other_merchant_and_buyer_404': True, 'customer_resolved': True,
                   'business_and_policy_index_unchanged': True},
        'spend': {'model_requests': len(model_calls), 'tool_calls': len(tools),
                  'input_tokens': sum(u['input_tokens'] for u in usage),
                  'output_tokens': sum(u['output_tokens'] for u in usage),
                  'estimated': any(u['estimated'] for u in usage)},
        'preservation': after,
    }
    target = OUT / 'runtime-results.json'
    if target.exists():
        assert json.loads(target.read_text(encoding='utf-8')) == json.loads(json.dumps(result, default=str)), 'frozen report differs'
    else:
        save(target, result)
    print(json.dumps({'runs': len(runs), 'published': sum(r['run']['status'] == 'SUCCEEDED' for r in runs),
                      'spend': result['spend'], 'raw_sha256': digest(result)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
