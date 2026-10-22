"""New frozen two-turn confirmation of single-source answer parts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'agent/src')]

from scripts import customer_agent_event_groups_v1 as prior

DIRECTORY = ROOT / 'evals/customer-agent-answer-parts-v1'
PLAN = DIRECTORY / 'manifest.json'
driver = prior.driver
io = prior.io


def load_cases():
    cases = io.read_json(DIRECTORY / 'cases.json')['cases']
    old = prior.load_cases()
    if len(cases) != 2:
        raise ValueError('exactly two autonomous checks required')
    for case, previous in zip(cases, old, strict=True):
        left, right = case['input_without_deadline'], previous['input_without_deadline']
        if any(left[k] == right[k] for k in ['run_id', 'conversation_id']):
            raise ValueError('new identities required')
        if {k: v for k, v in left.items() if k not in {'run_id', 'conversation_id'}} != {
            k: v for k, v in right.items() if k not in {'run_id', 'conversation_id'}
        }:
            raise ValueError('original request changed')
        if any(case[k] != previous[k] for k in [
            'facts', 'http_status', 'pinned_generations', 'criteria', 'source_case',
        ]):
            raise ValueError('original facts or conditions changed')
    return cases


def freeze(path=PLAN):
    load_cases()
    previous = io.read_json(prior.PLAN)
    files = set(previous['files']) | {
        'evals/customer-agent-event-groups-v1/manifest.json', 'evals/customer-agent-answer-parts-v1/cases.json',
        'reports/customer-agent-event-groups-v1/runtime-results.json', 'scripts/customer_agent_answer_parts_v1.py',
        'agent/tests/unit/test_customer_agent_answer_parts_v1.py', 'agent/tests/unit/test_support_answer_parts.py',
        'agent/tests/integration/test_support_answer_parts_api.py', 'docs/customer-agent-answer-parts-v1.md',
    }
    io.write_new(path, {'version': 'customer-agent-answer-parts-v1', 'autonomous_turns': 2,
                        'factual_scope': 'Two seen synthetic HTTP snapshots; actual model/ASGI/AgentScope/PG, no Java/browser',
                        'files': {p: io.digest(ROOT / p) for p in sorted(files)},
                        'embedding_files': previous['embedding_files']})


def load_plan(path=PLAN):
    plan = io.read_json(path)
    for name, fingerprint in plan['files'].items():
        if io.digest(ROOT / name) != fingerprint:
            raise ValueError('frozen source changed: ' + name)
    for name, fingerprint in plan['embedding_files'].items():
        if io.digest(Path(driver.MODEL_PATH) / name) != fingerprint:
            raise ValueError('embedding changed: ' + name)
    return {**plan, 'cases': load_cases()}


def execute(output, usage):
    with patch.object(driver, 'PLAN', PLAN), patch.object(driver, 'load_plan', load_plan):
        driver.evaluate(output, usage)


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
        plan = load_plan()
        result = {'version': plan['version'], 'autonomous_turns': len(plan['cases']), 'new_models': 0}
        if args.database:
            scoped = [{'id': c['id'], 'snapshot': c, 'turns': [{
                'text': c['input_without_deadline']['context']['current_request'], 'criteria': c['criteria']
            }]} for c in plan['cases']]
            result['database'] = io.previous.check_database(scoped, driver.DSN)
        if args.output:
            io.write_new(args.output, result)
        print(json.dumps({k: v for k, v in result.items() if k != 'database'}))
    elif args.output is None:
        parser.error('--output required')
    else:
        execute(args.output, args.live_usage)


if __name__ == '__main__':
    main()
