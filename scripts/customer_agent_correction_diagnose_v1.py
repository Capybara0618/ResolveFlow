"""Replay recorded decisions offline to locate validation versus answer-semantic boundaries."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportInput
from tests.integration.test_support_dialogue_api import TokenizedScript

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'reports/customer-agent-correction-v1/runtime-results.json'
EXPECTED = '1c17ec911247b6f362da70189b71e719ef9f8480f9a417e239626a478b408ae4'


def diagnose():
    assert hashlib.sha256(RAW.read_bytes()).hexdigest() == EXPECTED
    report = json.loads(RAW.read_text(encoding='utf-8'))
    rows = []
    for row in report['rows']:
        if not row['id'].endswith(':C01') or row['turn'] not in {3, 4}:
            continue

        class SavedSources:
            def __init__(self, tools):
                self.position = 0
                self.tools = tools

            def read(self, name, arguments):
                tool = self.tools[self.position]
                assert tool['name'] == name
                self.position += 1
                return tool['result']

        sources = SavedSources(row['tools'])
        # Expired wall-clock deadline is refreshed in the diagnostic copy only; raw stays frozen.
        req = SupportInput.model_validate({**row['input'], 'deadline_at': dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)})
        model = TokenizedScript(mode='live', script=[m['decision'] for m in row['models']])
        result = SupportAgent(req, model, sources, architecture='staged-v1').run()
        assert result['status'] == 'SUCCEEDED'
        assert result['answer']['text'] == row['result']['answer']['text']
        assert result['answer']['customer_memory'] == row['result']['answer']['customer_memory']
        assert sources.position == len(row['tools'])
        text = result['answer']['text']
        guide = next(t['result']['data']['text'] for t in row['tools'] if t['name'] == 'get_support_guide')
        rows.append({'id': row['id'], 'turn': row['turn'], 'offline_accepted_original_decisions': True,
            'original_answer_and_memory_preserved': True, 'saved_decisions': model.calls,
            'original_guide_read': '打开售后咨询' in guide and '请商家核查' in guide,
            'answer_mixes_refund_entry_with_review': '「我的售后」' in text and '「请商家核查」' in text,
            'new_provider_calls': 0, 'business_writes': 0})
    return {'raw_sha256': EXPECTED, 'diagnostic_only': True, 'rows': rows}


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
    print(json.dumps(value))


if __name__ == '__main__':
    main()
