"""Re-evaluate saved decisions with the actual new rule, no predicate disabling or live calls."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'agent/src'), str(ROOT / 'agent')]

from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportInput
from tests.integration.test_support_dialogue_api import TokenizedScript

from scripts.customer_agent_acceptance_diagnose_v1 import FROZEN
from scripts.customer_agent_navigation_diagnose_v1 import SavedSources


def diagnose():
    rows = []
    for name, digest in FROZEN.items():
        path = ROOT / 'reports/customer-agent-acceptance-v1' / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        report = json.loads(path.read_text(encoding='utf-8'))
        for row in report.get('rows', [report]):
            req = SupportInput.model_validate({**row['input'],
                'deadline_at': dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)})
            script = [m['decision'] for m in row.get('injected', []) + row['models']]
            saved = SavedSources(row['tools'])
            model = TokenizedScript(mode='live', script=script)
            result = SupportAgent(req, model, saved, architecture='staged-v1').run()
            assert result['status'] == 'SUCCEEDED', result
            assert saved.position == len(row['tools'])
            rows.append({'raw': name, 'turn': row.get('turn', 'R01'), 'original_status': row['result']['status'],
                'offline_status': result['status'], 'saved_decisions_consumed': model.calls,
                'saved_tools_consumed': saved.position, 'text': result['answer']['text']})
    return {'diagnostic_only': True, 'not_strict_replay': True, 'new_provider_calls': 0,
            'business_writes': 0, 'predicate_disabled': False, 'raw_sha256': FROZEN, 'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = diagnose()
    if args.output.exists():
        assert json.loads(args.output.read_text(encoding='utf-8')) == value
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())
    print({'saved_paths_passed': len(value['rows']), 'new_provider_calls': 0, 'predicate_disabled': False})


if __name__ == '__main__':
    main()
