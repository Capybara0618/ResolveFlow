"""One explicit provider interoperability probe. No Agent quality or browser latency claim."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'agent/src')]

from resolveflow.harness.budget import BudgetGuard, RunBudget
from resolveflow.harness.context import canonical_json, estimate_tokens
from resolveflow.harness.sdk_adapter import raw_text_message
from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.support.protocol import DECISION
from resolveflow.support.stream_projection import AnswerProjection

from scripts.agent_eval import allowance, persist
from scripts.evaluation.models import CaptureModel, live_guard

PROMPT = '''这是合成的客服界面互通检查。用户问：可以先咨询售后，再决定要不要申请退款吗？
业务说明：咨询独立于退款；只有用户确认申请摘要后才创建申请。请用约60字中文解释。
不猜订单、物流、金额、政策或办理页面名，不生成任何操作结果。
只输出JSON：{"kind":"ANSWER_PARTS","parts":[{"task_id":"info","status":"ANSWERED","text":"自然答复","citations":[]}]}。'''


def execute(output: Path) -> None:
    if output.exists():
        raise ValueError('probe output already exists; never overwrite a previous attempt')
    key = os.environ.get('RESOLVEFLOW_MODEL_API_KEY', '')
    if not key:
        raise ValueError('model key required in environment')
    started = time.perf_counter()
    projection = AnswerProjection()
    deltas: list[dict] = []

    def observe(fragment: str) -> None:
        for delta in projection.feed(fragment):
            deltas.append({'at_ms': (time.perf_counter() - started) * 1000, **asdict(delta)})

    client = StreamingLiveModelClient(
        endpoint='https://api.deepseek.com/chat/completions', model_id='deepseek-flash', provider='deepseek',
        api_key=key, timeout_seconds=30, on_content=observe,
        parameters={'thinking': {'type': 'disabled'}, 'response_format': {'type': 'json_object'}, 'temperature': 0})
    guard = BudgetGuard(RunBudget(model_calls=1, step_output_tokens=256))
    messages = [raw_text_message(PROMPT, role='user')]
    body = client.prepare_request(system='', messages=messages, max_output_tokens=256)
    report = {'scope': 'one provider streaming interoperability probe; not full Agent/browser performance',
              'synthetic_input': True, 'provider_call_limit': 1, 'max_output_tokens': 256,
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'request': body, 'deltas': deltas, 'success': False}
    usage_path = ROOT / 'tmp/evaluation-live-budget.json'
    with live_guard(usage_path):
        usage = allowance(usage_path)
        report['ledger_before'] = usage['used']
        model = CaptureModel(client, allowance=usage)
        try:
            ceiling = guard.reserve_model_request(input_tokens=estimate_tokens(canonical_json(body)) + 256)
            started = time.perf_counter()
            reply = model.decide(system='', messages=messages, max_output_tokens=ceiling)
            guard.settle_model_output(reply.usage.output_tokens, estimated=reply.usage.estimated)
            projection.finish()
            decision = DECISION.validate_python(reply.decision)
            report.update(decision=decision.model_dump(), usage=asdict(reply.usage), model_alias=reply.model_alias)
            report['success'] = bool(deltas) and reply.decision.get('kind') == 'ANSWER_PARTS'
        except Exception as error:  # noqa: BLE001 - archive this single attempt without implicit retries
            report['failure'] = type(error).__name__  # No credential/response error bodies in this report.
        finally:
            report.update(elapsed_ms=(time.perf_counter() - started) * 1000, stream=client.last_stream,
                          provider_calls=client.calls, guard_spend=asdict(guard.spend), ledger_after=usage['used'])
            if deltas and client.last_stream and client.last_stream['completed_ms'] is not None:
                report['body_before_stream_done'] = deltas[0]['at_ms'] < client.last_stream['completed_ms']
            persist(output, report)
            report['report_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
    print(json.dumps({k: report.get(k) for k in ('success', 'provider_calls', 'ledger_before', 'ledger_after',
                                                'body_before_stream_done', 'elapsed_ms', 'report_sha256')}))
    if not report['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    execute(args.output)
