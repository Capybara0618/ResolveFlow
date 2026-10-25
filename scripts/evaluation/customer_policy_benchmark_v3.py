"""Shared source-span chunking, scoped retrieval and bounded evidence for the v3 experiment."""

from __future__ import annotations

import json
import time
from collections import defaultdict

from resolveflow.policies.index import PolicyHit
from resolveflow.policies.retrieval import bm25_scores, cosine_similarity

from scripts.customer_rag_dataset_v3 import sha

VARIANTS = ['dense', 'bm25', 'hybrid-rrf', 'hybrid-rrf-ce']
CONFIG = {'candidate_k': 20, 'rrf_constant': 60, 'chunk_chars': 320, 'overlap_chars': 48,
    'prefix_chars': 64, 'seed_k': 3, 'diagnostic_k': [1, 5], 'max_chars': 8000,
    'max_tokens': 4096, 'routes': ['body_dense', 'body_bm25_positive'],
    'query_rewrite': False, 'parent_expansion': False, 'rounds': 3, 'cpu_threads': 4}


def windows(text, limit, overlap):
    left = 0
    while left < len(text):
        right = min(len(text), left + limit)
        if right < len(text):
            boundary = max(text.rfind(mark, left + limit // 2, right) for mark in '。；\n')
            if boundary >= 0:
                right = boundary + 1
        yield left, right
        if right == len(text):
            break
        left = max(left + 1, right - overlap)


def _append_document(document, chunks):
    buffer, buffer_section = [], None

    def piece(block, left, right):
        return {'source_id': document['source_id'], 'raw_sha256': document['raw_sha256'],
            'block_id': block['id'], 'text_range': [left, right], 'text': block['text'][left:right]}

    def emit(pieces, section):
        body = '\n'.join(p['text'] for p in pieces)
        prefix = (document['source_title'][:31] + ' | ' + ' > '.join(section)[-30:])[:64]
        text = prefix + '\n' + body
        chunks.append({'id': document['source_id'] + f':c{len(chunks) + 1:04d}',
            'source_id': document['source_id'], 'subject': document['subject'],
            'raw_sha256': document['raw_sha256'], 'section_path': section,
            'prefix': prefix, 'body': body, 'text': text, 'content_sha256': sha(text.encode()),
            'fragments': pieces})

    def flush():
        if buffer:
            emit(list(buffer), buffer_section)
            buffer.clear()

    for block in document['blocks']:
        if block['kind'] == 'heading':
            continue
        section = block['section_path']
        text = block['text']
        if block['kind'] == 'table' and len(text) > CONFIG['chunk_chars']:
            flush()
            # Repeat the first serialized header line using its actual source span.
            # This is a layout fallback, not an inferred merged-cell interpretation.
            end = text.find('\n')
            header_end = end + 1 if 0 < end <= 100 else 0
            start = header_end
            limit = CONFIG['chunk_chars'] - header_end - bool(header_end)
            for left, right in windows(text[start:], limit, CONFIG['overlap_chars']):
                pieces = [piece(block, 0, header_end)] if header_end else []
                pieces.append(piece(block, start + left, start + right))
                emit(pieces, section)
            continue
        for left, right in windows(text, CONFIG['chunk_chars'], CONFIG['overlap_chars']):
            fragment = piece(block, left, right)
            size = sum(len(p['text']) for p in buffer) + len(buffer) + len(fragment['text'])
            if buffer and (section != buffer_section or size > CONFIG['chunk_chars']):
                flush()
            buffer_section = section
            buffer.append(fragment)
    flush()


def build_chunks(corpus):
    chunks = []
    for document in corpus['documents']:
        _append_document(document, chunks)
    if len({c['id'] for c in chunks}) != len(chunks):
        raise ValueError('duplicate chunk identity')
    return chunks


def public_query(query):
    return {k: query[k] for k in ('query', 'subject', 'scope')}


def retrieve(query, chunks, vectors, encoder, scorer, variant):
    if variant not in VARIANTS:
        raise ValueError('unknown retrieval variant')
    scope = {(s['source_id'], s['raw_sha256']) for s in query['scope']}
    expected = {(c['source_id'], c['raw_sha256']) for c in chunks if c['subject'] == query['subject']}
    if scope != expected:
        raise ValueError('scope must cover all documents of the same brand')
    scoped = [c for c in chunks if c['subject'] == query['subject']
        and (c['source_id'], c['raw_sha256']) in scope]
    started = time.perf_counter()
    vector = encoder.embed([query['query']])[0] if variant != 'bm25' else None
    encoded = time.perf_counter()
    dense = sorted([(c, cosine_similarity(vectors[c['id']], vector)) for c in scoped],
        key=lambda pair: (-pair[1], pair[0]['id']))[:20] if vector is not None else []
    lexical = sorted(zip(scoped, bm25_scores([c['text'] for c in scoped], query['query']), strict=True),
        key=lambda pair: (-pair[1], pair[0]['id']))[:20] if variant != 'dense' else []
    if variant == 'dense':
        ranked = dense
    elif variant == 'bm25':
        ranked = lexical
    else:
        scores, originals = defaultdict(float), {}
        for route in (dense, [(c, s) for c, s in lexical if s > 0]):
            for position, (chunk, _) in enumerate(route, 1):
                scores[chunk['id']] += 1 / (CONFIG['rrf_constant'] + position)
                originals[chunk['id']] = chunk
        ranked = sorted([(originals[key], value) for key, value in scores.items()],
            key=lambda pair: (-pair[1], pair[0]['id']))[:20]
    candidate_at = time.perf_counter()
    profile = None
    if variant == 'hybrid-rrf-ce':
        if scorer is None:
            raise ValueError('CrossEncoder is required, no silent fallback')
        manifest = sha(json.dumps(query['scope'], sort_keys=True).encode())
        hits = [PolicyHit(c['source_id'], query['subject'], c['raw_sha256'], manifest,
            c['id'], c['id'], c['content_sha256'], c['prefix'], c['text'], float(s), 'dense')
            for c, s in ranked]
        reranked, profile = scorer.rank(query['query'], hits)
        mapping = {c['id']: c for c, _ in ranked}
        if {h.chunk_id for h in reranked} != set(mapping) or len(reranked) != len(mapping):
            raise ValueError('reranker candidate identity differs')
        ranked = [(mapping[h.chunk_id], h.score) for h in reranked]
    return ranked, {'encode_ms': (encoded - started) * 1000,
        'candidate_fusion_ms': (candidate_at - encoded) * 1000, 'rerank': profile,
        'scoped_candidates': len(scoped), 'scoped_documents': len(scope)}


def uncovered(left, right, existing):
    remaining = [(left, right)]
    for a, b in existing:
        remaining = [(x, y) for lo, hi in remaining
            for x, y in [(lo, min(hi, a)), (max(lo, b), hi)] if x < y]
    return remaining


def assemble(ranked, tokenizer, *, k=3, max_chars=8000, max_tokens=4096):
    pieces, selected, skipped, sections = [], [], [], []
    intervals = defaultdict(list)
    for chunk, _ in ranked[:k]:
        additions = []
        for fragment in chunk['fragments']:
            key = (fragment['source_id'], fragment['raw_sha256'], fragment['block_id'])
            left, right = fragment['text_range']
            for a, b in uncovered(left, right, intervals[key]):
                additions.append({**fragment, 'text_range': [a, b],
                    'text': fragment['text'][a - left:b - left]})
        if not additions:
            continue
        section = '[' + chunk['id'] + '] ' + chunk['prefix'] + '\n' + '\n'.join(p['text'] for p in additions)
        candidate = '\n\n'.join([*sections, section])
        if len(candidate) > max_chars or len(tokenizer.encode(candidate).ids) > max_tokens:
            skipped.append(chunk['id'])
            continue
        sections.append(section)
        selected.append(chunk['id'])
        pieces.extend(additions)
        for piece in additions:
            intervals[(piece['source_id'], piece['raw_sha256'], piece['block_id'])].append(piece['text_range'])
    body = '\n\n'.join(sections)
    return {'body': body, 'body_sha256': sha(body.encode()), 'body_chars': len(body),
        'body_tokens': len(tokenizer.encode(body).ids), 'selected_chunks': selected,
        'skipped_chunks': skipped, 'pieces': pieces}


def covers(pieces, atom):
    left, right = atom['text_range']
    intervals = sorted(p['text_range'] for p in pieces if all(p[k] == atom[k]
        for k in ('source_id', 'raw_sha256', 'block_id')))
    position = left
    for lo, hi in intervals:
        if lo > position:
            break
        position = max(position, hi)
    return position >= right


def quality(query, packet):
    if query['answerability'] != 'ANSWERABLE':
        return {'any_required': None, 'complete': None}
    flags = [covers(packet['pieces'], atom) for atom in query['required_evidence']]
    return {'any_required': any(flags), 'complete': all(flags)}
