"""Validate optional branch retrieval on retained real indexes; default rankings must stay equal."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'agent/src')]

import httpx
from customer_rag_diagnostic import ReadOnlyDatabase, snapshot
from resolveflow.policies.index import PolicyIndex
from resolveflow.support.embeddings import SupportEmbeddings
from resolveflow.support.protocol import SupportInput
from resolveflow.support.sources import BoundSources


def execute():
    baseline_path = ROOT / 'reports/customer-policy-focus-v1/retrieval.json'
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    plan = json.loads((ROOT / 'evals/customer-policy-focus-v1/queries.json').read_text(encoding='utf-8'))
    source_path = ROOT / plan['source']
    saved = next(r['run'] for r in json.loads(source_path.read_text(encoding='utf-8'))['runs']
                 if r['run']['run_id'] == plan['source_run'])
    output = ROOT / 'reports/customer-policy-focus-v1/branches.json'
    assert not output.exists(), 'Do not overwrite a previous confirmation'
    for file, digest in baseline['files'].items():
        if file.endswith('retrieval.py'):
            continue  # Production change is intentionally confirmed against the prior frozen result.
        assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == digest
    resources = SupportEmbeddings()
    path = str(ROOT / 'tmp/c071-probe/models/BAAI--bge-small-zh-v1.5')
    prewarm = resources.prewarm(path)
    db = ReadOnlyDatabase('postgresql://agent:agent@127.0.0.1:55433/agent_db')
    http_calls = []

    def no_network(request):
        http_calls.append(str(request.url))
        raise AssertionError('No HTTP allowed in the retrieval confirmation')

    try:
        before = snapshot(db)
        with httpx.Client(transport=httpx.MockTransport(no_network)) as client:
            source = BoundSources(SupportInput.model_validate(saved['input_json']), case_url='http://unused.local',
                token='', client=client, index=PolicyIndex(db), embedder=resources.get(path))
            source.generations = saved['generations_json']
            unchanged = []
            for row in baseline['rows']:
                hits = source.search(row['query'], 5)
                rules = [h['data']['rule_id'] for h in hits]
                assert rules == row['rules'], row['id']
                unchanged.append({'id': row['id'], 'variant': row['variant'], 'rules': rules})
            contextual = next(r for r in baseline['rows'] if r['id'] == 'delayed-followup' and r['variant'] == 'standalone-context')
            conditional = next(r for r in baseline['rows'] if r['id'] == 'hypothetical-loss')
            queries = [contextual['query'], conditional['query']]
            original = next(r for r in baseline['rows'] if r['variant'] == 'saved-original')
            start = time.perf_counter()
            hits = source.search(original['query'], 3, sub_queries=queries)
            elapsed = (time.perf_counter() - start)*1000
            ids = [h['data']['rule_id'] for h in hits]
            assert ids[:2] == [contextual['rules'][0], conditional['rules'][0]]
            assert set(original['required']) <= set(ids)
            originals = {s['hash']: s['text'] for r in baseline['rows'] for s in r['sources']}
            assert all(h['data']['text'] == originals[h['data']['content_hash']] for h in hits)
        assert before == snapshot(db) and not http_calls
        files = [baseline_path, source_path, Path(__file__).resolve(),
                 *[(ROOT / 'agent/src/resolveflow/support' / name) for name in
                   ['protocol.py', 'guidance.py', 'engine.py', 'sources.py', 'retrieval.py']]]
        output.write_bytes((json.dumps({'new_llm_calls': 0, 'http_calls': 0, 'public_data_unchanged': True,
            'synthetic_branch_queries': True, 'not_holdout': True, 'default_rankings_equal': unchanged,
            'sub_queries': queries, 'rules': ids, 'required_at_3_covered': True, 'elapsed_ms': elapsed,
            'prewarm_ms': prewarm, 'sources': hits,
            'files': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}},
            ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
        print(json.dumps({'default_queries_unchanged': len(unchanged), 'branch_rules': ids, 'elapsed_ms': elapsed}))
    finally:
        db.close()


if __name__ == '__main__':
    execute()
