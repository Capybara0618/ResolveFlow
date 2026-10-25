"""Rebuild every recorded clause/parent result and compare fixed development arms offline."""

from __future__ import annotations

import json
from pathlib import Path

from resolveflow.harness.token_counting import load_tokenizer

from scripts.customer_rag_clause_experiment_v1 import (
    DATA,
    PARENT_DATA,
    PLAN,
    REPORT,
    check,
    summarize,
)
from scripts.customer_rag_dataset_v3 import read, sha, write_new
from scripts.evaluation.customer_clause_retrieval_v1 import VARIANTS, project_parents
from scripts.evaluation.customer_policy_benchmark_v3 import assemble, covers, quality


def main():
    check()
    source = REPORT / 'development.json'
    result = read(source)
    if result['manifest_sha256'] != sha(PLAN.read_bytes()):
        raise ValueError('runtime manifest differs')
    queries = [q for q in read(PARENT_DATA / 'queries.json')['queries'] if q['split'] == 'development']
    by_id = {q['id']: q for q in queries}
    parents = {p['id']: p for p in read(PARENT_DATA / 'chunks.json')['chunks']}
    children = {c['id']: c for c in read(DATA / 'children.json')['chunks']}
    tokenizer = load_tokenizer()
    if result['summary'] != summarize(result['rows'], queries):
        raise ValueError('raw matrix/summary differ')
    old = read(REPORT.parent / 'customer-rag-quantification-v3/development.json')
    old_rows = {(r['id'], r['repeat']): r for r in old['rows'] if r['variant'] == 'hybrid-rrf-ce'}
    control_same = True
    max_pair, ce_pairs, skipped = 0, 0, 0
    stages = {v: {'parent_candidate_missing': 0, 'top3_ranking': 0, 'assembly_missing': 0} for v in VARIANTS}
    failures = []
    first = {(r['id'], r['variant']): r for r in result['rows'] if r['repeat'] == 1}
    for row in result['rows']:
        q = by_id[row['id']]
        ranked = [(parents[h['id']], h['score']) for h in row['hits']]
        if any(p['subject'] != q['subject'] or (p['source_id'], p['raw_sha256']) not in
                {(s['source_id'], s['raw_sha256']) for s in q['scope']} for p, _ in ranked):
            raise ValueError('parent escaped brand/version scope')
        child_hits = row['timing']['child_hits']
        all_parent_candidates = ranked
        if child_hits is not None:
            ranked_children = [(children[h['id']], h['score']) for h in child_hits]
            projected = project_parents(ranked_children, parents, naive=row['variant'] == 'clause-ce-naive')
            if [(p['id'], s) for p, s in projected] != [(p['id'], s) for p, s in ranked]:
                raise ValueError('child/parent projection differs')
            all_parent_candidates = project_parents(ranked_children, parents, naive=False)
        else:
            original = old_rows[(row['id'], row['repeat'])]
            control_same &= [h['id'] for h in row['hits']] == [h['id'] for h in original['hits']]
            control_same &= row['packet'] == original['packet'] and row['quality'] == original['quality']
        for k in (1, 3, 5):
            packet = assemble(ranked, tokenizer, k=k)
            if quality(q, packet) != row['quality'][str(k)] or (k == 3 and packet != row['packet']):
                raise ValueError('saved evidence/score differs from source rebuild')
        skipped += len(row['packet']['skipped_chunks'])
        profile = row['timing']['rerank']
        if profile:
            ce_pairs += profile['pairs']
            max_pair = max(max_pair, profile['max_pair_tokens'])
        if row['repeat'] != 1 or q['answerability'] != 'ANSWERABLE' or row['quality']['3']['complete']:
            continue
        atoms = q['required_evidence']
        candidate_pieces = [p for c, _ in all_parent_candidates for p in c['fragments']]
        raw_top3 = [p for c, _ in ranked[:3] for p in c['fragments']]
        stage = 'parent_candidate_missing' if not all(covers(candidate_pieces, a) for a in atoms) else (
            'assembly_missing' if all(covers(raw_top3, a) for a in atoms) else 'top3_ranking')
        stages[row['variant']][stage] += 1
        if row['variant'] == 'clause-ce-grouped':
            failures.append({'id': q['id'], 'query': q['query'], 'category': q['category'],
                'stage': stage, 'evidence': [{**a, 'covered_top3': covers(row['packet']['pieces'], a),
                    'minimum_parent_rank_prefix': next((k for k in range(1, len(ranked) + 1)
                        if covers([p for c, _ in ranked[:k] for p in c['fragments']], a)), None)} for a in atoms],
                'parent_hits': row['hits'], 'child_hits': child_hits})
    answerable = [q for q in queries if q['answerability'] == 'ANSWERABLE']
    deltas = []
    for before, after in [('packed-ce', 'clause-ce-grouped'), ('clause-ce-naive', 'clause-ce-grouped'),
            ('clause-dense', 'clause-ce-grouped'), ('clause-bm25', 'clause-ce-grouped'),
            ('clause-rrf', 'clause-ce-grouped')]:
        gained, lost = [], []
        for q in answerable:
            a, b = (first[(q['id'], v)]['quality']['3']['complete'] for v in [before, after])
            if a != b:
                (gained if b else lost).append(q['id'])
        deltas.append({'baseline': before, 'candidate': after, 'questions': 32,
            'gained': gained, 'regressed': lost, 'net_count': len(gained) - len(lost)})
    complex_ids = [q['id'] for q in answerable if q['category'] != 'ordinary']
    complex_counts = {v: sum(first[(identity, v)]['quality']['3']['complete'] for identity in complex_ids)
        for v in VARIANTS}
    analysis = {'source_sha256': sha(source.read_bytes()), 'manifest_sha256': sha(PLAN.read_bytes()),
        'analyzer_sha256': sha(Path(__file__).read_bytes()), 'raw_rows_checked': len(result['rows']),
        'packet_scores_rebuilt': len(result['rows']) * 3, 'child_parent_projection_verified': True,
        'packed_control_matches_previous_ranks_packets_scores': bool(control_same),
        'complex_questions': len(complex_ids), 'complex_complete_counts': complex_counts,
        'paired_changes': deltas, 'failure_stages': stages, 'grouped_failures': failures,
        'measured_ce_pairs': ce_pairs, 'generic_warmup_ce_pairs': 8, 'measured_ce_max_tokens': max_pair,
        'top3_budget_skips': skipped, 'new_generation_api_calls': 0, 'acceptance_rankings': 0,
        'all_parent_rankings_stable': all(len({tuple(h['id'] for h in r['hits']) for r in result['rows']
            if r['id'] == q['id'] and r['variant'] == v}) == 1 for q in queries for v in VARIANTS)}
    write_new(REPORT / 'analysis.json', analysis)
    print(json.dumps({k: analysis[k] for k in ['complex_complete_counts', 'paired_changes',
        'failure_stages', 'packed_control_matches_previous_ranks_packets_scores']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
