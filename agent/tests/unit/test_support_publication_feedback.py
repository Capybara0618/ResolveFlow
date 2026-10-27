"""Saved read-first publication failure must request both declaration and source events."""

import json
from copy import deepcopy
from pathlib import Path

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from tests.unit.test_support_agent import Reads, read, request
from tests.unit.test_support_event_groups import group


def decisions():
    root = Path(__file__).resolve().parents[3]
    report = json.loads((root / 'agent/tests/fixtures/regressions/customer-agent-read-first-v1/runtime-results.json').read_text(
        encoding='utf-8'))
    return deepcopy(report['rows'][0]['models'][1]['decision']), deepcopy(report['rows'][0]['models'][2]['decision'])


def test_missing_first_declaration_gets_tasks_and_events_feedback_and_repairs_in_one_call():
    req = request()
    incomplete, corrected = decisions()
    corrected['dialogue_events'] = [group('ADD', ['t1'], req.context['current_request'])]
    original = deepcopy(incomplete)
    model = MockModelClient(mode='live', script=[read(), incomplete, corrected])
    sources = Reads()
    result = SupportAgent(req, model, sources).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    feedback = json.loads(model.packets[2]['feedback'])
    assert feedback['issue'] == 'TASKS_REQUIRED' and feedback['field'] == 'tasks'
    assert feedback['required_on_answer'] == ['tasks', 'dialogue_events']
    assert 'dialogue_events' in feedback['repair_note']
    assert incomplete == original and sources.calls == [('get_shipment_trace', {})]
    assert model.packets[2]['task_state']['tasks'] == [] and model.calls == 3


def test_saved_partial_fix_that_still_omits_events_remains_rejected():
    incomplete, corrected_without_events = decisions()
    sources = Reads()
    model = MockModelClient(mode='live', script=[read(), incomplete, corrected_without_events])
    result = SupportAgent(request(), model, sources).run()
    assert result['reason'] == 'INVALID_DECISION' and result['answer'] is None
    assert sources.calls == [('get_shipment_trace', {})] and model.calls == 3
