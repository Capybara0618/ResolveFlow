"""Clause-local retrieval with original, bounded parent contexts; no Gold-dependent selection."""

from __future__ import annotations

import json
import time

from scripts.customer_rag_dataset_v3 import sha
from scripts.evaluation.customer_policy_benchmark_v3 import retrieve as base_retrieve

VARIANTS = ['packed-ce', 'clause-dense', 'clause-bm25', 'clause-rrf',
    'clause-ce-naive', 'clause-ce-grouped']
CONFIG = {'rounds': 3, 'candidate_k': 20, 'rrf_constant': 60, 'seed_k': 3,
    'max_chars': 8000, 'max_tokens': 4096, 'cpu_threads': 4, 'query_rewrite': False,
    'child_unit': 'original-parent-fragment; bound table header kept with body',
    'parent_selection': 'maximum child rank; distinct parents before TopK',
    'primary_baseline': 'packed-ce', 'primary_candidate': 'clause-ce-grouped'}


def build_clauses(parents):
    children = {}
    for parent in parents:
        fragments = parent['fragments']
        bound_table = (len(fragments) == 2 and fragments[0]['block_id'] == fragments[1]['block_id']
            and fragments[0]['text_range'][0] == 0 and fragments[0]['text'].endswith('\n')
            and len(fragments[0]['text']) <= 101)
        units = [fragments] if bound_table else [[piece] for piece in fragments]
        for pieces in units:
            signature = json.dumps({'subject': parent['subject'], 'prefix': parent['prefix'],
                'pieces': pieces}, ensure_ascii=False, sort_keys=True)
            identity = parent['source_id'] + ':clause-' + sha(signature.encode())[:20]
            if identity in children:
                if parent['id'] not in children[identity]['parent_ids']:
                    children[identity]['parent_ids'].append(parent['id'])
                continue
            body = '\n'.join(p['text'] for p in pieces)
            text = parent['prefix'] + '\n' + body
            children[identity] = {'id': identity, 'source_id': parent['source_id'],
                'subject': parent['subject'], 'raw_sha256': parent['raw_sha256'],
                'section_path': parent['section_path'], 'prefix': parent['prefix'],
                'body': body, 'text': text, 'content_sha256': sha(text.encode()),
                'fragments': pieces, 'parent_ids': [parent['id']]}
    return list(children.values())


def project_parents(ranked, parents, *, naive=False):
    output, selected = [], set()
    for child, score in (ranked[:3] if naive else ranked):
        for identity in child['parent_ids']:
            parent = parents.get(identity)
            if parent is None or any(parent[key] != child[key]
                    for key in ('subject', 'source_id', 'raw_sha256')):
                raise ValueError('invalid parent source/version binding')
            if identity not in selected:
                output.append((parent, score))
                selected.add(identity)
    return output


def retrieve(query, parents, children, parent_vectors, child_vectors, encoder, scorer, variant):
    if variant not in VARIANTS:
        raise ValueError('unknown clause experiment variant')
    if variant == 'packed-ce':
        ranked, timing = base_retrieve(query, parents, parent_vectors, encoder, scorer, 'hybrid-rrf-ce')
        return ranked, {**timing, 'parent_projection_ms': 0., 'child_hits': None}
    method = {'clause-dense': 'dense', 'clause-bm25': 'bm25', 'clause-rrf': 'hybrid-rrf',
        'clause-ce-naive': 'hybrid-rrf-ce', 'clause-ce-grouped': 'hybrid-rrf-ce'}[variant]
    ranked_children, timing = base_retrieve(query, children, child_vectors, encoder, scorer, method)
    tick = time.perf_counter()
    ranked = project_parents(ranked_children, {p['id']: p for p in parents},
        naive=variant == 'clause-ce-naive')
    projection_ms = (time.perf_counter() - tick) * 1000
    return ranked, {**timing, 'parent_projection_ms': projection_ms,
        'child_hits': [{'id': c['id'], 'score': float(score)} for c, score in ranked_children]}
