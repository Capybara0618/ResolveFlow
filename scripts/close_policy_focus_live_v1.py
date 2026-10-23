"""Three frozen policy follow-ups, at most twelve actual requests total, no failed-turn rerun."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

import confirm_policy_focus_live_v1 as driver

ROOT = driver.ROOT
OUT = ROOT / 'reports/customer-policy-focus-close-v1/live'
PLAN = ROOT / 'evals/customer-policy-focus-close-v1/plan.json'


def fixture_for(question, original=None):
    fixture = deepcopy(driver.build_fixture() if original is None else original)
    request = fixture['original_input']
    request['context']['current_request'] = question
    for message in request['context']['history']:
        if message['sequence'] == request['input_version']:
            message['text'] = question
    return fixture


def prepare():
    assert not (OUT / 'manifest.json').exists(), 'frozen cohort already exists'
    plan = driver.read(PLAN)
    original_output, original_fixture = driver.OUT, driver.build_fixture
    original = original_fixture()
    try:
        for case in plan['cases']:
            fixture = fixture_for(case['question'], original)
            driver.OUT = OUT / case['id']
            driver.build_fixture = lambda fixture=fixture: deepcopy(fixture)
            driver.prepare()
            path = driver.OUT / 'manifest.json'
            manifest = driver.read(path)
            for source in [PLAN, Path(__file__).resolve()]:
                manifest['files'][source.relative_to(ROOT).as_posix()] = driver.digest(source)
            driver.persist(path, manifest)
    finally:
        driver.OUT, driver.build_fixture = original_output, original_fixture
    driver.persist(OUT / 'manifest.json', {'scope': plan['scope'], 'total_model_attempt_limit': 12,
        'cases': {c['id']: driver.digest(OUT / c['id'] / 'manifest.json') for c in plan['cases']}})


def execute():
    assert not (OUT / 'results.json').exists(), 'attempted cohort is immutable'
    manifest = driver.read(OUT / 'manifest.json')
    for name, fingerprint in manifest['cases'].items():
        assert driver.digest(OUT / name / 'manifest.json') == fingerprint
    original_output, original_model = driver.OUT, driver.RecordedStreamingModel
    summary = {'state': 'RUNNING', 'models': 0, 'runs': [], 'total_model_attempt_limit': 12}
    driver.persist(OUT / 'results.json', summary)

    class CohortModel(original_model):
        def decide(self, **kwargs):
            if summary['models'] >= manifest['total_model_attempt_limit']:
                raise ValueError('frozen whole-cohort request bound reached')
            summary['models'] += 1
            driver.persist(OUT / 'results.json', summary)
            return super().decide(**kwargs)

    try:
        driver.RecordedStreamingModel = CohortModel
        for name in manifest['cases']:
            driver.OUT = OUT / name
            try:
                driver.execute()
            finally:
                path = driver.OUT / 'runtime-results.json'
                result = driver.read(path) if path.exists() else {}
                summary['runs'].append({'case': name, 'status': result.get('result', {}).get('status'),
                    'models': result.get('transport_requests'),
                    'runtime_sha256': driver.digest(path) if path.exists() else None})
                driver.persist(OUT / 'results.json', summary)
            if result.get('result', {}).get('status') != 'SUCCEEDED':
                summary['state'] = 'STOPPED_FAILED_TURN'
                break
        else:
            summary['state'] = 'FINISHED'
    except Exception:
        summary['state'] = 'FAILED'
        raise
    finally:
        driver.OUT, driver.RecordedStreamingModel = original_output, original_model
        driver.persist(OUT / 'results.json', summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'execute'])
    args = parser.parse_args()
    prepare() if args.command == 'prepare' else execute()
