"""Source-bound subset comparison and Codex semantic review; never calls a provider."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'agent/src'))

from resolveflow.harness.actions import ModelDecision  # noqa: E402
from scripts.agent_rag_source_review import (  # noqa: E402
    match_searches,
    object_hash,
    policy_rows,
    saved_observation,
    verify_hits,
)
from scripts.evaluation.dataset import digest, read, validate  # noqa: E402
from scripts.evaluation.quality_audit import audit as usage_audit  # noqa: E402
from scripts.evaluation.reporting import compare_reports  # noqa: E402
from scripts.evaluation.scoring import score_agent  # noqa: E402

DIMENSIONS = ('factual_support', 'policy_application', 'action_reason_alignment',
              'responsibility', 'merchant_readability')


def project(report: dict, ids: list[str]) -> dict:
    """Keep original entries unchanged; only recalculate subset aggregates."""
    entries = report['results']
    if (not ids or len(set(ids)) != len(ids) or len({e['id'] for e in entries}) != len(entries)
            or set(ids) - {e['id'] for e in entries}):
        raise ValueError('Nonzero unique cohort must be present in baseline')
    result = copy.deepcopy(report)
    result['results'] = [e for e in result['results'] if e['id'] in ids]
    result['summary'] = {
        'n': len(ids),
        'joint_correct': sum(bool(e['joint_correct']) for e in result['results']),
        'action_correct': sum(bool(e['action_correct']) for e in result['results']),
        'incomplete': sum(not e['completed'] for e in result['results']),
        'model_calls': sum(e['model_calls'] for e in result['results']),
    }
    return result


def semantic_review(labels: dict, entries: list[dict], cases: dict, report_hash: str) -> dict:
    rows = labels.get('cases', [])
    if (labels.get('origin') != 'CODEX_REVIEW' or labels.get('blind') is not False
            or labels.get('report_sha256') != report_hash or not labels.get('reviewed_at')
            or len(rows) != len(entries) or {r['id'] for r in rows} != {e['id'] for e in entries}):
        raise ValueError('Complete nonblind source-bound review required')
    by_id = {r['id']: r for r in rows}
    for entry in entries:
        row = by_id[entry['id']]
        if (row.get('entry_sha256') != object_hash(entry)
                or row.get('case_sha256') != object_hash(cases[entry['id']]) or not row.get('notes')):
            raise ValueError('Review entry/facts source differs')
        for field in DIMENSIONS:
            allowed = {'PASS', 'WARN', 'FAIL'} if entry['completed'] else {'NOT_COMPLETED'}
            if row.get(field) not in allowed:
                raise ValueError('Invalid semantic value or incomplete result promoted to success')
    return {field: dict(Counter(row[field] for row in rows)) for field in DIMENSIONS}


def audit(cohort: dict, candidate: dict, baseline: dict, labels: dict, candidate_hash: str) -> dict:
    for name, expected in cohort['inputs'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or digest(path) != expected:
            raise ValueError('Frozen input differs: ' + name)
    dataset = ROOT / cohort['dataset']
    validate(dataset)
    ids = cohort['case_ids']
    if (len(candidate['results']) != len(ids) or {e['id'] for e in candidate['results']} != set(ids)
            or candidate.get('code_commit') != cohort['code_commit']):
        raise ValueError('Candidate differs from preselected cohort/version')
    before = project(baseline, ids)
    comparison = compare_reports(before, candidate)
    cases = {c['id']: c for c in read('agent/cases.json', dataset)}
    bundles = {b['bundle_id']: b for b in read('policies/bundles.json', dataset)}
    rows = []
    for entry in candidate['results']:
        case = cases[entry['id']]
        decision = ModelDecision.model_validate(entry['decision']) if entry.get('decision') else None
        observed = [saved_observation(o) for o in entry.get('observations', [])]
        score = score_agent(SimpleNamespace(completed=entry['completed'], decision=decision,
                                           observations=observed), read('gold/agent.json', dataset)[entry['id']],
                            case=case)
        if any(entry.get(k) != value for k, value in score.items()):
            raise ValueError('Saved automatic score differs')
        searches = match_searches(entry)
        bundle = bundles[case['bundle_id']]
        for search in searches:
            if search['observation']:
                verify_hits(search['observation'], bundle)
        frames = [policy_rows(request) for request in entry['requests']]
        source_rules = {r['rule_id']: r['text'] for r in bundle['rules']}
        for frame in frames:
            for rule in frame:
                if (rule['bundle_id'] != bundle['bundle_id'] or rule['version'] != bundle['version']
                        or rule['rule_id'] not in source_rules or rule['text'] != source_rules[rule['rule_id']]):
                    raise ValueError('Policy frame differs from complete source')
        rows.append({'id': entry['id'], 'completed': entry['completed'],
                     'kind': (entry.get('decision') or {}).get('kind'),
                     'action': entry.get('action'), 'reason_code': entry.get('reason_code'),
                     'search_attempts': len(searches),
                     'search_executed': sum(s['execution'] == 'EXECUTED' for s in searches),
                     'refusals': [n for n in entry.get('notices', []) if n.startswith('REFUSED ')],
                     'terminal_trajectory': [t for t in entry.get('trajectory', [])
                                             if t.get('action') in {'PROPOSE', 'ASK_CUSTOMER', 'ESCALATE', 'STOP'}]})
    return {'version': 'agent-handoff-comparison-v1', 'cohort_case_ids': ids,
            'candidate_sha256': candidate_hash, 'comparison': comparison,
            'semantic_review': semantic_review(labels, candidate['results'], cases, candidate_hash),
            'usage': usage_audit(candidate, dataset), 'case_results': rows,
            'origin': 'CODEX_REVIEW_NONBLIND_SYNTHETIC_SINGLE_RUN', 'new_model_calls': 0,
            'production_writes': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cohort', 'candidate', 'baseline', 'review', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Completed report is immutable; use a new path')
    cohort = json.loads(args.cohort.read_text(encoding='utf-8'))
    if (args.baseline.resolve() != (ROOT / cohort['baseline']).resolve()
            or args.candidate.resolve() != (ROOT / cohort['candidate']).resolve()):
        raise ValueError('Report paths differ from frozen protocol')
    result = audit(cohort, json.loads(args.candidate.read_text(encoding='utf-8')),
                   json.loads(args.baseline.read_text(encoding='utf-8')),
                   json.loads(args.review.read_text(encoding='utf-8')), digest(args.candidate))
    result.update(cohort_sha256=digest(args.cohort), review_sha256=digest(args.review),
                  runner_sha256=digest(Path(__file__)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'comparison': result['comparison'], 'semantic_review': result['semantic_review']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
