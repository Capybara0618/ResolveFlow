"""Continue only the unexecuted conversation suffix after a report-file failure; never rerun answers."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from scripts import customer_workflow_comparison_live as driver
from scripts.customer_rag_live_v2 import persist as durable_persist
from scripts.customer_workflow_comparison_prepare import (
    DATA,
    digest,
    read,
    sent_models,
)

ROOT = driver.ROOT
SOURCE = ROOT / 'reports/customer-workflow-comparison-v2/agent-runtime.json'
PLAN = DATA.with_name('continuation-manifest.json')
TOTAL_LIMIT = 400


def matrix():
    return [driver.empty_row(case, variant, index) for number, case in enumerate(driver.cases())
        for variant in (driver.VARIANTS if number % 2 == 0 else driver.VARIANTS[::-1])
        for index in range(len(case['turns']))]


def validate_prefix(prefix, ledger_used):
    expected, rows = matrix(), prefix['rows']
    if (prefix.get('version') != driver.VERSION or prefix.get('dataset_sha256') != digest(DATA)
            or prefix.get('state') != 'ERROR' or prefix.get('error_type') != 'PermissionError'
            or not prefix.get('isolated_schema_dropped') or not 0 < len(rows) < len(expected)):
        raise ValueError('not an exported report-file interruption')
    for row, wanted in zip(rows, expected, strict=False):
        if any(row.get(k) != wanted[k] for k in ('case_id', 'variant', 'turn', 'run_id')):
            raise ValueError('saved prefix identity/order differs')
        if row['status'] not in {'SUCCEEDED', 'FAILED', 'TIMEOUT', 'BUDGET_EXHAUSTED'} or row['elapsed_ms'] is None:
            raise ValueError('unfinished prefix cannot be replayed as completed')
        if any(m.get('state') not in {'COMPLETE', 'ERROR'} for m in row['models']):
            raise ValueError('unfinished provider call requires separate audit')
    if expected[len(rows)]['turn'] != 1:
        raise ValueError('continuation requires a conversation boundary; no fresh-state mid-conversation restart')
    count = len(sent_models(rows))
    if (ledger_used != prefix['usage_after'] or ledger_used - prefix['usage_before'] != count
            or prefix['max_new_provider_requests'] != TOTAL_LIMIT or count >= TOTAL_LIMIT):
        raise ValueError('ledger/prefix allowance differs')
    return TOTAL_LIMIT - count


def continuation_matrix(original, prefix):
    rows = prefix['rows']
    def run(selected, report, execute_turn, save):
        at = 0
        def next_turn(case, variant, index, completed):
            nonlocal at
            position = at
            at += 1
            if position < len(rows):
                wanted = driver.empty_row(case, variant, index)
                if rows[position]['run_id'] != wanted['run_id']:
                    raise ValueError('saved prefix order changed')
                return deepcopy(rows[position])
            return execute_turn(case, variant, index, completed)
        original(selected, report, next_turn, save)
    return run


def frozen_metadata():
    driver.load_plan()
    prefix = read(SOURCE)
    remaining = validate_prefix(prefix, read(driver.USAGE)['used'])
    names = ['scripts/customer_workflow_comparison_continue.py',
        'agent/tests/unit/test_customer_workflow_comparison_continue.py', 'scripts/customer_rag_live_v2.py']
    return {'version': 'customer-workflow-comparison-v2-continuation-v1',
        'original_manifest_sha256': digest(driver.PLAN), 'interrupted_runtime_sha256': digest(SOURCE),
        'ledger_before_original': prefix['usage_before'], 'ledger_at_interruption': prefix['usage_after'],
        'total_limit': TOTAL_LIMIT, 'remaining_allowance': remaining,
        'completed_prefix_turns': len(prefix['rows']), 'unexecuted_turns': 100 - len(prefix['rows']),
        'new_behavior': 'driver file I/O retry and exact saved-prefix reuse only; production/model/data unchanged',
        'files': {n: digest(ROOT / n) for n in names}}


def execute(output):
    supplement = read(PLAN)
    if supplement != frozen_metadata():
        raise ValueError('continuation source/runtime/ledger differs')
    prefix = read(SOURCE)
    with (patch.object(driver, 'persist', durable_persist),
          patch.object(driver, 'run_matrix', continuation_matrix(driver.run_matrix, prefix))):
        driver.execute(output, supplement['remaining_allowance'])
    report = read(output)
    if report['rows'][:len(prefix['rows'])] != prefix['rows']:
        raise ValueError('saved answers changed during continuation')
    if prefix['public_before'] != report['public_before'] or prefix['public_before'] != report['public_after']:
        raise ValueError('retained data changed across segments')
    report['continuation'] = {**supplement, 'supplement_sha256': digest(PLAN),
        'segment_usage_before': report['usage_before'], 'segment_max_new_provider_requests': report['max_new_provider_requests']}
    report['usage_before'] = prefix['usage_before']
    report['max_new_provider_requests'] = TOTAL_LIMIT
    for name in ('all_runs', 'all_calls'):
        report[name] = prefix[name] + report[name]
    if report['usage_after'] - report['usage_before'] != len(sent_models(report['rows'])):
        raise ValueError('combined ledger/attempt count differs')
    durable_persist(output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['freeze', 'execute'])
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.mode == 'freeze':
        driver.write_new(PLAN, frozen_metadata())
    else:
        if not args.live or not args.output:
            parser.error('explicit --live and new --output required')
        execute(args.output)


if __name__ == '__main__':
    main()
