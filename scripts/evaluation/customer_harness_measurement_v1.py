"""Metered production consultation calls; only local transport execution is exposed by the CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.service import SupportRuntime
from resolveflow.support.sources import BoundSources
from resolveflow.support.store import SupportStore

from scripts.customer_rag_live_v2 import persist
from scripts.evaluation.customer_harness_context_v1 import (
    DATA,
    VARIANTS,
    RawHistoryAgent,
    checkpoint_request,
    public_case,
    validate_dataset,
    write_new,
)

VERSION = 'customer-harness-measurement-v1'
PARAMETERS = {'thinking': {'type': 'disabled'}, 'response_format': {'type': 'json_object'}, 'temperature': 0}
SYNTHETIC_POLICY = (
    ('DISPUTE', '签收记录与客户未收到的陈述冲突时，应由商家核验签收证明，客户陈述不能直接作为承运商丢失结论。'),
    ('QUALITY', '客户反馈商品故障或损坏时，可补充照片、视频或排查情况，商家核验后决定处理方式，不因自述直接认定质量责任。'),
    ('REFUND', '用户表达退款意愿后可以预览并编辑申请摘要，用户确认后才创建申请；未发货订单仍须核对订单资格，退款需商家审批。'),
)


class SendAllowance:
    """An explicit per-execution bound; a real caller must additionally persist the shared usage ledger."""

    def __init__(self, limit: int, *, consumed=None) -> None:
        if type(limit) is not int or limit < 0:
            raise ValueError('nonnegative explicit send limit required')
        self.limit, self.used, self.consumed = limit, 0, consumed

    def consume(self) -> None:
        if self.used >= self.limit:
            raise SupportFailure('EVALUATION_ALLOWANCE_EXHAUSTED')
        if self.consumed is not None:
            self.consumed()
        self.used += 1


class MeasuredModel(StreamingLiveModelClient):
    def __init__(self, *, allowance, save, transport_scope, **kwargs):
        super().__init__(**kwargs)
        if transport_scope not in {'MOCK_SSE', 'REAL_PROVIDER'}:
            raise ValueError('explicit transport scope required')
        if transport_scope == 'MOCK_SSE' and not isinstance(self.stream_transport, httpx.MockTransport):
            raise ValueError('offline calls require MockTransport')
        self.allowance, self.save, self.transport_scope = allowance, save, transport_scope
        self.records: list[dict[str, Any]] = []

    def _send(self, payload, headers):
        self.allowance.consume()
        self.records[-1]['send_reserved'] = True
        self.save()
        return super()._send(payload, headers)

    def decide(self, **kwargs):
        record = {'body': self.prepare_request(system=kwargs['system'], messages=kwargs['messages'],
                  max_output_tokens=kwargs['max_output_tokens']),
                  'state': 'STARTED', 'send_reserved': False, 'usage': None,
                  'transport_scope': self.transport_scope, 'usage_kind': 'UNKNOWN'}
        self.records.append(record)
        self.last_stream = None
        self.save()  # A report error before reservation must stop before any transmission.
        started, prior = time.perf_counter(), len(self.requests)
        try:
            reply = super().decide(**kwargs)
            record.update(state='COMPLETE', decision=reply.decision, usage=asdict(reply.usage),
                          usage_kind='ESTIMATED' if reply.usage.estimated else 'PROVIDER',
                          served_model=reply.model_alias)
            return reply
        except Exception as error:
            record.update(state='ERROR', error_type=type(error).__name__)
            raise
        finally:
            record.update(elapsed_ms=(time.perf_counter() - started) * 1000, stream=self.last_stream)
            if len(self.requests) > prior:
                record['http_status'] = self.requests[-1]['status']
            self.save()


def usage_summary(records):
    sent = [r for r in records if r['send_reserved']]
    known = [r for r in sent if r['usage_kind'] == 'PROVIDER']
    unknown = len(sent) - len(known)
    inputs = sum(r['usage']['input_tokens'] for r in known)
    outputs = sum(r['usage']['output_tokens'] for r in known)
    return {'provider_requests': len(sent), 'unknown_usage_requests': unknown,
            'known_provider_input_tokens': inputs, 'known_provider_output_tokens': outputs,
            'provider_input_tokens': inputs if sent and not unknown else None,
            'provider_output_tokens': outputs if sent and not unknown else None}


def prepared_request(case, index, variant, *, deadline, previous=None):
    if previous and previous.get('conversation_update'):
        update = previous['conversation_update']
        if update.get('version') != 'support-state-v1' or any(update.get(k) != previous.get(k)
                for k in ('run_id', 'conversation_id', 'input_version')):
            raise ValueError('accepted update identity mismatch')
    req = checkpoint_request(case, index, variant, deadline=deadline, previous=previous)
    req.context['policy_manifest'] = {'merchant_id': req.merchant_id, 'bundle_ids': ['synthetic-policy'],
                                      'manifest_hash': 'synthetic-policy-v1'}
    return req


class SyntheticIndex:
    """Identical synthetic policy source in both arms; this does not evaluate RAG quality."""

    def __init__(self, request):
        self.request = request

    def require_ready(self, bundles, manifest):
        if bundles != ['synthetic-policy'] or manifest != 'synthetic-policy-v1':
            raise ValueError('synthetic policy scope differs')
        return [SimpleNamespace(merchant_id=self.request.merchant_id, bundle_id='synthetic-policy',
                                generation_id='synthetic-generation-v1')]

    def small_context(self, **kwargs):
        if kwargs != {'merchant_id': self.request.merchant_id, 'bundle_ids': ['synthetic-policy'],
                      'manifest_hash': 'synthetic-policy-v1',
                      'generation_ids': {'synthetic-policy': 'synthetic-generation-v1'}}:
            raise ValueError('synthetic policy generation differs')
        return [SimpleNamespace(version='v1', title='明确标记的合成评测政策', bundle_id='synthetic-policy',
                    merchant_id=self.request.merchant_id, manifest_hash='synthetic-policy-v1', rule_id=key,
                    chunk_id='synthetic-' + key, content_hash=hashlib.sha256(text.encode()).hexdigest(), text=text)
                for key, text in SYNTHETIC_POLICY]


@contextmanager
def source_client(request, records):
    prefix = '/internal/v1/support/turns/' + request.run_id
    def route(call):
        suffix = call.url.path.removeprefix(prefix)
        if call.method != 'GET' or not call.url.path.startswith(prefix + '/'):
            return httpx.Response(403)
        if suffix == '/current':
            value = {'conversation_id': request.conversation_id, 'input_version': request.input_version}
        elif suffix == '/facts/order':
            value = {'line_id': request.line_id, 'merchant_id': request.merchant_id, 'version': 1,
                     'order_line': {'line_id': request.line_id, 'status': 'DELIVERED', 'currency': 'CNY',
                                    'line_paid_amount': 32900, 'quantity': 1, 'version': 1}}
        elif suffix == '/facts/shipment':
            value = {'version': 1, 'synthetic': True, 'lines': [{'line_id': request.line_id,
                'status': 'DELIVERED', 'carrier_conclusion': 'DELIVERED', 'source_version': 1, 'events': []}]}
        elif suffix == '/facts/history':
            limit = int(call.url.params.get('limit', 5))
            before = int(call.url.params.get('before_sequence', request.input_version + 1))
            if not 1 <= limit <= 5 or before <= 0:
                return httpx.Response(400)
            messages = [m for m in request.context['history'] if m['sequence'] < before]
            value = {'version': request.input_version, 'messages': deepcopy(messages[-limit:])}
        else:
            return httpx.Response(403)
        records.append({'path': call.url.path, 'parameters': dict(call.url.params), 'result': deepcopy(value)})
        return httpx.Response(200, json=value)
    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        yield client, SyntheticIndex(request)


class EvaluationStore(SupportStore):
    def __init__(self, database, *, variant='layered', journal_factory=None, inherited=None):
        super().__init__(database)
        self.variant, self.journal_factory, self.inherited = variant, journal_factory, inherited

    def claim(self, request, manifest):
        manifest = deepcopy(manifest) | {'evaluation': {'version': VERSION, 'variant': self.variant,
            'measurement_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
        journal, cached = super().claim(request, manifest)
        if journal is not None and self.inherited is not None:
            from psycopg.types.json import Jsonb
            with self.database.connection() as c, c.transaction():
                journal._lock(c)
                count = c.execute('SELECT count(*) AS n FROM support_agent_call WHERE run_id=%s',
                                  (request.run_id,)).fetchone()['n']
                if count:
                    raise ValueError('redo inheritance only allowed on an empty new evaluation run')
                c.execute('UPDATE support_agent_run SET spend_json=%s WHERE run_id=%s',
                          (Jsonb(self.inherited), request.run_id))
        if journal is not None and self.journal_factory is not None:
            journal = self.journal_factory(journal)
        return journal, cached


def run_turn(database, request, variant, model, *, journal_factory=None, inherited=None):
    records = []
    started = time.perf_counter()
    with source_client(request, records) as (client, index):
        def sources(bound, token, journal):
            return BoundSources(bound, token=token, case_url='http://synthetic.invalid', client=client,
                                index=index, journal=journal)
        runtime = SupportRuntime(database, DeploymentConfig(mode='live', provider='deepseek',
            model_id='deepseek-flash', endpoint=model.endpoint, context_window_tokens=32768),
            architecture='orchestrated-v1', model_factory=lambda: model, sources_factory=sources)
        def store(db):
            return EvaluationStore(db, variant=variant, journal_factory=journal_factory, inherited=inherited)
        with patch('resolveflow.support.service.SupportStore', store), patch(
            'resolveflow.support.service.SupportAgent', RawHistoryAgent if variant == 'raw' else SupportAgent
        ):
            result = runtime.run(request, 'synthetic-read-only')
    return {'result': result, 'facts': records, 'elapsed_ms': (time.perf_counter() - started) * 1000,
            'usage': usage_summary(model.records), 'models': model.records,
            'input': request.model_dump(mode='json'), 'transport_scope': model.transport_scope,
            'semantic_quality': None}


def mock_decision(packet):
    text = packet['current_request']
    if packet['stage']['phase'] == 'UNDERSTAND':
        return {'kind': 'TURN_UNDERSTANDING', 'focus': [{'id': 'q', 'intent': 'OTHER', 'request': '接线测试',
                    'needs': [], 'goal': 'EXPLAIN'}],
                'dialogue_events': [{'change': 'CONTINUE' if packet.get('previous_tasks') else 'ADD',
                                    'task_id': 'q', 'reference': 'CURRENT', 'quote': text}],
                'customer_claims': [{'topic': 'OTHER', 'reference': 'CURRENT', 'quote': text}]}
    return {'kind': 'RESPOND', 'parts': [{'task_id': 'q', 'text': '这是SSE脚本接线确认，不是语义评测答案。'}]}


def mock_provider(decide, *, received=None, usage=True):
    def provider(call):
        body = json.loads(call.content)
        if received is not None:
            received.append(body)
        packet = json.loads(body['messages'][-1]['content'])
        decision = json.dumps(decide(packet), ensure_ascii=False)
        events = []
        for start in range(0, len(decision), 11):
            events.append({'model': 'synthetic-sse-model', 'choices': [
                {'index': 0, 'delta': {'content': decision[start:start + 11]}}]})
        events.append({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
                       **({'usage': {'prompt_tokens': 100, 'completion_tokens': 30}} if usage else {})})
        text = ''.join('data: ' + json.dumps(e, ensure_ascii=False) + '\n\n' for e in events) + 'data: [DONE]\n\n'
        return httpx.Response(200, text=text, headers={'Content-Type': 'text/event-stream'})
    return provider


def context_matrix(database, *, output: Path, model_factory, limit: int):
    if output.exists():
        raise FileExistsError('never overwrite an existing context result')
    data = json.loads(DATA.read_text(encoding='utf-8'))
    validate_dataset(data)
    report = {'version': VERSION, 'state': 'RUNNING', 'rows': [], 'max_sends': limit, 'semantic_scores': None}
    write_new(output, report)
    allowance = SendAllowance(limit)
    for number, authored in enumerate(data['context_cases']):
        case = public_case(authored)
        for variant in VARIANTS if number % 2 == 0 else VARIANTS[::-1]:
            previous = None
            for index in (0, 1):
                row = {'case_id': authored['id'], 'variant': variant, 'checkpoint': index + 1,
                       'state': 'STARTED', 'models': []}
                report['rows'].append(row)
                save = lambda: persist(output, report)
                save()
                model = model_factory(allowance, row['models'], save)
                req = prepared_request(case, index, variant, previous=previous,
                                       deadline=datetime.now(UTC) + timedelta(seconds=120))
                value = run_turn(database, req, variant, model)
                row.update(value, state='COMPLETE')
                previous = value['result']
                save()
    report.update(state='FINISHED', sends=allowance.used)
    persist(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('offline',))
    parser.add_argument('--dsn', required=True)
    parser.add_argument('--schema', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.schema.startswith('t_hctx_'):
        raise ValueError('only pre-created evaluation schemas are accepted')
    def factory(allowance, records, save):
        model = MeasuredModel(endpoint='https://synthetic.invalid', provider='deepseek', model_id='deepseek-flash',
            stream_transport=httpx.MockTransport(mock_provider(mock_decision)), allowance=allowance, save=save,
            transport_scope='MOCK_SSE', parameters=PARAMETERS)
        model.records = records
        return model
    db = Database(args.dsn, schema=args.schema)
    try:
        context_matrix(db, output=args.output, model_factory=factory, limit=128)
    finally:
        db.close()


if __name__ == '__main__':
    main()
