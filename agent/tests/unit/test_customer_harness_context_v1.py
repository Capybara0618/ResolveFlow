"""Evaluation preparation must not fabricate memory, scores or recovery success."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from scripts.evaluation.customer_harness_context_v1 import (
    RawHistoryAgent,
    build_dataset,
    checkpoint_request,
    public_case,
    validate_dataset,
)

from resolveflow.harness.context import canonical_json
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.token_counting import counter_for
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportFailure
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import Reads, answer


def deadline():
    return datetime.now(UTC) + timedelta(seconds=120)


def test_fixed_matrix_is_sixteen_conversations_and_fifteen_recovery_pairs():
    data = build_dataset()
    validate_dataset(data)
    assert len(data['context_cases']) == 16
    assert len(data['recovery_cases']) == 5
    assert len(data['recovery_windows']) == 3
    assert {c['family'] for c in data['context_cases']} == {'recall', 'correction', 'resume', 'no_repeat'}
    assert sum(len(c['checkpoints']) for c in data['context_cases']) * 2 == 64


def test_rubrics_never_enter_public_cases_or_requests_and_history_is_not_mutated():
    original = build_dataset()['context_cases'][0]
    case = public_case(original)
    assert 'rubrics' not in canonical_json(case)
    before = deepcopy(case)
    req = checkpoint_request(case, 0, 'layered', deadline=deadline())
    assert case == before
    assert 'rubrics' not in canonical_json(req.context)
    assert not any(key.startswith('previous_') for key in req.context)


def test_second_checkpoint_requires_real_prefix_and_never_seeds_state_from_labels():
    case = public_case(build_dataset()['context_cases'][0])
    with pytest.raises(ValueError, match='preceding result'):
        checkpoint_request(case, 1, 'layered', deadline=deadline())
    first = checkpoint_request(case, 0, 'layered', deadline=deadline())
    result = {'run_id': first.run_id, 'conversation_id': first.conversation_id,
              'input_version': first.input_version, 'status': 'FAILED', 'answer': None}
    req = checkpoint_request(case, 1, 'layered', deadline=deadline(), previous=result)
    assert not any(key.startswith('previous_') for key in req.context)
    assert all(m['author'] == 'CUSTOMER' or m.get('synthetic_background') is True
               for m in req.context['history'])
    foreign = {**result, 'run_id': '00000000-0000-4000-8000-000000000099'}
    with pytest.raises(ValueError, match='prefix identity'):
        checkpoint_request(case, 1, 'layered', deadline=deadline(), previous=foreign)


def test_raw_baseline_keeps_exact_newest_messages_and_uses_same_provider_budget():
    case = public_case(build_dataset()['context_cases'][-1])
    req = checkpoint_request(case, 0, 'raw', deadline=deadline())
    req.context['history'] = [dict(message_id=f'm{i}', sequence=i, author='CUSTOMER', recipient='ASSISTANT',
                                   text=f'背景{i}：' + '普通对话背景。' * 200) for i in range(1, 50)]
    req.input_version = 51
    before = deepcopy(req.context)
    agent = RawHistoryAgent(req, TokenizedScript(script=[]), Reads(), architecture='orchestrated-v1')
    packet = agent._packet()
    body, _ = agent._prepare(packet)
    assert counter_for(agent.model).count(body) + 256 <= agent.input_cap
    retained = packet['recent_messages']
    assert retained and retained[-1]['sequence'] == 49
    assert [m['sequence'] for m in retained] == list(range(retained[0]['sequence'], 50))
    assert all(m['text'] == before['history'][m['sequence'] - 1]['text'] for m in retained)
    assert packet['history_index'] == packet['history_read_refs'] == []
    assert req.context == before


def test_required_overflow_remains_failure_in_both_variants_without_model_calls():
    case = public_case(build_dataset()['context_cases'][0])
    req = checkpoint_request(case, 0, 'raw', deadline=deadline())
    req.context['current_request'] = '必须保留的当前诉求。' * 4000
    for cls in (SupportAgent, RawHistoryAgent):
        model = TokenizedScript(script=[])
        result = cls(req, model, Reads(), architecture='orchestrated-v1').run()
        assert result['reason'] == 'CONTEXT_REQUIRED_OVERFLOW'
        assert model.calls == 0


def test_baseline_does_not_change_single_sdk_execution_or_answer_checks():
    case = public_case(build_dataset()['context_cases'][0])
    req = checkpoint_request(case, 0, 'raw', deadline=deadline())
    # Scripted wiring only. These outputs do not demonstrate semantic memory quality.
    script = [{'kind': 'TURN_UNDERSTANDING', 'focus': [{'id': 'q', 'intent': 'OTHER',
               'request': '记录客户情况', 'needs': [], 'goal': 'EXPLAIN'}],
               'dialogue_events': [{'change': 'ADD', 'task_id': 'q', 'reference': 'CURRENT',
                                    'quote': req.context['current_request']}]},
              {'kind': 'RESPOND', 'parts': [{'task_id': 'q', 'text': '已记录你的情况。'}]}]
    model = TokenizedScript(script=script)
    result = RawHistoryAgent(req, model, Reads(), architecture='orchestrated-v1').run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert model.calls == 2


def test_dataset_tampering_and_unsupported_variants_fail_explicitly():
    data = build_dataset()
    data['context_cases'][0]['checkpoints'][0]['rubrics'] = []
    with pytest.raises(ValueError):
        validate_dataset(data)
    with pytest.raises(ValueError, match='variant'):
        checkpoint_request(public_case(build_dataset()['context_cases'][0]), 0, 'invented', deadline=deadline())


def test_raw_baseline_does_not_import_saved_structured_state():
    case = public_case(build_dataset()['context_cases'][0])
    req = checkpoint_request(case, 0, 'raw', deadline=deadline())
    req.context['previous_customer_memory'] = {'invalid': 'must not reach CustomerMemory'}
    req.context['previous_tasks'] = {'invalid': 'must not reach DialogueState'}
    before = deepcopy(req.context)
    agent = RawHistoryAgent(req, MockModelClient(script=[answer(citations=[])]), Reads())
    assert agent.memory.entries == []
    assert 'previous_customer_memory' not in agent.request.context
    assert req.context == before


def test_current_journal_unknown_model_response_is_not_a_reusable_result():
    from resolveflow.support.store import SupportJournal

    class Rows:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def transaction(self):
            return self

        def execute(self, sql, params):
            self.sql = sql
            return self

        def fetchone(self):
            if 'support_agent_call' not in self.sql:
                return {'spend_json': {}}
            import hashlib
            return {'request_hash': hashlib.sha256(canonical_json({'body': 'same'}).encode()).hexdigest(),
                    'status': self.status, 'response_json': {'saved': True}}

        def connection(self):
            return self

    journal = SupportJournal(Rows('STARTED'), 'synthetic-run', 2)
    with pytest.raises(SupportFailure, match='UNKNOWN_MODEL_RESULT'):
        journal.cached('model', 1, {'body': 'same'})
    assert SupportJournal(Rows('COMPLETE'), 'synthetic-run', 2).cached('model', 1, {'body': 'same'}) == {'saved': True}
