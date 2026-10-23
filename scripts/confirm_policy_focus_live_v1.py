"""One explicit live turn on frozen synthetic history/facts and real pinned policy indexes."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'agent/src')]

import httpx
from customer_rag_diagnostic import ReadOnlyDatabase, snapshot
from resolveflow.harness.live_model import LiveModelClient
from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.policies.index import PolicyIndex
from resolveflow.runtime.db import Database, create_schema, drop_schema
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.embeddings import SupportEmbeddings
from resolveflow.support.protocol import SupportInput
from resolveflow.support.service import SupportRuntime
from resolveflow.support.sources import BoundSources
from resolveflow.support.stream_projection import AnswerProjection, ProjectionError

from scripts.agent_eval import allowance, persist
from scripts.evaluation.models import live_guard

OUT = ROOT / 'reports/customer-policy-focus-live-v1'
PLAN = ROOT / 'evals/customer-policy-focus-v1/live-plan.json'
DSN = 'postgresql://agent:agent@127.0.0.1:55433/agent_db'
MODEL_PATH = str(ROOT / 'tmp/c071-probe/models/BAAI--bge-small-zh-v1.5')
LEDGER = ROOT / 'tmp/evaluation-live-budget.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordedStreamingModel(StreamingLiveModelClient):
    def __init__(self, *, usage, limit, on_record, **kwargs):
        super().__init__(**kwargs)
        self.usage_ledger, self.limit, self.on_record = usage, limit, on_record
        self.records = []

    def decide(self, **kwargs):
        if len(self.records) >= self.limit:
            raise ValueError('explicit turn attempt bound reached')
        record = {'request': self.prepare_request(system=kwargs['system'], messages=kwargs['messages'],
                                                  max_output_tokens=kwargs['max_output_tokens'])}
        projection, deltas = AnswerProjection(), []
        started = time.perf_counter()

        def observe(fragment):
            try:
                for delta in projection.feed(fragment):
                    deltas.append({'elapsed_ms': (time.perf_counter()-started)*1000, **asdict(delta)})
            except ProjectionError:
                record['projection_error'] = True  # Full original validation/accounting still runs.

        self.on_content = observe
        self.records.append(record)
        self.usage_ledger['used'] += 1
        self.usage_ledger['save']()
        self.on_record(self.records)
        try:
            reply = LiveModelClient.decide(self, **kwargs)
            record.update(decision=reply.decision, usage=asdict(reply.usage), model_alias=reply.model_alias)
            return reply
        except Exception as error:  # Archive one attempted request; never retry here.
            record['error_type'] = type(error).__name__
            raise
        finally:
            record.update(elapsed_ms=(time.perf_counter()-started)*1000, stream=self.last_stream, deltas=deltas)
            self.on_record(self.records)


def build_fixture():
    plan = read(PLAN)
    archived = read(ROOT / plan['source'])
    saved = next(r['run'] for r in archived['runs'] if r['run']['run_id'] == plan['source_run'])
    assert saved['input_json']['context']['current_request'] == plan['user_question']
    shipment = next(c['response_json'][0]['data'] for c in archived['runs'][0]['calls']
                    if c['kind'] == 'tool' and c['request_json']['name'] == 'get_shipment_trace')
    old = read(ROOT / 'reports/chat-stream-live-v1/browser.json')
    conversation = next(o['event']['payload']['conversation'] for o in old['observations']
                        if o['type'] == 'event' and o['event']['kind'] == 'stream.snapshot')
    order = next(s['data'] for s in conversation['ticket']['report']['citations'] if s['source_type'] == 'ORDER')
    assert order['line_id'] == saved['input_json']['line_id']
    assert any(line['line_id'] == order['line_id'] for line in shipment['lines'])
    return {'original_input': saved['input_json'], 'generation_ids': saved['generations_json'],
            'order': order, 'shipment': shipment, 'facts_mode': 'frozen synthetic HTTP snapshots, not current business reads'}


def frozen_transport(request, fixture, bound, paths):
    path = request.url.path
    paths.append(path)
    assert bound.run_id in path, 'snapshot facade must remain run-bound'
    if path.endswith('/current'):
        return httpx.Response(200, json={'conversation_id': bound.conversation_id, 'input_version': bound.input_version})
    for suffix in ['order', 'shipment']:
        if path.endswith('/facts/' + suffix):
            return httpx.Response(200, json=fixture[suffix])
    if path.endswith('/facts/history'):
        before = int(request.url.params.get('before_sequence', str(bound.input_version + 1)))
        limit = int(request.url.params.get('limit', '5'))
        messages = [m for m in bound.context['history'] if m['sequence'] < before][-limit:]
        return httpx.Response(200, json={'messages': messages, 'version': bound.input_version})
    return httpx.Response(404)


def prepare():
    assert not (OUT / 'manifest.json').exists(), 'prepared input is immutable'
    fixture = build_fixture()
    db = ReadOnlyDatabase(DSN)
    try:
        policy = fixture['original_input']['context']['policy_manifest']
        ready = PolicyIndex(db).require_ready(policy['bundle_ids'], policy['manifest_hash'])
        assert {g.bundle_id: g.generation_id for g in ready} == fixture['generation_ids']
    finally:
        db.close()
    persist(OUT / 'input.json', fixture)
    files = [PLAN, Path(__file__).resolve(), OUT / 'input.json',
             ROOT / read(PLAN)['source'], ROOT / 'reports/chat-stream-live-v1/browser.json',
             *sorted((ROOT / 'agent/src/resolveflow/support').glob('*.py')),
             *[(ROOT / 'agent/src/resolveflow/harness' / name) for name in
               ['live_model.py', 'streaming_model.py', 'sdk_adapter.py', 'budget.py']],
             *[(ROOT / 'agent/src/resolveflow/policies' / name) for name in ['index.py', 'retrieval.py']]]
    persist(OUT / 'manifest.json', {'model_attempt_limit': 12, 'turns': 1, 'force_sub_queries': False,
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'files': {p.relative_to(ROOT).as_posix(): digest(p) for p in files}})
    print('Prepared one frozen turn, matching original generation; new models: 0')


def execute():
    output = OUT / 'runtime-results.json'
    assert not output.exists(), 'an attempted turn is never automatically rerun'
    manifest = read(OUT / 'manifest.json')
    for path, fingerprint in manifest['files'].items():
        assert digest(ROOT / path) == fingerprint, 'frozen execution source/input changed'
    key = os.environ.get('RESOLVEFLOW_MODEL_API_KEY', '').strip()
    assert key, 'model key is required in the process environment'
    fixture = read(OUT / 'input.json')
    resources = SupportEmbeddings()
    warmup = resources.prewarm(MODEL_PATH)
    schema = 't_policy_focus_' + uuid.uuid4().hex[:16]
    retained, db = ReadOnlyDatabase(DSN), Database(DSN, schema=schema)
    created = exported = False
    report = {'state': 'PREPARING', 'manifest_sha256': digest(OUT / 'manifest.json'), 'synthetic_data': True,
              'facts_mode': fixture['facts_mode'], 'source_commit': subprocess.check_output(
                  ['git', 'rev-parse', 'HEAD'], text=True).strip(), 'schema': schema, 'warmup_ms': warmup,
              'models': [], 'paths': [], 'not_resume_metrics': True}
    persist(output, report)
    try:
        report['public_before'] = snapshot(retained)
        create_schema(DSN, schema)
        created = True
        db.migrations()
        original = fixture['original_input']
        req = SupportInput.model_validate({**original, 'run_id': str(uuid.uuid4()),
            'deadline_at': (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)).isoformat()})
        report['input'] = req.model_dump(mode='json')
        config = DeploymentConfig(mode='live', provider='deepseek', endpoint='https://api.deepseek.com/chat/completions',
            model_id='deepseek-flash', api_key=key, policy_index=True, embedding_path=MODEL_PATH, context_window_tokens=32768)
        with live_guard(LEDGER):
            usage = allowance(LEDGER)
            report['ledger_before'] = usage['used']

            def save(records):
                report['models'] = records
                persist(output, report)

            model = RecordedStreamingModel(usage=usage, limit=manifest['model_attempt_limit'], on_record=save,
                endpoint=config.endpoint, model_id=config.model_id, provider=config.provider, api_key=key,
                parameters={'thinking': {'type': 'disabled'}, 'response_format': {'type': 'json_object'}, 'temperature': 0})
            with httpx.Client(transport=httpx.MockTransport(
                    lambda call: frozen_transport(call, fixture, req, report['paths']))) as client:

                def sources(bound, token, journal):
                    journal.pin_generations(fixture['generation_ids'])
                    return BoundSources(bound, case_url='http://frozen-case.local', token=token,
                        index=PolicyIndex(retained), embedder=resources.get(MODEL_PATH), journal=journal, client=client)

                runtime = SupportRuntime(db, config, architecture='staged-v1', embeddings=resources,
                                         model_factory=lambda: model, sources_factory=sources)
                report['state'] = 'RUNNING'
                persist(output, report)
                started = time.perf_counter()
                try:
                    report['result'] = runtime.run(req, 'frozen-snapshot-read-token')
                finally:
                    report.update(elapsed_ms=(time.perf_counter()-started)*1000, ledger_after=usage['used'],
                                  transport_requests=len(model.requests))
                    with db.connection() as connection:
                        report['run'] = connection.execute('SELECT * FROM support_agent_run WHERE run_id=%s',
                                                           (req.run_id,)).fetchone()
                        report['calls'] = connection.execute('SELECT * FROM support_agent_call WHERE run_id=%s '
                            'ORDER BY created_at,kind,position', (req.run_id,)).fetchall()
                    exported = True
                    persist(output, report)
        report['public_after'] = snapshot(retained)
        assert report['public_after'] == report['public_before'], 'retained public data changed'
        report['public_data_unchanged'] = True
        report['state'] = 'FINISHED'
    except Exception as error:  # Retain every attempted turn, no automatic restart.
        report.update(state='FAILED', error_type=type(error).__name__)
        raise
    finally:
        db.close()
        retained.close()
        if created and exported:
            drop_schema(DSN, schema)
            report['temporary_schema_removed'] = True
        persist(output, report)
    print(json.dumps({'state': report['state'], 'status': report['result']['status'],
                      'models': report['transport_requests'], 'ledger_after': report['ledger_after']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'execute'])
    args = parser.parse_args()
    prepare() if args.command == 'prepare' else execute()
