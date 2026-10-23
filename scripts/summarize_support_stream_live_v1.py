"""Offline summary of the three original live turns; never calls a model or business API."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/chat-stream-live-v3'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def summarize():
    first = ROOT / 'reports/chat-stream-live-v2'
    original = ROOT / 'reports/chat-stream-live-v1'
    first_runs, remaining = read(first / 'runtime-results.json'), read(OUT / 'runtime-results.json')
    assert read(original / 'runtime-results.json')['model_attempts'] == 0
    assert first_runs['model_attempts'] == 7 and remaining['model_attempts'] == 3
    assert first_runs['ledger_after'] == remaining['ledger_before']
    assert remaining['ledger_after'] - first_runs['ledger_before'] == 10
    runs = first_runs['runs'] + remaining['runs']
    assert len(runs) == 3 and len({r['run']['run_id'] for r in runs}) == 3
    assert all(r['run']['status'] == 'SUCCEEDED' for r in runs)
    assert all(c['status'] == 'COMPLETE' for r in runs for c in r['calls'])
    assert first_runs['business_unchanged'] and remaining['business_unchanged']
    browsers = [read(first / 'browser.json'), read(OUT / 'browser.json')]
    assert len(browsers[0]['writes']) == 3 and len(browsers[1]['writes']) == 2  # Login plus 2/1 messages.
    assert not browsers[1]['errors'] and len(browsers[1]['checks']) == 2
    for measured in (browsers[0]['turns'][0], browsers[1]['turns'][0]):
        assert measured['first_body_ms'] < measured['completed_ms']
        assert measured['formal_message_delta'] == 1 and measured['generation_removed']
    rows = read(OUT / 'backend-events.json')
    timings = []
    for index, run in enumerate(runs):
        events = [row for row in rows if row[0] == run['run']['run_id']]
        point = lambda kind, events=events: datetime.fromisoformat(next(e[3] for e in events if e[2] == kind))
        elapsed = lambda kind, point=point: round((point(kind) - point('turn.accepted')).total_seconds() * 1000, 3)
        browser = browsers[0]['turns'][index] if index < 2 else browsers[1]['turns'][0]
        timings.append({'original_turn': index + 1, 'run_id': run['run']['run_id'],
                        'model_calls': sum(c['kind'] == 'model' for c in run['calls']),
                        'browser_first_body_ms': browser.get('first_body_ms'),
                        'browser_completed_ms': browser.get('completed_ms'),
                        'server_first_delta_from_accept_ms': elapsed('answer.delta'),
                        'server_commit_from_accept_ms': elapsed('answer.committed'),
                        'server_claim_from_accept_ms': elapsed('turn.started')})
    files = sorted(p for directory in (original, first, OUT) for p in directory.iterdir()
                   if p.is_file() and p.name not in {'README.md', 'summary.json'})
    return {'scope': 'three original synthetic business turns with a real provider; not p95/holdout quality',
            'backend_published': 3, 'distinct_runs': 3, 'model_attempts': 10, 'unknown_model_results': 0,
            'provider_input_tokens': first_runs['input_tokens'] + remaining['input_tokens'],
            'provider_output_tokens': first_runs['output_tokens'] + remaining['output_tokens'],
            'provider_usage_estimated': first_runs['estimated'] or remaining['estimated'],
            'financial_order_shipment_policy_baseline_preserved': True,
            'extra_merchant_message_in_v1': True, 'full_reload_requires_login': True,
            'sse_transport_reconnect_passed': True, 'normal_viewport': '1440x1000',
            'semantic_quality_unresolved': ['policy_relevance_and_coverage', 'guide_existing_ticket_branch', 'duplicate_navigation'],
            'timings': timings,
            'files': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}


if __name__ == '__main__':
    value = summarize()
    target = OUT / 'summary.json'
    if target.exists():
        assert read(target) == value, 'frozen summary differs'
    else:
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: value[k] for k in ['backend_published', 'model_attempts', 'provider_input_tokens', 'provider_output_tokens']}))
