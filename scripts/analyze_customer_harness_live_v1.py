"""Offline-only aggregation from original runtime and explicit nonblind source reviews."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.customer_harness_live_v1 import context_slots, dataset
from scripts.evaluation.customer_harness_context_v1 import RECOVERY_WINDOWS, write_new


def reduction(before, after):
    return None if before is None or after is None or before == 0 else (before - after) / before


def cost(records):
    sent = [r for r in records if r.get('send_reserved')]
    known = [r for r in sent if r.get('usage_kind') == 'PROVIDER' and r.get('usage') is not None]
    unknown = len(sent) - len(known)
    inputs = sum(r['usage']['input_tokens'] for r in known)
    outputs = sum(r['usage']['output_tokens'] for r in known)
    return {'request_reservations': len(sent), 'unknown_usage_requests': unknown,
            'known_input_tokens': inputs, 'known_output_tokens': outputs,
            'input_tokens': inputs if not unknown else None, 'output_tokens': outputs if not unknown else None}


def quality(labels):
    if not labels or any(type(r.get('pass')) is not bool or not r.get('reason') or not r.get('evidence') for r in labels):
        raise ValueError('explicit complete source review required')
    passed = sum(r['pass'] for r in labels)
    return {'passed': passed, 'total': len(labels), 'rate': passed / len(labels)}


def key(row):
    return row['case_id'], row['variant'], row['checkpoint']


def reviewed_cost(rows, labels):
    label_map = {key(r): r for r in labels}
    by = {key(r): r for r in rows}
    chosen = [(case_id, checkpoint) for case_id, variant, checkpoint in by if variant == 'raw'
              and (case_id, 'layered', checkpoint) in by
              and label_map[(case_id, 'raw', checkpoint)]['pass']
              and label_map[(case_id, 'layered', checkpoint)]['pass']]
    raw = cost([m for case_id, checkpoint in chosen for m in by[(case_id, 'raw', checkpoint)]['models']])
    layered = cost([m for case_id, checkpoint in chosen for m in by[(case_id, 'layered', checkpoint)]['models']])
    return {'paired_checkpoints': len(chosen), 'raw': raw, 'layered': layered,
            'input_token_reduction': reduction(raw['input_tokens'], layered['input_tokens'])}


def analyze(runtime, review):
    rows = runtime['context']
    labels = review['context']
    expected = {(s['case_id'], s['variant'], s['checkpoint']) for s in context_slots()}
    if (len(rows) != 64 or {key(r) for r in rows} != expected
            or len(labels) != 64 or {key(r) for r in labels} != expected):
        raise ValueError('context matrix incomplete or duplicated')
    quality(labels)
    actual = {key(r): r for r in rows}
    for label in labels:
        if label['pass'] and actual[key(label)].get('result', {}).get('status') != 'SUCCEEDED':
            raise ValueError('technical failure cannot be a semantic success')
    context = {}
    for variant in ('raw', 'layered'):
        selected = [r for r in rows if r['variant'] == variant]
        marked = [r for r in labels if r['variant'] == variant]
        context[variant] = {'quality': quality(marked), 'second_checkpoint': quality([
            r for r in marked if r['checkpoint'] == 2]), 'cost': cost([m for r in selected for m in r['models']]),
            'technical_statuses': dict(Counter(r.get('result', {}).get('status', 'NOT_RUN') for r in selected)),
            'families': {family: quality([r for r in marked if r['case_id'].startswith(family + '-')])
                         for family in ('recall', 'correction', 'resume', 'no_repeat')}}
    context['paired_success_cost'] = reviewed_cost(rows, labels)
    context['overall_input_token_reduction'] = reduction(
        context['raw']['cost']['input_tokens'], context['layered']['cost']['input_tokens'])
    context['quality_difference_percentage_points'] = 100 * (
        context['layered']['quality']['rate'] - context['raw']['quality']['rate'])

    recoveries, reviewed = runtime['recovery'], review['recovery']
    rkey = lambda r: (r['case_id'], r['window'], r['arm'])
    planned = {(c['id'], w, arm) for c in dataset()['recovery_cases'] for w in RECOVERY_WINDOWS
               for arm in ('resume', 'redo')}
    if (len(recoveries) != 30 or {rkey(r) for r in recoveries} != planned
            or len(reviewed) != 30 or {rkey(r) for r in reviewed} != planned):
        raise ValueError('recovery matrix incomplete or duplicated')
    rmap, rlabels = {rkey(r): r for r in recoveries}, {rkey(r): r for r in reviewed}
    for label in reviewed:
        if (type(label.get('result_correct')) is not bool or not label.get('reason') or not label.get('evidence')):
            raise ValueError('explicit complete recovery source review required')
        row = rmap[rkey(label)]
        result = ((row.get('post') or {}).get('record') or {}).get('result') or {}
        if label['result_correct'] and result.get('status') != 'SUCCEEDED':
            raise ValueError('unknown/missing result cannot count as completed recovery')
    recovery = {}
    all_costs = []
    for window in RECOVERY_WINDOWS:
        block = {}
        paired = [c['id'] for c in dataset()['recovery_cases'] if all(
            rlabels[(c['id'], window, arm)]['result_correct'] for arm in ('resume', 'redo'))]
        for arm in ('resume', 'redo'):
            chosen = [r for r in recoveries if r['window'] == window and r['arm'] == arm]
            post_records = [m for r in chosen for m in ((r.get('post') or {}).get('record') or {}).get('models', [])]
            prefix_records = [m for r in chosen for m in ((r.get('prefix') or {}).get('record') or {}).get('models', [])]
            block[arm] = {'correct_results': sum(rlabels[rkey(r)]['result_correct'] for r in chosen),
                          'total': 5, 'post_cost': cost(post_records), 'prefix_cost': cost(prefix_records),
                          'statuses': dict(Counter((((r.get('post') or {}).get('record') or {}).get('result') or {}).get(
                              'status', 'NOT_RUN') for r in chosen))}
            all_costs.extend(prefix_records + post_records)
        block['both_correct_pairs'] = paired
        for arm in ('resume', 'redo'):
            records = [m for case_id in paired for m in rmap[(case_id, window, arm)]['post']['record']['models']]
            block[arm]['paired_post_cost'] = cost(records)
        block['paired_post_request_reduction'] = reduction(
            block['redo']['paired_post_cost']['request_reservations'],
            block['resume']['paired_post_cost']['request_reservations'])
        recovery[window] = block
    pairs = [(case_id, window) for window, block in recovery.items() for case_id in block['both_correct_pairs']]
    paired_costs = {arm: cost([m for case_id, window in pairs for m in rmap[(case_id, window, arm)][
        'post']['record']['models']]) for arm in ('resume', 'redo')}
    recovery['paired_complete'] = {'pairs': len(pairs), **paired_costs,
        'request_reduction': reduction(paired_costs['redo']['request_reservations'],
                                       paired_costs['resume']['request_reservations']),
        'input_token_reduction': reduction(paired_costs['redo']['input_tokens'], paired_costs['resume']['input_tokens'])}
    recovery['all_quality'] = {arm: {'correct': sum(r['result_correct'] for r in reviewed if r['arm'] == arm),
                                    'total': 15} for arm in ('resume', 'redo')}
    context_records = [m for r in rows for m in r['models']]
    return {'context': context, 'recovery': recovery, 'all_records': cost(context_records + all_costs),
            'session_reservations': runtime.get('used_by_phase'),
            'source_review_kind': review['review_kind'], 'not_holdout': True, 'real_customers': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    runtime = json.loads(args.runtime.read_text(encoding='utf-8'))
    review = json.loads(args.review.read_text(encoding='utf-8'))
    result = analyze(runtime, review)
    result['sources'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.runtime, args.review,
                                                                                   Path(__file__))}
    write_new(args.output, result)


if __name__ == '__main__':
    main()
