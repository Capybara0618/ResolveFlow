from copy import deepcopy

import pytest
from scripts import customer_agent_publication_v2 as runner
from scripts.customer_agent_publication_diagnose_v2 import diagnose


def test_confirmation_preserves_questions_but_uses_new_identity_and_current_hashes(tmp_path):
    cases = runner.load_cases()
    assert [len(c['turns']) for c in cases] == [4, 1]
    old = runner.base.load_cases()
    for case, previous in zip(cases, old, strict=True):
        req, _ = runner.base.prepare_turn(case, 0, [])
        earlier, _ = runner.base.prepare_turn(previous, 0, [])
        assert req.conversation_id != earlier.conversation_id
        assert case['turns'] == previous['turns']
        assert 'criteria' not in str(req.context)
    path = tmp_path / 'manifest.json'
    runner.freeze(path)
    plan, _ = runner.load_plan(path)
    assert plan['production_commit'].startswith('426f08c')
    invalid = deepcopy(plan)
    invalid['files']['agent/src/resolveflow/support/navigation.py'] = '0' * 64
    bad = tmp_path / 'invalid.json'
    runner.prior.write_new(bad, invalid)
    with pytest.raises(ValueError, match='frozen source changed'):
        runner.load_plan(bad)


def test_executor_restores_all_original_bindings_if_the_underlying_run_fails(monkeypatch, tmp_path):
    base = runner.base
    original = base.VERSION, base.PLAN, base.load_cases, base.load_plan

    def fail(*args):
        assert base.VERSION == runner.VERSION and base.PLAN == runner.PLAN
        assert base.load_cases()[0]['id'].startswith(runner.VERSION)
        raise RuntimeError('local interruption')

    monkeypatch.setattr(base, 'evaluate', fail)
    with pytest.raises(RuntimeError):
        runner.evaluate(tmp_path / 'output', tmp_path / 'usage.json')
    assert original == (base.VERSION, base.PLAN, base.load_cases, base.load_plan)


def test_saved_acceptance_paths_pass_without_disabling_the_new_predicate():
    value = diagnose()
    assert value['new_provider_calls'] == 0 and not value['predicate_disabled']
    assert len(value['rows']) == 5
    assert all(r['offline_status'] == 'SUCCEEDED' for r in value['rows'])
    assert sum(r['original_status'] == 'FAILED' for r in value['rows']) == 2
