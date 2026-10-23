"""One frozen post-fix confirmation; reuse the audited natural/probe executors unchanged."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'agent/src')]

from scripts import customer_agent_acceptance_v1 as base

VERSION = 'customer-agent-publication-v2'
DIRECTORY = ROOT / 'evals' / VERSION
PLAN = DIRECTORY / 'manifest.json'
prior = base.prior


def load_cases():
    data = prior.read_json(DIRECTORY / 'scenarios.json')
    if data['version'] != VERSION or [c['id'] for c in data['cases']] != ['A01', 'R01']:
        raise ValueError('unexpected publication confirmation cohort')
    originals = prior.read_json(ROOT / 'evals/customer-agent-acceptance-v1/scenarios.json')['cases']
    source = {c['source_id']: c for c in base.navigation.load_cases()}
    cases = []
    for selected, original in zip(data['cases'], originals, strict=True):
        if selected != original:
            raise ValueError('fixed questions, modes and criteria must remain unchanged')
        case = deepcopy(source[selected['source_id']])
        case.update(deepcopy(selected), id=VERSION + ':' + selected['id'],
                    partition='development-visible-post-fix-confirmation', architecture='staged-v1')
        cases.append(case)
    return cases


def freeze(path=PLAN):
    cases = load_cases()
    old = prior.read_json(base.PLAN)
    files = set(old['files']) | {
        'scripts/customer_agent_publication_v2.py', 'scripts/customer_agent_publication_diagnose_v2.py',
        'evals/customer-agent-publication-v2/scenarios.json', 'docs/customer-agent-publication-v2.md',
        'agent/tests/unit/test_customer_agent_publication_v2.py',
        'agent/tests/unit/test_support_navigation_publication.py',
        'agent/tests/integration/test_support_navigation_publication.py',
        'reports/customer-agent-acceptance-v1/natural-results.json',
        'reports/customer-agent-acceptance-v1/repair-results.json',
    }
    prior.write_new(path, {'version': VERSION, 'natural_turns': 4, 'probe_turns': 1,
        'not_resume_metrics': True, 'not_holdout': True, 'synthetic_facts': True, 'architecture': 'staged-v1',
        'production_commit': '426f08c3ae368353131c78c985995e3ea6c006fd',
        'order': [{'id': c['id'], 'turns': len(c['turns']), 'mode': c['mode']} for c in cases],
        'files': {p: prior.digest(ROOT / p) for p in sorted(files)}, 'embedding_files': old['embedding_files']})


def load_plan(path=None):
    plan = prior.read_json(path or PLAN)
    if plan['version'] != VERSION:
        raise ValueError('wrong confirmation version')
    for name, fingerprint in plan['files'].items():
        if prior.digest(ROOT / name) != fingerprint:
            raise ValueError('frozen source changed: ' + name)
    for name, fingerprint in plan['embedding_files'].items():
        if prior.digest(Path(prior.MODEL_PATH) / name) != fingerprint:
            raise ValueError('embedding changed: ' + name)
    return plan, load_cases()


def evaluate(output, usage_path):
    # Both natural execution and probe resolve these globals inside the bounded patch.
    with patch.object(base, 'VERSION', VERSION), patch.object(base, 'PLAN', PLAN), \
            patch.object(base, 'load_cases', load_cases), patch.object(base, 'load_plan', load_plan):
        base.evaluate(output, usage_path)


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
