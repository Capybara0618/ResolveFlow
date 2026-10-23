"""Offline isolate the page-label predicate using frozen failures; never a production bypass or score."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'agent/src'), str(ROOT / 'agent')]

from resolveflow.support import navigation
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportInput
from tests.integration.test_support_dialogue_api import TokenizedScript

from scripts.customer_agent_navigation_diagnose_v1 import SavedSources

FROZEN = {
    'natural-results.json': '0634f803d06db29517f5359e5420895a2e064f5d3263e7df89b543025c5291f0',
    'repair-results.json': 'fc382cb47ee8fcdae2d412c6ca6e6a6cbdb15f92873fd6d97cbb447f0f548b9e',
}


def diagnose():
    results = []
    for name, digest in FROZEN.items():
        path = ROOT / 'reports/customer-agent-acceptance-v1' / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        report = json.loads(path.read_text(encoding='utf-8'))
        row = report['rows'][1] if name == 'natural-results.json' else report
        req = SupportInput.model_validate({**row['input'],
            'deadline_at': dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)})
        script = [m['decision'] for m in row.get('injected', []) + row['models']]
        attempts = []
        for disabled in [False, True]:
            saved = SavedSources(row['tools'])
            model = TokenizedScript(mode='live', script=script)
            labels = () if disabled else navigation.PAGE_LABELS
            with patch.object(navigation, 'PAGE_LABELS', labels):
                result = SupportAgent(req, model, saved, architecture='staged-v1').run()
            assert result['status'] == ('SUCCEEDED' if disabled else 'FAILED')
            assert saved.position == len(row['tools'])
            attempts.append({'page_label_predicate_disabled_in_diagnostic_only': disabled,
                'status': result['status'], 'saved_decisions': model.calls,
                'saved_tools': saved.position, 'text': (result.get('answer') or {}).get('text')})
        results.append({'raw': name, 'attempts': attempts})
    assert navigation.PAGE_LABELS == ('售后咨询', '我的售后')
    return {'diagnostic_only': True, 'not_strict_replay': True, 'new_provider_calls': 0,
            'business_writes': 0, 'production_code_changed': False, 'raw_sha256': FROZEN, 'rows': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = diagnose()
    if args.output.exists():
        assert json.loads(args.output.read_text(encoding='utf-8')) == value
    else:
        args.output.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())
    print({'failed_paths_isolated': len(value['rows']), 'new_provider_calls': 0})


if __name__ == '__main__':
    main()
