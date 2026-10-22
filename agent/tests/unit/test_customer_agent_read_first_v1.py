import pytest
from scripts import customer_agent_read_first_v1 as check


def test_only_fresh_identities_change_and_new_sources_are_frozen(tmp_path):
    before = check.prior.PLAN.read_bytes()
    assert len(check.load_cases()) == 2
    path = tmp_path / 'manifest.json'
    check.freeze(path)
    plan = check.load_plan(path)
    assert plan['autonomous_turns'] == 2
    plan['files']['agent/src/resolveflow/support/protocol.py'] = '0' * 64
    changed = tmp_path / 'changed.json'
    check.io.write_new(changed, plan)
    with pytest.raises(ValueError, match='frozen source changed'):
        check.load_plan(changed)
    assert check.prior.PLAN.read_bytes() == before


def test_scoped_driver_is_restored_after_failure_without_creating_output(monkeypatch, tmp_path):
    pointer, loader = check.driver.PLAN, check.driver.load_plan

    def reject(output, usage):
        assert check.driver.PLAN == check.PLAN and check.driver.load_plan is check.load_plan
        raise ValueError('before model')

    monkeypatch.setattr(check.driver, 'evaluate', reject)
    with pytest.raises(ValueError, match='before model'):
        check.execute(tmp_path / 'none.json', tmp_path / 'usage.json')
    assert check.driver.PLAN == pointer and check.driver.load_plan is loader
    assert not list(tmp_path.iterdir())
