"""Fixed-query local retrieval/evidence ablation; no generation API or production changes."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from statistics import mean, median

from resolveflow.harness.token_counting import load_tokenizer
from resolveflow.policies.retrieval import bm25_scores, embedder

from scripts.customer_quantification_rag import EMBEDDING, fuse
from scripts.customer_workflow_comparison_prepare import digest, read
from scripts.evaluation.customer_evidence import assemble
from scripts.evaluation.customer_quantification_data import ROOT, rag_data
from scripts.policy_codex_review import sufficiently_covered
from scripts.policy_query_eval import coverage, rank

VERSION = 'customer-rag-quantification-v2'
PLAN = ROOT / 'evals' / VERSION / 'manifest.json'
VARIANTS = ['bm25-direct', 'dense-direct', 'rrf-legacy-direct', 'rrf-positive-direct',
    'bm25-parent', 'rrf-positive-parent']
CONFIG = {'variants': VARIANTS, 'rounds': 3, 'queries': 40, 'answerable': 32, 'candidate_k': 20,
    'rrf_constant': 60, 'seed_k': [3, 5], 'timed_seed_k': 3, 'max_chars': 8000, 'max_tokens': 4096,
    'primary_candidate': 'rrf-positive-parent', 'primary_baseline': 'bm25-direct',
    'strong_structure_control': 'bm25-parent', 'query_rewrite': False,
    'cpu_threads': 4, 'production_adoption': False, 'independent_holdout': False,
    'latency_scope': 'Query to Top3-seeded evidence body; excludes startup/HTTP/PG/answer generation/label scoring'}
AGENT_RUNTIME = ROOT / 'reports/customer-workflow-comparison-v2/agent-runtime-complete.json'


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as file:
        json.dump(value, file, ensure_ascii=False, indent=2, default=str)
        file.write('\n')


def public_query(query):
    return {k: query[k] for k in ('query', 'subject', 'scope')}


def load_data():
    queries, atoms, children, index = rag_data()
    # The generic scoring catalog omits table rendering metadata; recover it from the same frozen source.
    draft = read(ROOT / 'tmp/policy-documents-v1/drafts-audited.json')
    for document in draft['documents']:
        for block in document['blocks']:
            target = index['blocks'][(document['source_id'], document['raw_sha256'], block['id'])]
            if target['text'] != block['text'] or target['text_sha256'] != block['text_sha256']:
                raise ValueError('source rendering metadata does not match the frozen block')
            target.update(kind=block['kind'], rows=block.get('rows', []))
    return queries, atoms, children, index


def fuse_routes(dense, lexical, title, *, positive):
    return fuse([dense, [(c, s) for c, s in lexical if not positive or s > 0],
        [(c, s) for c, s in title if not positive or s > 0]], limit=CONFIG['candidate_k'])


def retrieve(query, children, encoder, variant):
    if variant not in VARIANTS:
        raise ValueError('unknown retrieval method')
    started = time.perf_counter()
    vector = encoder.embed([query['query']])[0] if variant.startswith(('dense', 'rrf')) else None
    encoded = time.perf_counter()
    if variant.startswith('bm25'):
        ranked = rank(query, children, 'bm25')
    elif variant.startswith('dense'):
        ranked = rank(query, children, 'dense', vector)
    else:
        dense, lexical = rank(query, children, 'dense', vector), rank(query, children, 'bm25')
        scoped = [c for c, _ in dense]
        title_scores = bm25_scores([' > '.join(c['section_path']) for c in scoped], query['query'])
        title = sorted(zip(scoped, title_scores, strict=True), key=lambda pair: (-pair[1], pair[0]['id']))
        ranked = fuse_routes(dense, lexical, title, positive='positive' in variant)
    return ranked, {'encode_ms': (encoded - started) * 1000,
        'candidate_fusion_ms': (time.perf_counter() - encoded) * 1000}


def packet_covered(atoms, packet):
    spans = [{'source_id': p['source_id'], 'raw_sha256': p['raw_sha256'], 'fragments': [p]}
        for p in packet['pieces']]
    return sufficiently_covered(atoms, lambda atom: coverage(spans, atom))


def packet_record(packet, *, full):
    return {k: v for k, v in packet.items() if k != 'body' and (full or k != 'pieces')}


def percentile(values, fraction):
    values = sorted(values)
    return values[math.ceil(len(values) * fraction) - 1] if values else None


def summarize(rows, queries):
    expected = {(q['id'], v, r) for q in queries for v in VARIANTS for r in (1, 2, 3)}
    actual = [(r['id'], r['variant'], r['repeat']) for r in rows]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError('incomplete/duplicate measurement matrix')
    if any(not math.isfinite(r['elapsed_ms']) or r['elapsed_ms'] < 0 for r in rows):
        raise ValueError('invalid measured latency')
    groups = {}
    for variant in VARIANTS:
        selected = [r for r in rows if r['variant'] == variant]
        quality = [r for r in selected if r['repeat'] == 1 and r['answerability'] == 'ANSWERABLE']
        stable = all(len({(tuple(r['hits']), r['packet']['packet_sha256']) for r in selected
            if r['id'] == q['id']}) == 1 for q in queries)
        values = [r['elapsed_ms'] for r in selected]
        groups[variant] = {'answerable_questions': len(quality), 'timed_requests': len(selected),
            'direct_complete_at_3': sum(r['direct_complete_at_3'] for r in quality),
            'direct_complete_at_5': sum(r['direct_complete_at_5'] for r in quality),
            'packet_complete_count': sum(r['packet_complete'] for r in quality),
            'packet_complete_rate': mean(r['packet_complete'] for r in quality),
            'packet_complete_at_5': sum(r['packet_complete_at_5'] for r in quality),
            'mean_ms': mean(values), 'p50_ms': percentile(values, .5), 'p95_ms': percentile(values, .95),
            'mean_body_tokens': mean(r['packet']['body_tokens'] for r in selected),
            'median_body_tokens': median(r['packet']['body_tokens'] for r in selected),
            'ranking_and_packet_stable': stable}
    return groups


def metadata():
    old = read(ROOT / 'evals/customer-quantification-v1/rag-manifest.json')
    names = set(old['files']) | {'docs/customer-rag-quantification-v2.md',
        'scripts/customer_rag_quantification_v2.py', 'agent/tests/unit/test_customer_rag_quantification_v2.py',
        'scripts/evaluation/customer_evidence.py', 'scripts/customer_workflow_comparison_prepare.py',
        'agent/src/resolveflow/harness/token_counting.py',
        'agent/src/resolveflow/assets/deepseek-v41/tokenizer.json.gz',
        'agent/src/resolveflow/support/sources.py', 'agent/src/resolveflow/support/retrieval.py',
        'agent/src/resolveflow/policies/index.py', 'scripts/customer_rag_diagnostic.py',
        AGENT_RUNTIME.relative_to(ROOT).as_posix(), 'evals/customer-quantification-v1/rag-manifest.json'}
    return {'version': VERSION, 'config': CONFIG,
        'files': {n: digest(ROOT / n) for n in sorted(names)},
        'embedding_files': {n: digest(EMBEDDING / n) for n in old['embedding_files']}}


def check():
    value = read(PLAN)
    if value != metadata():
        raise ValueError('frozen source/configuration differs')
    return value


def execute(output):
    check()
    if output.exists():
        raise FileExistsError(output)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    started = time.perf_counter()
    import torch
    torch.set_num_threads(CONFIG['cpu_threads'])
    torch.set_num_interop_threads(1)
    queries, atoms, children, index = load_data()
    encoder, tokenizer = embedder(str(EMBEDDING)), load_tokenizer()
    encoder.embed(['售后政策的适用范围'])
    bm25_scores(['人工核验后处理'], '人工核验')
    startup_ms = (time.perf_counter() - started) * 1000
    rows = []
    for repeat in range(1, 4):
        order = VARIANTS[repeat - 1:] + VARIANTS[:repeat - 1]
        for original in queries:
            query = public_query(original)
            for variant in order:
                begin = time.perf_counter()
                ranked, profile = retrieve(query, children, encoder, variant)
                assembly_at = time.perf_counter()
                packet = assemble(query, [c for c, _ in ranked[:3]], children, index, tokenizer,
                    expand=variant.endswith('-parent'), max_chars=CONFIG['max_chars'], max_tokens=CONFIG['max_tokens'])
                elapsed = (time.perf_counter() - begin) * 1000
                profile['assembly_ms'] = (time.perf_counter() - assembly_at) * 1000
                packet5 = assemble(query, [c for c, _ in ranked[:5]], children, index, tokenizer,
                    expand=variant.endswith('-parent'), max_chars=CONFIG['max_chars'], max_tokens=CONFIG['max_tokens'])
                evidence = atoms[original['id']]
                rows.append({'id': original['id'], 'variant': variant, 'repeat': repeat,
                    'answerability': original['answerability'], 'elapsed_ms': elapsed, 'timing': profile,
                    'hits': [c['id'] for c, _ in ranked],
                    'direct_complete_at_3': sufficiently_covered(evidence,
                        lambda a, ranked=ranked: coverage([c for c, _ in ranked[:3]], a)),
                    'direct_complete_at_5': sufficiently_covered(evidence,
                        lambda a, ranked=ranked: coverage([c for c, _ in ranked[:5]], a)),
                    'packet_complete': packet_covered(evidence, packet),
                    'packet_complete_at_5': packet_covered(evidence, packet5),
                    'packet': packet_record(packet, full=repeat == 1),
                    'packet5': packet_record(packet5, full=repeat == 1)})
        print({'completed_round': repeat, 'requests': len(rows)}, flush=True)
    check()
    write_new(output, {'version': VERSION, 'manifest_sha256': digest(PLAN), 'config': CONFIG,
        'startup_and_warmup_ms': startup_ms, 'new_generation_api_calls': 0,
        'real_query_embedding_batches': sum(r['variant'].startswith(('dense', 'rrf')) for r in rows),
        'summaries': summarize(rows, queries), 'rows': rows})


def business(output):
    from resolveflow.policies.index import PolicyIndex
    from resolveflow.support.protocol import SupportInput
    from resolveflow.support.sources import BoundSources

    from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot
    check()
    runtime = read(AGENT_RUNTIME)
    pins = {r['run_id']: r['generations_json'] for r in runtime['all_runs']}
    db = ReadOnlyDatabase('postgresql://agent:agent@127.0.0.1:55433/agent_db')
    rows = []
    class Journal:
        def __init__(self, generation):
            self.value = generation
        def generations(self):
            return self.value
        def pin_generations(self, _):
            raise AssertionError('read-only measurement cannot repin generations')
    try:
        before = snapshot(db)
        index = PolicyIndex(db)
        for row in runtime['rows']:
            if row['variant'] != 'agent':
                continue
            for tool_index, tool in enumerate(row['tools']):
                if tool['category'] != 'POLICY':
                    continue
                request = SupportInput.model_validate(row['input'])
                source = BoundSources(request, case_url='http://unused.local', token='readonly-measurement',
                    index=index, journal=Journal(pins[row['run_id']]))
                try:
                    for repeat in (1, 2, 3):
                        begin = time.perf_counter()
                        value = source.search(tool['query'], tool['top_k'], sub_queries=tool.get('sub_queries'))
                        elapsed = (time.perf_counter() - begin) * 1000
                        if value != tool['result']:
                            raise ValueError('bound source differs from actual Agent result')
                        rows.append({'case_id': row['case_id'], 'turn': row['turn'], 'tool_index': tool_index,
                            'repeat': repeat, 'query': tool['query'], 'elapsed_ms': elapsed, 'rules': len(value),
                            'mode': value[0]['retrieval_context']['mode'], 'generation_ids': pins[row['run_id']]})
                finally:
                    source.close()
        after = snapshot(db)
        if before != after:
            raise ValueError('retained public data changed')
        check()
        values = [r['elapsed_ms'] for r in rows]
        write_new(output, {'version': VERSION, 'manifest_sha256': digest(PLAN), 'agent_runtime_sha256': digest(AGENT_RUNTIME),
            'scope': 'actual PG BoundSources.search tiny policy set; no HTTP/embedding/answer generation',
            'source_parity_with_actual_agent': True, 'query_tool_calls': len(rows) // 3, 'timed_requests': len(rows),
            'mean_ms': mean(values), 'p50_ms': percentile(values, .5), 'p95_ms': percentile(values, .95),
            'public_before': before, 'public_after': after, 'new_generation_api_calls': 0, 'rows': rows})
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['freeze', 'check', 'execute', 'business'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.mode == 'freeze':
        load_data()
        write_new(PLAN, metadata())
    elif args.mode == 'check':
        print({'version': check()['version'], 'new_generation_api_calls': 0})
    elif not args.output:
        parser.error('new --output required')
    elif args.mode == 'execute':
        execute(args.output)
    else:
        if args.output.exists():
            raise FileExistsError(args.output)
        business(args.output)


if __name__ == '__main__':
    main()
