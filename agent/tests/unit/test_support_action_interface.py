"""Reproduce saved live protocol friction without changing the saved outputs."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from resolveflow.support.dialogue import DialogueState
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import DECISION, SupportInput
from resolveflow.support.tasks import render_answer

from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import Reads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_issue_retention import saved
from tests.unit.test_support_tasks import task


def test_actual_resolve_with_cancelled_outcome_derives_one_canonical_closed_state():
    row = saved(4)
    payload = deepcopy(row['models'][0]['decision'])
    req = SupportInput.model_validate(row['input'])
    req = req.model_copy(update={'deadline_at': request().deadline_at})  # Offline probe, not the historical run.
    result = SupportAgent(req, TokenizedScript(mode='live', script=[payload]), Reads()).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    value = next(t for t in result['answer']['task_state']['tasks'] if t['id'] == 't3')
    assert value['lifecycle'] == 'RESOLVED' and value['status'] == 'ANSWERED'
    assert row['models'][0]['decision'] == payload


@pytest.mark.parametrize('change,expected', [('PAUSE', 'SUSPENDED'), ('CANCEL', 'CANCELLED'),
                                          ('RESOLVE', 'ANSWERED')])
def test_explicit_event_derives_display_outcome_without_duplicate_status_control(change, expected):
    req = request(input_version=3)
    req.context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': 1,
                                    'tasks': [task('trace', status='ANSWERED')]}
    payload = parts(part('trace', '已记录本轮变化。'), tasks=[task('trace')],
                    dialogue_events=[group(change, ['trace'], req.context['current_request'])])
    model = TokenizedScript(mode='live', script=[payload])
    result = SupportAgent(req, model, Reads()).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['task_state']['tasks'][0]['status'] == expected
    assert model.calls == 1


def test_purpose_is_nonexecuting_metadata_but_foreign_arguments_and_other_unknown_keys_still_fail():
    req = request()
    payload = {**read(), 'purpose': '查询实时运输状态'}
    original = deepcopy(payload)
    final = parts(part('trace', '已读取运输记录。', ['O1']), tasks=[task('trace')],
                  dialogue_events=[group('ADD', ['trace'], req.context['current_request'])])
    sources = Reads()
    result = SupportAgent(req, TokenizedScript(mode='live', script=[payload, final]), sources).run()
    assert result['status'] == 'SUCCEEDED' and sources.calls == [('get_shipment_trace', {})]
    assert payload == original
    for bad in [{**payload, 'execute_refund': True}, {**payload, 'arguments': {'line_id': 'foreign'}},
                {**payload, 'purpose': 'x' * 201}]:
        with pytest.raises(ValidationError):
            DECISION.validate_python(bad)


def test_non_current_quote_still_cannot_close_issue():
    row = saved(4)
    value = deepcopy(row['models'][0]['decision'])
    value['dialogue_events'][0]['reference'] = 'H1'
    parsed = render_answer(DECISION.validate_python(value), [])
    state = DialogueState(SupportInput.model_validate(row['input']))
    before = deepcopy(state.packet())
    with pytest.raises(ValueError):
        state.apply(parsed.dialogue_events, parsed.tasks, [], require=True)
    assert state.packet() == before
