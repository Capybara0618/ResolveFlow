"""Offline counterfactual on saved decisions, not new provider calls or strict manifest replay."""

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

FROZEN = {
    'customer-agent-navigation-v1': '7e873e6d11c19b2165d4795543d1630f80ed1467e34dae6c77c78925d16fbf86',
    'customer-agent-correction-v1': '1c17ec911247b6f362da70189b71e719ef9f8480f9a417e239626a478b408ae4',
}


class SavedSources:
    def __init__(self, tools):
        self.tools, self.position = tools, 0

    def read(self, name, arguments):
        tool = self.tools[self.position]
        assert tool['name'] == name
        self.position += 1
        return tool['result']

    def search(self, query, top_k):
        tool = self.tools[self.position]
        assert tool['name'] == 'search_policy'
        assert tool['query'] == query and tool['top_k'] == top_k
        self.position += 1
        return tool['result']


def diagnose():
    rows = []
    for version, expected in FROZEN.items():
        raw = ROOT / 'reports' / version / 'runtime-results.json'
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == expected
        report = json.loads(raw.read_text(encoding='utf-8'))
        for row in report['rows']:
            if version.endswith('correction-v1') and (not row['id'].endswith(':C01') or row['turn'] not in {3, 4}):
                continue
            sources = SavedSources(row['tools'])
            # Only the diagnostic copy gets a fresh deadline; no manifest/budget reset on a saved run.
            req = SupportInput.model_validate({**row['input'],
                'deadline_at': dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)})
            script = [m['decision'] for m in row['models']]
            if version.endswith('correction-v1'):
                script.append(script[-1])  # The same bad free route remains bad after the one feedback.
            model = TokenizedScript(mode='live', script=script)
            result = SupportAgent(req, model, sources, architecture='staged-v1').run()
            should_publish = version.endswith('navigation-v1') and not (row['id'].endswith(':C01') and row['turn'] == 1)
            assert result['status'] == ('SUCCEEDED' if should_publish else 'FAILED'), result
            feedback = [json.loads(p['feedback']) for p in model.packets if p.get('feedback')]
            if not should_publish:
                assert feedback and feedback[0]['field'] == 'next_steps'
            if version.endswith('navigation-v1') and not should_publish:
                assert feedback[0]['resubmit'] == 'READ_THEN_FULL_ANSWER'
            rows.append({'source_version': version, 'id': row['id'], 'turn': row['turn'],
                'original_published': row['result']['status'] == 'SUCCEEDED',
                'offline_status': result['status'], 'saved_decisions_consumed': model.calls,
                'saved_tools_consumed': sources.position, 'feedback': feedback,
                'text': (result.get('answer') or {}).get('text')})
    return {'diagnostic_only': True, 'not_strict_replay': True, 'new_provider_calls': 0, 'business_writes': 0,
            'raw_sha256': FROZEN, 'rows': rows}


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
    print({'diagnostic_rows': len(value['rows']), 'new_provider_calls': 0})


if __name__ == '__main__':
    main()
