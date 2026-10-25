"""Validate author-constructed cases against frozen original policy spans; never rank cases."""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from scripts.customer_rag_dataset_v3 import DATA, read, sha, validate_corpus

CATEGORIES = {'ordinary', 'colloquial', 'exact', 'compound', 'unanswerable'}


def validate_questions(data, corpus):
    validate_corpus(corpus)
    documents = {d['source_id']: d for d in corpus['documents']}
    blocks = {b['id']: (d, b) for d in corpus['documents'] for b in d['blocks']}
    queries = data['queries']
    if data['independent_holdout'] is not False or data['acceptance_rankings_seen'] is not False:
        raise ValueError('authorship/unseen-ranking boundary differs')
    if len(queries) != 100 or len({q['id'] for q in queries}) != 100 or len({q['query'] for q in queries}) != 100:
        raise ValueError('empty/duplicate question matrix')
    category_counts = Counter(q['category'] for q in queries)
    if category_counts != Counter(dict.fromkeys(CATEGORIES, 20)):
        raise ValueError('category matrix differs')
    split_counts = Counter((q['split'], q['category']) for q in queries)
    if split_counts != Counter({(s, c): n for s, n in [('development', 8), ('acceptance', 12)]
            for c in CATEGORIES}):
        raise ValueError('split matrix differs')
    families, sources_by_split = defaultdict(set), defaultdict(set)
    positive_sources = set()
    atoms = 0
    for query in queries:
        expected_scope = {(d['source_id'], d['raw_sha256']) for d in documents.values()
            if d['subject'] == query['subject']}
        actual_scope = [(s['source_id'], s['raw_sha256']) for s in query['scope']]
        if not expected_scope or set(actual_scope) != expected_scope or len(actual_scope) != len(expected_scope):
            raise ValueError('scope must include all snapshots in the same external brand family')
        if not query['query'].strip() or any(bid in query['query'] for bid in blocks):
            raise ValueError('empty query or evidence ID leaked into query')
        if not query['answer_points'] or any(not p.strip() for p in query['answer_points']):
            raise ValueError('missing answer rubric')
        if query['review'] != {'origin': 'CODEX_SOURCE_REVIEW', 'source_checked': True, 'independent_human': False}:
            raise ValueError('source-review attribution differs')
        if not query['fact_group']:
            raise ValueError('missing fact group')
        families[query['fact_group']].add(query['split'])
        evidence = query['required_evidence']
        if query['category'] == 'unanswerable':
            if query['answerability'] != 'NOT_IN_CORPUS' or evidence or not query['missing_reason']:
                raise ValueError('missing-evidence question needs reason, not fabricated Gold')
        elif query['answerability'] != 'ANSWERABLE' or not evidence or query['missing_reason'] is not None:
            raise ValueError('answerability/Gold differs')
        identities = set()
        for atom in evidence:
            document, block = blocks[atom['block_id']]
            if (atom['source_id'], atom['raw_sha256']) not in expected_scope or atom['source_id'] != document['source_id']:
                raise ValueError('out-of-scope evidence')
            left, right = atom['text_range']
            if not 0 <= left < right <= len(block['text']) or block['text'][left:right] != atom['quote']:
                raise ValueError('evidence quote does not resolve to original source')
            if sha(atom['quote'].encode()) != atom['quote_sha256']:
                raise ValueError('quote hash differs')
            identity = (atom['block_id'], left, right)
            if identity in identities:
                raise ValueError('duplicate evidence atom')
            identities.add(identity)
            sources_by_split[query['split']].add(atom['source_id'])
            positive_sources.add(atom['source_id'])
            atoms += 1
    if any(len(splits) > 1 for splits in families.values()):
        raise ValueError('fact group crossed development/acceptance')
    if sources_by_split['development'] & sources_by_split['acceptance']:
        raise ValueError('evidence source crossed development/acceptance')
    if positive_sources != set(documents):
        raise ValueError('source without any answerable question')
    return {'questions': len(queries), 'development': 40, 'acceptance': 60,
        'answerable_development': 32, 'answerable_acceptance': 48, 'unanswerable': 20,
        'positive_sources': len(positive_sources), 'evidence_atoms': atoms,
        'split_source_overlap': [], 'new_rankings': 0, 'new_generation_api_calls': 0}


if __name__ == '__main__':
    print(json.dumps(validate_questions(read(DATA / 'queries.json'), read(DATA / 'corpus.json'))))
