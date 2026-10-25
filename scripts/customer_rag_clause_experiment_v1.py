"""One frozen local development ablation of clause indexing and parent deduplication."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from statistics import mean

from resolveflow.harness.token_counting import load_tokenizer
from resolveflow.policies.index import PolicyHit
from resolveflow.policies.retrieval import bm25_scores, embedder

from scripts.customer_quantification_rag import EMBEDDING
from scripts.customer_rag_benchmark import GPU_PYTHON
from scripts.customer_rag_benchmark_v3 import CACHE as PARENT_CACHE
from scripts.customer_rag_benchmark_v3 import PLAN as PARENT_PLAN
from scripts.customer_rag_benchmark_v3 import check as check_parent
from scripts.customer_rag_benchmark_v3 import offline, tokenizer_audit
from scripts.customer_rag_dataset_v3 import DATA as PARENT_DATA
from scripts.customer_rag_dataset_v3 import ROOT, read, sha, write_new
from scripts.customer_rag_rerank import MODEL
from scripts.evaluation.customer_clause_retrieval_v1 import (
    CONFIG,
    VARIANTS,
    build_clauses,
    retrieve,
)
from scripts.evaluation.customer_policy_benchmark_v3 import (
    assemble,
    public_query,
    quality,
)
from scripts.evaluation.customer_rerank import LocalReranker
from scripts.evaluation.customer_rerank_gpu import GPUWorker

DATA = ROOT / 'evals/customer-rag-clause-v1'
REPORT = ROOT / 'reports/customer-rag-clause-v1'
CACHE = ROOT / 'tmp/customer-rag-clause-v1/vectors.json'
PLAN = DATA / 'manifest.json'


def prepare():
    check_parent()
    if CACHE.exists() or (DATA / 'children.json').exists():
        raise FileExistsError('clause preparation already exists')
    offline()
    parents = read(PARENT_DATA / 'chunks.json')['chunks']
    children = build_clauses(parents)
    window = tokenizer_audit(children, read(PARENT_DATA / 'queries.json')['queries'])
    encoder = embedder(str(EMBEDDING))
    tick = time.perf_counter()
    vectors = encoder.embed([c['text'] for c in children])
    elapsed = (time.perf_counter() - tick) * 1000
    if encoder._encoder().max_seq_length < window['embedding_chunk_max_tokens']:
        raise ValueError('embedding runtime window smaller than audited child text')
    write_new(DATA / 'children.json', {'config': CONFIG,
        'parent_index_sha256': sha((PARENT_DATA / 'chunks.json').read_bytes()), 'chunks': children})
    write_new(CACHE, {'children_sha256': sha((DATA / 'children.json').read_bytes()),
        'model': encoder.model, 'revision': encoder.revision,
        'vectors': {c['id']: v for c, v in zip(children, vectors, strict=True)}})
    write_new(REPORT / 'preparation.json', {'children': len(children), 'parents': len(parents),
        'window_audit': window, 'embedding_build_ms': elapsed, 'new_generation_api_calls': 0,
        'new_query_rankings': 0, 'new_ce_forwards': 0,
        'by_subject': {s: sum(c['subject'] == s for c in children)
            for s in sorted({c['subject'] for c in children})}})
    return {'children': len(children), 'window_audit': window, 'new_generation_api_calls': 0}


def freeze():
    check_parent()
    files = ['docs/customer-rag-clause-experiment-v1.md', 'scripts/customer_rag_clause_experiment_v1.py',
        'scripts/evaluation/customer_clause_retrieval_v1.py',
        'agent/tests/unit/test_customer_clause_retrieval_v1.py',
        'agent/tests/unit/test_customer_rag_clause_experiment_v1.py',
        'evals/customer-rag-clause-v1/children.json', 'tmp/customer-rag-clause-v1/vectors.json',
        'reports/customer-rag-clause-v1/preparation.json']
    write_new(PLAN, {'version': 'customer-rag-clause-v1', 'config': CONFIG, 'variants': VARIANTS,
        'parent_manifest_sha256': sha(PARENT_PLAN.read_bytes()),
        'files': {name: sha((ROOT / name).read_bytes()) for name in files},
        'questions_split': 'development_only', 'questions': 40, 'answerable': 32,
        'new_generation_api_calls': 0, 'production_adoption': False})


def check():
    check_parent()
    plan = read(PLAN)
    if plan['parent_manifest_sha256'] != sha(PARENT_PLAN.read_bytes()):
        raise ValueError('original v3 manifest changed')
    if plan['config'] != CONFIG or plan['variants'] != VARIANTS:
        raise ValueError('clause protocol changed')
    for name, expected in plan['files'].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError('frozen clause asset changed: ' + name)
    return plan


def summarize(rows, queries):
    expected = {(q['id'], v, r) for q in queries for v in VARIANTS for r in (1, 2, 3)}
    actual = [(r['id'], r['variant'], r['repeat']) for r in rows]
    if set(actual) != expected or len(set(actual)) != len(actual):
        raise ValueError('incomplete/duplicate clause measurement matrix')
    if any(not math.isfinite(r['elapsed_ms']) or r['elapsed_ms'] < 0 for r in rows):
        raise ValueError('invalid latency')
    answerable = {q['id'] for q in queries if q['answerability'] == 'ANSWERABLE'}
    output = {}
    for variant in VARIANTS:
        selected = [r for r in rows if r['variant'] == variant]
        scored = [r for r in selected if r['repeat'] == 1 and r['id'] in answerable]
        times = sorted(r['elapsed_ms'] for r in selected)
        output[variant] = {'answerable_questions': len(scored),
            'complete_at_3_count': sum(r['quality']['3']['complete'] for r in scored),
            'complete_at_1_count': sum(r['quality']['1']['complete'] for r in scored),
            'top1_any_count': sum(r['quality']['1']['any_required'] for r in scored),
            'timed_requests': len(times), 'mean_ms': mean(times),
            'p50_ms': times[math.ceil(len(times) * .5) - 1],
            'p95_ms': times[math.ceil(len(times) * .95) - 1],
            'mean_body_tokens': mean(r['packet']['body_tokens'] for r in selected),
            'mean_parent_count': mean(len(r['packet']['selected_chunks']) for r in selected),
            'by_category': {c: {'questions': sum(r['category'] == c for r in scored),
                'complete': sum(r['quality']['3']['complete'] for r in scored if r['category'] == c)}
                for c in sorted({q['category'] for q in queries if q['answerability'] == 'ANSWERABLE'})},
            'stable_packets': all(len({r['packet']['body_sha256'] for r in selected if r['id'] == q['id']}) == 1
                for q in queries)}
    return output


def execute(output):
    plan = check()
    if output.exists() or output.with_suffix('.jsonl').exists():
        raise FileExistsError(output)
    offline()
    parents = read(PARENT_DATA / 'chunks.json')['chunks']
    children = read(DATA / 'children.json')['chunks']
    parent_vectors, child_vectors = read(PARENT_CACHE)['vectors'], read(CACHE)['vectors']
    queries = [q for q in read(PARENT_DATA / 'queries.json')['queries'] if q['split'] == 'development']
    tick = time.perf_counter()
    encoder, tokenizer = embedder(str(EMBEDDING)), load_tokenizer()
    worker = GPUWorker(GPU_PYTHON, MODEL, output.with_suffix('.gpu.log'))
    try:
        scorer = LocalReranker(worker, synchronize=worker.synchronize)
        encoder.embed(['售后政策适用范围'])
        bm25_scores(['售后材料与退货政策'], '退货材料')
        warm = [PolicyHit('warm', 'M', 'v', 'h', f'r{i}', f'c{i}', 'h', 'title',
            '人工核查后处理。', 0., 'dense') for i in range(8)]
        scorer.rank('售后核查', warm)
        startup_ms = (time.perf_counter() - tick) * 1000
        rows = []
        with output.with_suffix('.jsonl').open('x', encoding='utf-8', newline='\n') as journal:
            journal.write(json.dumps({'manifest_sha256': sha(PLAN.read_bytes()),
                'split': 'development', 'rounds': 3}) + '\n')
            for repeat in (1, 2, 3):
                order = VARIANTS[repeat - 1:] + VARIANTS[:repeat - 1]
                for query in queries:
                    for variant in order:
                        tick = time.perf_counter()
                        ranked, profile = retrieve(public_query(query), parents, children, parent_vectors,
                            child_vectors, encoder, scorer, variant)
                        packet = assemble(ranked, tokenizer)
                        elapsed = (time.perf_counter() - tick) * 1000
                        packet1, packet5 = assemble(ranked, tokenizer, k=1), assemble(ranked, tokenizer, k=5)
                        row = {'id': query['id'], 'category': query['category'], 'variant': variant,
                            'repeat': repeat, 'elapsed_ms': elapsed, 'timing': profile,
                            'hits': [{'id': c['id'], 'score': float(s)} for c, s in ranked], 'packet': packet,
                            'quality': {str(k): quality(query, p) for k, p in [(1, packet1), (3, packet), (5, packet5)]}}
                        rows.append(row)
                        journal.write(json.dumps(row, ensure_ascii=False) + '\n')
                        journal.flush()
                print(json.dumps({'completed_round': repeat, 'requests': len(rows)}), flush=True)
        check()
        write_new(output, {'version': plan['version'], 'manifest_sha256': sha(PLAN.read_bytes()),
            'parent_manifest_sha256': plan['parent_manifest_sha256'], 'split': 'development',
            'startup_ms': startup_ms, 'gpu': worker.ready, 'new_generation_api_calls': 0,
            'summary': summarize(rows, queries), 'rows': rows})
        return {'requests': len(rows), 'new_generation_api_calls': 0, 'acceptance_rankings': 0}
    finally:
        worker.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'freeze', 'check', 'execute'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.mode == 'prepare':
        print(json.dumps(prepare()))
    elif args.mode == 'freeze':
        freeze()
        print(json.dumps({'frozen': True}))
    elif args.mode == 'check':
        print(json.dumps({'version': check()['version']}))
    elif args.output:
        print(json.dumps(execute(args.output)))
    else:
        parser.error('execute requires a new --output')
