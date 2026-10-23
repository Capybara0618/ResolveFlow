"""One finite staged run on new expressions; retain every failure, never change old reports."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'agent/src')]

from scripts import customer_agent_state_live_v1 as state

prior = state.prior
VERSION = 'customer-agent-correction-v1'
DIRECTORY = ROOT / 'evals' / VERSION
PLAN = DIRECTORY / 'manifest.json'


def load_cases():
    source = {c['source_id']: c for c in state.load_cases()}
    data = prior.read_json(DIRECTORY / 'scenarios.json')
    if data['version'] != VERSION or [c['id'] for c in data['cases']] != ['C01', 'C02', 'C03']:
        raise ValueError('unexpected correction scenarios')
    result = []
    for selected in data['cases']:
        case = deepcopy(source[selected['source_id']])
        case.update(deepcopy(selected), id=VERSION + ':' + selected['id'], architecture='staged-v1',
                    partition='development-visible-new-expression')
        result.append(case)
    if [len(c['turns']) for c in result] != [4, 1, 1]:
        raise ValueError('expected exactly six turns')
    return result


def prepare_turn(case, turn_index, completed):
    return state.prepare_turn(case, turn_index, completed)


def freeze(path=PLAN):
    cases = load_cases()
    old = prior.read_json(state.PLAN)
    files = set(old['files']) | {
        'scripts/customer_agent_correction_v1.py', 'evals/customer-agent-correction-v1/scenarios.json',
        'docs/customer-agent-correction-v1.md', 'agent/tests/unit/test_customer_agent_correction_v1.py',
        'agent/tests/integration/test_customer_agent_correction_v1.py',
        'reports/customer-agent-demo-v2/runtime-results.json', 'agent/src/resolveflow/assets/support-guide-v2.json',
        'agent/tests/unit/test_support_customer_claims.py', 'agent/tests/integration/test_support_conversation_update.py',
    }
    prior.write_new(path, {'version': VERSION, 'turns': 6, 'not_resume_metrics': True,
        'synthetic_facts': True, 'not_holdout': True, 'architecture': 'staged-v1',
        'order': [{'id': c['id'], 'turns': len(c['turns'])} for c in cases],
        'files': {p: prior.digest(ROOT / p) for p in sorted(files)}, 'embedding_files': old['embedding_files']})


def load_plan(path=None):
    plan = prior.read_json(path or PLAN)
    if plan['version'] != VERSION:
        raise ValueError('wrong version')
    for name, digest in plan['files'].items():
        if prior.digest(ROOT / name) != digest:
            raise ValueError('frozen source changed: ' + name)
    for name, digest in plan['embedding_files'].items():
        if prior.digest(Path(prior.MODEL_PATH) / name) != digest:
            raise ValueError('embedding changed: ' + name)
    return plan, load_cases()


def evaluate(output, usage_path):
    from resolveflow.support import service

    original = service.SupportRuntime

    class StagedRuntime(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, architecture='staged-v1')

    with patch.object(prior, 'PLAN', PLAN), patch.object(prior, 'load_plan', load_plan), \
            patch.object(prior, 'prepare_turn', prepare_turn), patch.object(service, 'SupportRuntime', StagedRuntime):
        prior.evaluate(output, usage_path)


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
        result = {'version': plan['version'], 'turns': 6, 'new_models': 0}
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
