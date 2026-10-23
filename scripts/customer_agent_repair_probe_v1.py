"""Clearly separate two scripted prefix decisions from provider-generated repair and answer."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from resolveflow.harness.model import ModelReply, ModelUsage

from scripts import customer_agent_acceptance_v1 as acceptance

prior = acceptance.prior


def prefix_for(req):
    return [
        {'kind': 'TURN_UNDERSTANDING', 'focus': [{'id': 'review', 'intent': 'HANDOFF',
            'request': '了解独立人工核查及共享方式', 'needs': ['GUIDE']}],
            'dialogue_events': [{'change': 'ADD', 'task_ids': ['review'], 'reference': 'CURRENT',
                                'quote': req.context['current_request']}], 'customer_claims': []},
        {'kind': 'ANSWER_PARTS', 'parts': [{'task_id': 'review', 'status': 'ANSWERED',
            'text': '可以先让商家协助核实。', 'next_steps': [{'action': 'MERCHANT_REVIEW', 'source': 'O1'}]}]},
    ]


class InjectedPrefix:
    def __init__(self, delegate, script, save):
        self.delegate, self.script, self.save = delegate, script, save
        self.injected = []

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def decide(self, **kwargs):
        if len(self.injected) < len(self.script):
            decision = self.script[len(self.injected)]
            usage = ModelUsage(estimated=True)
            self.injected.append({'origin': 'SCRIPTED_FAULT_INJECTION', 'mode': 'mock',
                'body': self.delegate.prepare_request(system=kwargs['system'], messages=kwargs['messages'],
                                                     max_output_tokens=kwargs['max_output_tokens']),
                'decision': decision, 'usage': asdict(usage)})
            self.save(self.injected)
            return ModelReply(decision, usage, mode='mock', model_alias='injected-navigation-prefix')
        return self.delegate.decide(**kwargs)


def evaluate_probe(output: Path, usage_path: Path):
    import httpx
    from fastapi.testclient import TestClient
    from resolveflow.api.app import create_app
    from resolveflow.api.identity import mint_service_token
    from resolveflow.runtime.db import Database, create_schema, drop_schema
    from resolveflow.runtime.factory import DeploymentConfig
    from resolveflow.support.service import SupportRuntime

    from scripts.agent_eval import allowance
    from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot
    from scripts.evaluation.models import live_guard

    acceptance.load_plan()
    key = (os.getenv('RESOLVEFLOW_MODEL_API_KEY') or os.getenv('Deepseek_API_KEY') or '').strip()
    if not key:
        raise ValueError('missing model key')
    case = acceptance.load_cases()[1]
    req, archive = acceptance.prepare_turn(case, 0, [])
    report = {'version': acceptance.VERSION, 'plan_sha256': prior.digest(acceptance.PLAN),
        'mode': 'injected-prefix-live-repair', 'synthetic_facts': True, 'not_resume_metrics': True,
        'state': 'PREPARING', 'input': req.model_dump(mode='json'), 'injected': [], 'models': [],
        'tools': [], 'paths': []}
    prior.write_new(output, report)
    schema = 't_support_acceptance_probe_' + uuid.uuid4().hex[:12]
    private = acceptance.ROOT / 'tmp' / acceptance.VERSION / schema
    private.mkdir(parents=True, exist_ok=False)
    prior.write_new(private / 'ownership.json', {'schema': schema, 'report': str(output.resolve())})
    retained, db = ReadOnlyDatabase(prior.DSN), Database(prior.DSN, schema=schema)
    created, exported = False, False
    try:
        report['public_before'] = snapshot(retained)
        create_schema(prior.DSN, schema)
        created = True
        db.migrations()
        config = DeploymentConfig(mode='live', provider='deepseek', model_id='deepseek-flash',
            endpoint='https://api.deepseek.com/chat/completions', api_key=key)
        runtime = SupportRuntime(db, config, architecture='staged-v1')

        def save(name, records):
            report[name] = records
            prior.persist(output, report)

        with live_guard(usage_path):
            usage = allowance(usage_path)
            report.update(state='RUNNING', usage_before=usage['used'])
            model = prior.RecordedModel(runtime._model(), usage, lambda records: save('models', records))
            wrapper = InjectedPrefix(model, prefix_for(req), lambda records: save('injected', records))
            runtime.model_factory = lambda: wrapper
            with httpx.Client(transport=httpx.MockTransport(
                    prior.upstream_for(case['snapshot'], req, archive, report['paths']))) as upstream:
                runtime.sources_factory = lambda bound, token, journal: prior.MeasuredSources(
                    bound, case_url='http://frozen-case.local', token=token, journal=journal,
                    client=upstream, records=report['tools'])
                app = create_app(provider_db=private / 'provider.sqlite3', delivery_loop=False,
                    worker_loop=False, migrate=False, jwt_secret=prior.SECRET, support_runtime=runtime)
                # This guide-only probe does not require or claim a second embedding warmup.
                old_prewarm = os.environ.pop('RESOLVEFLOW_SUPPORT_PREWARM', None)
                try:
                    with TestClient(app) as api:
                        token = mint_service_token('case-service', prior.SECRET, scope='support:run',
                            merchant_id=req.merchant_id, customer_id=req.customer_id)
                        started = time.perf_counter()
                        response = api.post('/internal/v1/support-runs',
                            headers={'Authorization': 'Bearer ' + token},
                            json={**req.model_dump(mode='json'), 'tool_token': 'frozen-read-token'})
                        report.update(http_status=response.status_code, result=response.json(),
                                      elapsed_ms=(time.perf_counter() - started) * 1000)
                finally:
                    if old_prewarm is not None:
                        os.environ['RESOLVEFLOW_SUPPORT_PREWARM'] = old_prewarm
            report['usage_after'] = usage['used']
        report['public_after'] = snapshot(retained)
        if report['public_before'] != report['public_after']:
            raise ValueError('retained public data changed')
        report['state'] = 'FINISHED'
    except Exception as error:
        report.update(state='ERROR', error_type=type(error).__name__)
        raise
    finally:
        try:
            if created:
                with db.connection() as c:
                    report['all_runs'] = c.execute('SELECT * FROM support_agent_run ORDER BY run_id').fetchall()
                    report['all_calls'] = c.execute(
                        'SELECT * FROM support_agent_call ORDER BY run_id,kind,position').fetchall()
            prior.persist(output, report)
            exported = True
        finally:
            db.close()
            if created and exported:
                drop_schema(prior.DSN, schema)
            retained.close()
        report['isolated_schema_dropped'] = created and exported
        prior.persist(output, report)
    print({'probe': 'R01', 'status': report.get('result', {}).get('status'),
           'injected_decisions': len(report['injected']), 'provider_requests': len(report['models'])}, flush=True)
