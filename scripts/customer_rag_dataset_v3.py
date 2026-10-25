"""Source-bound expanded policy corpus. No generation API, ranking or production writes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.policy_documents import (
    Node,
    Tree,
    parse_document,
    validate_source,
    visible,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'evals/customer-rag-quantification-v3'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def all_nodes(node):
    yield node
    for child in node.children:
        if isinstance(child, Node):
            yield from all_nodes(child)


def extract_document(raw, source):
    validate_source(source)
    if sha(raw) != source['expected_sha256']:
        raise ValueError('snapshot hash differs')
    html = raw.decode(source['encoding'], errors='strict')
    if '\ufffd' in html:
        raise ValueError('replacement character in source')
    selector = source['selector']
    # Locate the explicit content root without relying on unrelated malformed ancestors.
    roots = [n for n in all_nodes(Tree(html).root) if n.tag == selector['tag'] and visible(n)
        and all(value in (n.attrs.get('class') or '').split() if key == 'class'
            else n.attrs.get(key) == value for key, value in selector.items() if key != 'tag')]
    if len(roots) != 1:
        raise ValueError('body selector must match exactly one root')
    root = roots[0]
    fragment = html[root.start:root.end]
    fragment_bytes = fragment.encode('utf-8')
    document = parse_document(fragment_bytes, {**source, 'encoding': 'utf-8',
        'expected_sha256': sha(fragment_bytes)})
    document.update(raw_sha256=sha(raw), source_title=source['title'], encoding=source['encoding'],
        role='EXTERNAL_REFERENCE', adopted_by_project_merchant=False,
        extraction={'method': 'explicit-root-fragment-policy-html-v1',
            'fragment_sha256': sha(fragment_bytes), 'root_start_char': root.start,
            'root_end_char': root.end, 'root_path': root.path})
    for block in document['blocks']:
        location = block['locator']
        location['start_char'] += root.start
        location['end_char'] += root.start
        location['line'] += root.line - 1
        location['path'] = root.path + '::fragment' + location['path']
        if sha(html[location['start_char']:location['end_char']].encode()) != block['raw_fragment_sha256']:
            raise ValueError('block position does not resolve to original HTML')
    return document


def validate_corpus(corpus):
    documents = corpus['documents']
    if not documents or len({d['source_id'] for d in documents}) != len(documents):
        raise ValueError('empty/duplicate corpus')
    block_ids = set()
    for document in documents:
        if document['adopted_by_project_merchant'] is not False or not document['subject'].startswith('EXTERNAL:'):
            raise ValueError('external reference boundary changed')
        if not document['blocks']:
            raise ValueError('empty extracted body')
        for block in document['blocks']:
            if block['id'] in block_ids:
                raise ValueError('duplicate block')
            block_ids.add(block['id'])
            if sha(block['text'].encode()) != block['text_sha256']:
                raise ValueError('text hash differs')
            if block['locator']['start_char'] >= block['locator']['end_char']:
                raise ValueError('invalid raw HTML position')
    return {'documents': len(documents), 'blocks': len(block_ids),
        'characters': sum(len(b['text']) for d in documents for b in d['blocks']),
        'subjects': len({d['subject'] for d in documents})}


def build():
    sources = read(DATA / 'sources.json')
    documents = []
    for source in sources:
        document = extract_document((ROOT / source['snapshot_path']).read_bytes(), source)
        document['capture'] = read(ROOT / source['capture_path'])
        documents.append(document)
    return {'version': 'customer-rag-quantification-v3', 'generation_api_calls': 0,
        'status': 'SOURCE_EXTRACTED_NOT_RANKED', 'sources_sha256': sha((DATA / 'sources.json').read_bytes()),
        'documents': documents}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['build', 'check'])
    args = parser.parse_args()
    corpus = build()
    summary = validate_corpus(corpus)
    if args.mode == 'build':
        write_new(DATA / 'corpus.json', corpus)
    elif read(DATA / 'corpus.json') != corpus:
        raise ValueError('saved corpus no longer matches frozen raw snapshots')
    print(json.dumps({**summary, 'new_generation_api_calls': 0}))
