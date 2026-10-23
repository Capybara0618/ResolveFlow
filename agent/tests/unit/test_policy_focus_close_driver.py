"""Frozen follow-ups change only the current question, never the retained business history."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))

import close_policy_focus_live_v1 as driver  # noqa: E402 - same script import path as the CLI
import confirm_policy_focus_scope_v2 as scope_driver  # noqa: E402


def test_variants_preserve_old_history_pins_and_replace_only_current_question():
    original = driver.driver.build_fixture()
    for case in driver.driver.read(driver.PLAN)['cases']:
        fixture = driver.fixture_for(case['question'])
        request = fixture['original_input']
        assert request['context']['current_request'] == case['question']
        assert fixture['generation_ids'] == original['generation_ids']
        assert fixture['shipment'] == original['shipment'] and fixture['order'] == original['order']
        old = [m for m in original['original_input']['context']['history'] if m['sequence'] < request['input_version']]
        assert [m for m in request['context']['history'] if m['sequence'] < request['input_version']] == old
    assert driver.driver.read(driver.PLAN)['total_model_attempt_limit'] == 12


@pytest.mark.parametrize('limit', [8, 12])
def test_whole_cohort_has_a_hard_bound_restores_driver_and_cannot_be_reexecuted(tmp_path, monkeypatch, limit):
    out = tmp_path / 'live'
    monkeypatch.setattr(driver, 'OUT', out)
    calls = []

    class SyntheticModel:
        def decide(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(driver.driver, 'RecordedStreamingModel', SyntheticModel)
    original_output = driver.driver.OUT
    cases = {}
    for name in ['a', 'b', 'c']:
        driver.driver.persist(out / name / 'manifest.json', {})
        cases[name] = driver.driver.digest(out / name / 'manifest.json')
    driver.driver.persist(out / 'manifest.json', {'cases': cases, 'total_model_attempt_limit': limit})

    def synthetic_execute():
        status = 'FAILED'
        try:
            for _ in range(5):
                driver.driver.RecordedStreamingModel().decide()
            status = 'SUCCEEDED'
        finally:
            driver.driver.persist(driver.driver.OUT / 'runtime-results.json',
                                  {'result': {'status': status}, 'transport_requests': len(calls)})

    monkeypatch.setattr(driver.driver, 'execute', synthetic_execute)
    with pytest.raises(ValueError, match='whole-cohort'):
        driver.execute()
    assert len(calls) == limit and driver.driver.OUT == original_output
    assert driver.driver.RecordedStreamingModel is SyntheticModel
    assert driver.driver.read(out / 'results.json')['state'] == 'FAILED'
    with pytest.raises(AssertionError, match='immutable'):
        driver.execute()


def test_single_scope_revision_freezes_its_explicit_request_limit_and_restores_driver(tmp_path, monkeypatch):
    original = scope_driver.driver.OUT
    monkeypatch.setattr(scope_driver, 'OUT', tmp_path / 'revision')

    def synthetic_prepare():
        scope_driver.driver.persist(scope_driver.driver.OUT / 'manifest.json', {'files': {}})

    monkeypatch.setattr(scope_driver.driver, 'prepare', synthetic_prepare)
    scope_driver.prepare(6)
    manifest = scope_driver.driver.read(scope_driver.OUT / 'manifest.json')
    assert manifest['model_attempt_limit'] == 6 and scope_driver.driver.OUT == original
    assert 'scripts/confirm_policy_focus_scope_v2.py' in manifest['files']
    with pytest.raises(AssertionError):
        scope_driver.prepare(0)
