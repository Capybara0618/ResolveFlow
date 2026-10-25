"""Recompute the frozen development retrieval results without models or acceptance rankings."""

from __future__ import annotations

import json

from resolveflow.harness.token_counting import load_tokenizer

from scripts.customer_rag_benchmark_v3 import PLAN, summarize
from scripts.customer_rag_dataset_v3 import DATA, ROOT, read, sha, write_new
from scripts.evaluation.customer_policy_benchmark_v3 import (
    VARIANTS,
    assemble,
    covers,
    quality,
)

SOURCE = ROOT / 'reports/customer-rag-quantification-v3/development.json'


def selected_queries(dataset):
    return [q for q in dataset['queries'] if q['split'] == 'development']


def paired_delta(first, ids, baseline, candidate):
    gained, regressed = [], []
    for identity in ids:
        old = first[(identity, baseline)]['quality']['3']['complete']
        new = first[(identity, candidate)]['quality']['3']['complete']
        if old is False and new is True:
            gained.append(identity)
        elif old is True and new is False:
            regressed.append(identity)
    return {'baseline': baseline, 'candidate': candidate, 'questions': len(ids),
        'gained': gained, 'regressed': regressed, 'net_count': len(gained) - len(regressed),
        'percentage_point_change': (len(gained) - len(regressed)) / len(ids) * 100}


def analyze(result, dataset, chunks, tokenizer):
    queries = selected_queries(dataset)
    if result['split'] != 'development' or result['generic_smoke_only'] is not False:
        raise ValueError('development result required')
    expected = summarize(result['rows'], queries)
    if result['summary'] != expected:
        raise ValueError('saved summary differs from raw matrix')
    by_id = {q['id']: q for q in queries}
    chunk_index = {c['id']: c for c in chunks}
    for row in result['rows']:
        query = by_id[row['id']]
        scope = {(s['source_id'], s['raw_sha256']) for s in query['scope']}
        ranked = [(chunk_index[h['id']], h['score']) for h in row['hits']]
        if any(c['subject'] != query['subject'] or (c['source_id'], c['raw_sha256']) not in scope
                for c, _ in ranked):
            raise ValueError('rank escaped source scope')
        if len({c['id'] for c, _ in ranked}) != len(ranked):
            raise ValueError('duplicate ranked chunk')
        for k in (1, 3, 5):
            packet = assemble(ranked, tokenizer, k=k)
            if row['quality'][str(k)] != quality(query, packet):
                raise ValueError('source-span quality differs')
            if k == 3 and packet != row['packet']:
                raise ValueError('persisted evidence packet differs')
    first = {(r['id'], r['variant']): r for r in result['rows'] if r['repeat'] == 1}
    answerable = [q for q in queries if q['answerability'] == 'ANSWERABLE']
    ids = [q['id'] for q in answerable]
    focus = [q['id'] for q in answerable if q['category'] != 'ordinary']
    groups = {'all_answerable': ids, 'complex': focus,
        'ordinary': [q['id'] for q in answerable if q['category'] == 'ordinary']}
    metrics = {}
    for name, members in groups.items():
        metrics[name] = {}
        for variant in VARIANTS:
            chosen = [first[(identity, variant)] for identity in members]
            count = sum(r['quality']['3']['complete'] for r in chosen)
            metrics[name][variant] = {'questions': len(members), 'complete_at_3_count': count,
                'complete_at_3_rate': count / len(members),
                'top1_any_rate': sum(r['quality']['1']['any_required'] for r in chosen) / len(members),
                'complete_at_1_rate': sum(r['quality']['1']['complete'] for r in chosen) / len(members)}
    failures, source_stages = [], {}
    for variant in VARIANTS:
        stages = {'candidate_missing': 0, 'top3_ranking': 0, 'assembly_missing': 0}
        for query in answerable:
            row = first[(query['id'], variant)]
            if row['quality']['3']['complete']:
                continue
            originals = [chunk_index[h['id']] for h in row['hits']]
            all_pieces = [p for c in originals for p in c['fragments']]
            top3_pieces = [p for c in originals[:3] for p in c['fragments']]
            atoms = query['required_evidence']
            candidate_complete = all(covers(all_pieces, a) for a in atoms)
            raw_top3_complete = all(covers(top3_pieces, a) for a in atoms)
            stage = 'candidate_missing' if not candidate_complete else (
                'assembly_missing' if raw_top3_complete else 'top3_ranking')
            stages[stage] += 1
            if variant != 'hybrid-rrf-ce':
                continue
            evidence = []
            for atom in atoms:
                minimum = next((k for k in range(1, len(originals) + 1)
                    if covers([p for c in originals[:k] for p in c['fragments']], atom)), None)
                evidence.append({**atom, 'minimum_rank_prefix': minimum,
                    'covered_in_top3': covers(row['packet']['pieces'], atom)})
            failures.append({'id': query['id'], 'category': query['category'], 'query': query['query'],
                'stage': stage, 'answer_points': query['answer_points'], 'evidence': evidence,
                'comparison': {v: first[(query['id'], v)]['quality'] for v in VARIANTS},
                'ce_top5': row['hits'][:5]})
        source_stages[variant] = stages
    return {'version': 'customer-rag-development-analysis-v3', 'group_metrics': metrics,
        'paired_changes': [paired_delta(first, ids, a, b) for a, b in [
            ('dense', 'hybrid-rrf'), ('hybrid-rrf', 'hybrid-rrf-ce'),
            ('dense', 'hybrid-rrf-ce'), ('bm25', 'hybrid-rrf-ce')]],
        'failure_stages': source_stages, 'ce_failures': failures,
        'raw_rows_checked': len(result['rows']), 'packet_rebuilds_checked': len(result['rows']) * 3,
        'scope_documents': sorted({r['timing']['scoped_documents'] for r in result['rows']}),
        'scope_candidates': sorted({r['timing']['scoped_candidates'] for r in result['rows']}),
        'ce_pairs': sum(r['timing']['rerank']['pairs'] for r in result['rows'] if r['timing']['rerank']),
        'ce_max_pair_tokens': max(r['timing']['rerank']['max_pair_tokens'] for r in result['rows']
            if r['timing']['rerank']),
        'full_rankings_stable': all(len({tuple(h['id'] for h in r['hits']) for r in result['rows']
            if r['id'] == q['id'] and r['variant'] == v}) == 1 for q in queries for v in VARIANTS),
        'new_model_inferences': 0, 'acceptance_rankings_read': 0,
        'final_answer_accuracy_measured': False}


if __name__ == '__main__':
    result = read(SOURCE)
    if result['manifest_sha256'] != sha(PLAN.read_bytes()):
        raise ValueError('runtime manifest differs')
    analysis = analyze(result, read(DATA / 'queries.json'), read(DATA / 'chunks.json')['chunks'], load_tokenizer())
    analysis.update(source_sha256=sha(SOURCE.read_bytes()), manifest_sha256=sha(PLAN.read_bytes()),
        analyzer_sha256=sha(__import__('pathlib').Path(__file__).read_bytes()))
    write_new(ROOT / 'reports/customer-rag-quantification-v3/development-analysis.json', analysis)
    print(json.dumps({k: analysis[k] for k in ['group_metrics', 'paired_changes', 'failure_stages', 'ce_pairs']},
        ensure_ascii=False))
