"""Actual PG/SDK path; injected prefix distinct from the two scripted provider stand-ins."""

import json
import uuid

from scripts import customer_agent_acceptance_v1 as runner
from scripts.customer_agent_repair_probe_v1 import InjectedPrefix, prefix_for

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import GuideReads, read
from tests.unit.test_support_answer_parts import part, parts


class PreparedScript(TokenizedScript):
    def prepare_request(self, *, system, messages, max_output_tokens):
        return {'model': self.model_id, 'messages': [{'role': str(m.role), 'content': ''.join(
            b.text for b in m.get_content_blocks() if hasattr(b, 'text'))} for m in messages],
            'max_tokens': max_output_tokens}


def test_probe_prefix_reaches_real_harness_feedback_and_persists_source_bound_repair(agent_db):
    req, _ = runner.prepare_turn(runner.load_cases()[1], 0, [])
    req.run_id = str(uuid.uuid4())
    final = part('review', '可以先让商家协助核实。')
    final['next_steps'] = [{'action': 'MERCHANT_REVIEW', 'source': 'O1'}]
    provider = PreparedScript(mode='live', script=[read('get_support_guide'), parts(final)])
    injected = InjectedPrefix(provider, prefix_for(req), lambda records: None)
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture='staged-v1',
        model_factory=lambda: injected, sources_factory=lambda *args: GuideReads())
    result = runtime.run(req, 'local-test-token')
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert len(injected.injected) == 2 and provider.calls == 2
    assert result['spend']['model_calls'] == 4
    feedback = json.loads(provider.packets[0]['feedback'])
    assert feedback['resubmit'] == 'READ_THEN_FULL_ANSWER'
    assert '打开“售后咨询”' in result['answer']['text']
    with agent_db.connection() as c:
        calls = c.execute('SELECT response_json FROM support_agent_call WHERE run_id=%s AND kind=%s ORDER BY position',
                          (req.run_id, 'model')).fetchall()
        assert [c['response_json']['mode'] for c in calls] == ['mock', 'mock', 'live', 'live']
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    restored = InjectedPrefix(PreparedScript(mode='live', script=[]), prefix_for(req), lambda records: None)
    runtime.model_factory = lambda: restored
    assert runtime.run(req, 'local-test-token') == result
    assert restored.injected == [] and restored.delegate.calls == 0
