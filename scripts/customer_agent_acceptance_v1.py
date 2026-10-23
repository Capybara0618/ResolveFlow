"""Four natural turns and one separately labelled injected-prefix/live-repair probe, once only."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'agent/src')]

from scripts import customer_agent_navigation_v1 as navigation

prior = navigation.prior
VERSION = 'customer-agent-acceptance-v1'
DIRECTORY = ROOT / 'evals' / VERSION
PLAN = DIRECTORY / 'manifest.json'


def load_cases():
    data = prior.read_json(DIRECTORY / 'scenarios.json')
    if data['version'] != VERSION or [c['id'] for c in data['cases']] != ['A01', 'R01']:
        raise ValueError('unexpected acceptance cohort')
    originals = navigation.load_cases()
    cases = []
    for selected, source in zip(data['cases'], [originals[0], originals[2]], strict=True):
        case = deepcopy(source)
        case.update(deepcopy(selected), id=VERSION + ':' + selected['id'],
                    partition='development-visible-acceptance', architecture='staged-v1')
        cases.append(case)
    if [len(c['turns']) for c in cases] != [4, 1] or cases[1]['mode'] != 'injected-prefix-live-repair':
        raise ValueError('expected four natural turns and one labelled repair probe')
    return cases


def prepare_turn(case, turn_index, completed):
    return navigation.prepare_turn(case, turn_index, completed)


def freeze(path=PLAN):
    cases = load_cases()
    old = prior.read_json(navigation.PLAN)
    files = set(old['files']) | {
        'scripts/customer_agent_navigation_v1.py', 'scripts/customer_agent_acceptance_v1.py',
        'scripts/customer_agent_repair_probe_v1.py', 'evals/customer-agent-acceptance-v1/scenarios.json',
        'docs/customer-agent-acceptance-v1.md', 'docs/customer-agent-navigation-fix-v1.md',
        'agent/tests/unit/test_customer_agent_acceptance_v1.py',
        'agent/tests/integration/test_customer_agent_acceptance_v1.py',
        'agent/tests/unit/test_support_navigation_recorded.py',
        'scripts/customer_agent_navigation_diagnose_v1.py',
        'reports/customer-agent-navigation-v1/runtime-results.json',
    }
    prior.write_new(path, {'version': VERSION, 'natural_turns': 4, 'probe_turns': 1,
        'not_resume_metrics': True, 'not_holdout': True, 'synthetic_facts': True, 'architecture': 'staged-v1',
        'production_commit': '8c899f5ee4680272c5407601a5366d45a8959242',
        'order': [{'id': c['id'], 'turns': len(c['turns']), 'mode': c['mode']} for c in cases],
        'files': {p: prior.digest(ROOT / p) for p in sorted(files)}, 'embedding_files': old['embedding_files']})


def load_plan(path=None):
    plan = prior.read_json(path or PLAN)
    if plan['version'] != VERSION:
        raise ValueError('wrong acceptance version')
    for name, fingerprint in plan['files'].items():
        if prior.digest(ROOT / name) != fingerprint:
            raise ValueError('frozen source changed: ' + name)
    for name, fingerprint in plan['embedding_files'].items():
        if prior.digest(Path(prior.MODEL_PATH) / name) != fingerprint:
            raise ValueError('embedding changed: ' + name)
    return plan, load_cases()


def evaluate(output, usage_path):
    from resolveflow.support import service

    from scripts.customer_agent_repair_probe_v1 import evaluate_probe

    if output.exists():
        raise FileExistsError('acceptance output exists; inspect it instead of rerunning')
    output.mkdir(parents=True)
    original = service.SupportRuntime

    class StagedRuntime(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, architecture='staged-v1')

    def natural_plan():
        plan, cases = load_plan()
        return plan, cases[:1]

    with patch.object(prior, 'PLAN', PLAN), patch.object(prior, 'load_plan', natural_plan), \
            patch.object(prior, 'prepare_turn', prepare_turn), patch.object(service, 'SupportRuntime', StagedRuntime):
        prior.evaluate(output / 'natural-results.json', usage_path)
    evaluate_probe(output / 'repair-results.json', usage_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze', action='store_true')
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--database', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--live-usage', type=Path, default=ROOT / 'tmp/evaluation-live-budget.json')
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.check:
        plan, cases = load_plan()
        result = {'version': plan['version'], 'natural_turns': 4, 'probe_turns': 1, 'new_models': 0}
        if args.database:
            result['database'] = prior.baseline.previous.check_database(cases, prior.DSN)
        if args.output:
            prior.write_new(args.output, result)
        print({k: v for k, v in result.items() if k != 'database'})
    elif args.output is None:
        parser.error('--output required')
    else:
        evaluate(args.output, args.live_usage)


if __name__ == '__main__':
    main()
