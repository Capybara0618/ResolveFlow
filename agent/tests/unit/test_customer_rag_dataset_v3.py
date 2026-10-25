import copy

import pytest
from scripts.customer_rag_dataset_v3 import extract_document, validate_corpus


def source(raw):
    import hashlib

    return {'id': 'example', 'subject': 'EXTERNAL:EXAMPLE', 'title': '政策',
        'url': 'https://example.com/policy', 'encoding': 'utf-8',
        'selector': {'tag': 'div', 'id': 'policy'},
        'expected_sha256': hashlib.sha256(raw).hexdigest(),
        'role': 'EXTERNAL_REFERENCE', 'adopted_by_project_merchant': False}


def test_extraction_rebinds_unicode_positions_to_original_snapshot():
    raw = '<html>导航<div id="policy"><h2>运费</h2><p>质量问题免运费。</p></div>页脚</html>'.encode()
    document = extract_document(raw, source(raw))
    assert len(document['blocks']) == 2
    assert document['blocks'][1]['text'] == '质量问题免运费。'
    validate_corpus({'documents': [document]})
    assert document['blocks'][0]['locator']['start_char'] > 2
    bad = copy.deepcopy(document)
    bad['blocks'][1]['text'] = '全部免运费。'
    with pytest.raises(ValueError, match='text hash'):
        validate_corpus({'documents': [bad]})


def test_shell_and_duplicate_roots_are_not_policy():
    for text in ['<div id="policy"></div>', '<div id="policy">a</div><div id="policy">b</div>']:
        raw = text.encode()
        with pytest.raises(ValueError):
            extract_document(raw, source(raw))


def test_raw_drift_rejected_before_extraction():
    raw = b'<div id="policy"><p>policy</p></div>'
    with pytest.raises(ValueError, match='snapshot hash'):
        extract_document(raw + b'changed', source(raw))
