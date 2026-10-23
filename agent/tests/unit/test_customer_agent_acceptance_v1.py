from copy import deepcopy

import pytest
from scripts import customer_agent_acceptance_v1 as runner
from scripts.customer_agent_repair_probe_v1 import InjectedPrefix, prefix_for

from resolveflow.harness.model import ModelReply


def test_acceptance_separates_four_natural_turns_and_injected_probe_without_criteria_leak(tmp_path):
    cases = runner.load_cases()
    assert [len(c['turns']) for c in cases] == [4, 1]
    requests = [runner.prepare_turn(c, 0, [])[0] for c in cases]
    assert requests[0].conversation_id != requests[1].conversation_id
    for req in requests:
        assert 'criteria' not in str(req.context) and 'injected-prefix' not in str(req.context)
    path = tmp_path / 'manifest.json'
    runner.freeze(path)
    plan, _ = runner.load_plan(path)
    assert plan['natural_turns'] == 4 and plan['probe_turns'] == 1
    bad = deepcopy(plan)
    bad['files']['agent/src/resolveflow/support/navigation.py'] = '0' * 64
    invalid = tmp_path / 'invalid.json'
    runner.prior.write_new(invalid, bad)
    with pytest.raises(ValueError, match='frozen source changed'):
        runner.load_plan(invalid)


def test_prefix_never_calls_provider_and_then_delegates_original_reply():
    class Provider:
        def __init__(self):
            self.calls = 0

        def prepare_request(self, **kwargs):
            return kwargs

        def decide(self, **kwargs):
            self.calls += 1
            return ModelReply({'kind': 'READ_TOOL', 'tool_name': 'get_support_guide', 'arguments': {}}, mode='live')

    req, _ = runner.prepare_turn(runner.load_cases()[1], 0, [])
    provider, saved = Provider(), []
    model = InjectedPrefix(provider, prefix_for(req), lambda records: saved.append(deepcopy(records)))
    kwargs = {'system': '', 'messages': [], 'max_output_tokens': 1024}
    assert model.decide(**kwargs).mode == 'mock'
    assert model.decide(**kwargs).mode == 'mock'
    assert provider.calls == 0 and len(saved[-1]) == 2
    assert saved[-1][-1]['origin'] == 'SCRIPTED_FAULT_INJECTION'
    assert model.decide(**kwargs).mode == 'live' and provider.calls == 1
    assert len(saved[-1]) == 2


def test_natural_executor_failure_restores_bindings_and_does_not_start_probe(monkeypatch, tmp_path):
    from resolveflow.support import service

    before = runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn, service.SupportRuntime

    def fail(*args):
        assert runner.prior.PLAN == runner.PLAN
        raise RuntimeError('local test interruption')

    monkeypatch.setattr(runner.prior, 'evaluate', fail)
    with pytest.raises(RuntimeError):
        runner.evaluate(tmp_path / 'outputs', tmp_path / 'usage.json')
    assert before == (runner.prior.PLAN, runner.prior.load_plan, runner.prior.prepare_turn, service.SupportRuntime)
    assert not (tmp_path / 'outputs/repair-results.json').exists()
