"""Small complete policy contexts preserve the same pinned scope as ranked retrieval."""

from dataclasses import replace

import pytest

from resolveflow.policies.index import PolicyIndex, PolicyIndexNotReadyError
from resolveflow.support.sources import BoundSources
from tests.integration.test_policy_index import LOGISTICS_SEPTEMBER
from tests.unit.test_support_sources import request


def bundle_with_rules(count=6, text='原始条件与例外。'):
    return replace(LOGISTICS_SEPTEMBER, rules=[
        {'rule_id': f'r{i}', 'title': f'条件{i}', 'text': text} for i in range(count)])


def test_small_context_includes_every_rule_without_embedding_or_topk_truncation(agent_db):
    index = PolicyIndex(agent_db)
    bundle = bundle_with_rules()
    generation = index.build(bundle)
    req = request()
    req.merchant_id = bundle.merchant_id
    req.context['policy_manifest'] = {'merchant_id': bundle.merchant_id,
        'bundle_ids': [bundle.bundle_id], 'manifest_hash': bundle.manifest_hash}
    source = BoundSources(req, case_url='http://unused', token='unused', index=index)
    try:
        hits = source.search('条件', 1)
        assert {h['data']['rule_id'] for h in hits} == {f'r{i}' for i in range(6)}
        assert all(h['retrieval_context'] == {'mode': 'COMPLETE_SMALL_SET', 'count': 6} for h in hits)
        assert all(h['data']['text'] == '原始条件与例外。' for h in hits)
        assert source.generations == {bundle.bundle_id: generation.generation_id}
    finally:
        source.close()


def test_complete_context_keeps_pinned_generation_and_checks_merchant_hash_and_ready(agent_db):
    index = PolicyIndex(agent_db)
    bundle = bundle_with_rules()
    generation = index.build(bundle)
    scope = dict(merchant_id=bundle.merchant_id, bundle_ids=[bundle.bundle_id],
        manifest_hash=bundle.manifest_hash, generation_ids={bundle.bundle_id: generation.generation_id})
    original = index.small_context(**scope)
    index.build(replace(bundle, rules=[{'rule_id': 'new', 'title': '新规则', 'text': '不同的新政策。'}]))
    assert index.small_context(**scope) == original
    for changed in [{'merchant_id': 'other'}, {'manifest_hash': 'wrong'},
                    {'generation_ids': {bundle.bundle_id: 'missing'}}, {'generation_ids': {}}]:
        with pytest.raises(PolicyIndexNotReadyError):
            index.small_context(**{**scope, **changed})


@pytest.mark.parametrize(('count', 'text'), [(9, '短规则'), (2, '完整条件。' * 700)], ids=['many', 'long'])
def test_large_context_is_declined_without_truncating_any_rule(agent_db, count, text):
    index = PolicyIndex(agent_db)
    bundle = bundle_with_rules(count, text)
    generation = index.build(bundle)
    assert index.small_context(merchant_id=bundle.merchant_id, bundle_ids=[bundle.bundle_id],
        manifest_hash=bundle.manifest_hash, generation_ids={bundle.bundle_id: generation.generation_id}) is None
