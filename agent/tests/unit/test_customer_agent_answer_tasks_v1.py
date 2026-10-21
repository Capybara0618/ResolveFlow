import pytest
from scripts import customer_agent_answer_tasks_v1 as check


def test_inputs_keep_original_conditions_under_new_frozen_source_manifest(tmp_path):
    cases = check.load_cases()
    assert len(cases) == 2 and [c['source_case'] for c in cases] == ['D01', 'D02']
    before = check.prior.PLAN.read_bytes()
    path = tmp_path / 'manifest.json'
    check.freeze(path)
    plan = check.load_plan(path)
    assert plan['autonomous_turns'] == 2
    plan['files']['agent/src/resolveflow/support/tasks.py'] = '0' * 64
    changed = tmp_path / 'changed.json'
    check.prior.preparation.write_new(changed, plan)
    with pytest.raises(ValueError, match='frozen source changed'):
        check.load_plan(changed)
    assert check.prior.PLAN.read_bytes() == before


def test_scoped_driver_and_prior_loader_are_restored_after_error(monkeypatch, tmp_path):
    original, loader, cases_loader = check.driver.PLAN, check.driver.load_plan, check.prior.load_cases

    def reject(output, usage):
        assert check.driver.PLAN == check.PLAN and check.driver.load_plan is check.load_plan
        raise ValueError('before model')

    monkeypatch.setattr(check.driver, 'evaluate', reject)
    with pytest.raises(ValueError, match='before model'):
        check.execute(tmp_path / 'none.json', tmp_path / 'usage.json')
    assert check.driver.PLAN == original and check.driver.load_plan is loader
    assert check.prior.load_cases is cases_loader and not list(tmp_path.iterdir())
