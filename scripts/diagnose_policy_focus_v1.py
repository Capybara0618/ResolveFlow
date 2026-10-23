"""Read-only query diagnostic against pinned real local indexes; no generative model or HTTP."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'agent/src')]

from customer_rag_diagnostic import ReadOnlyDatabase, snapshot
from resolveflow.policies.index import PolicyIndex
from resolveflow.support.embeddings import SupportEmbeddings
from resolveflow.support.retrieval import retrieve_policy

PLAN = ROOT / 'evals/customer-policy-focus-v1/queries.json'
OUT = ROOT / 'reports/customer-policy-focus-v1/retrieval.json'


def execute():
    assert not OUT.exists(), 'Do not overwrite an earlier diagnostic'
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    source = ROOT / plan['source']
    saved = next(r['run'] for r in json.loads(source.read_text(encoding='utf-8'))['runs']
                 if r['run']['run_id'] == plan['source_run'])
    manifest = saved['input_json']['context']['policy_manifest']
    resources = SupportEmbeddings()
    path = str(ROOT / 'tmp/c071-probe/models/BAAI--bge-small-zh-v1.5')
    prewarm_ms = resources.prewarm(path)
    encoder = resources.get(path)
    db = ReadOnlyDatabase('postgresql://agent:agent@127.0.0.1:55433/agent_db')
    try:
        before = snapshot(db)
        rows = []
        for case in plan['cases']:
            for variant, query in case['queries'].items():
                timings = {}
                started = time.perf_counter()
                hits = retrieve_policy(PolicyIndex(db), merchant_id=manifest['merchant_id'],
                    bundle_ids=manifest['bundle_ids'], manifest_hash=manifest['manifest_hash'],
                    generation_ids=saved['generations_json'], query=query, top_k=5, embedder=encoder, timings=timings)
                rules = [h.rule_id for h in hits]
                rows.append({'id': case['id'], 'variant': variant, 'query': query, 'rules': rules,
                    'required': case['required'],
                    'covered_at_3': set(case['required']) <= set(rules[:3]) if case['required'] else None,
                    'covered_at_5': set(case['required']) <= set(rules) if case['required'] else None,
                    'elapsed_ms': (time.perf_counter() - started) * 1000, 'timings': timings,
                    'sources': [{'rule': h.rule_id, 'text': h.text, 'hash': h.content_hash} for h in hits]})
                print(case['id'], variant, rules, flush=True)
        after = snapshot(db)
        assert before == after, 'Retained public data changed'
        result = {'scope': plan['scope'], 'new_llm_calls': 0, 'http_calls': 0, 'public_data_unchanged': True,
                  'prewarm_ms': prewarm_ms, 'rows': rows,
                  'files': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in [PLAN, source, Path(__file__).resolve(),
                                      ROOT / 'agent/src/resolveflow/support/retrieval.py']}}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    finally:
        db.close()


if __name__ == '__main__':
    execute()
