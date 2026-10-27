"""An accepted application answer can offer a reason, but never create or authorize a refund."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from resolveflow.support.guidance import decision_feedback
from resolveflow.support.protocol import DECISION
from resolveflow.support.stages import INVESTIGATION_SYSTEM
from tests.unit.test_support_agent import GuideReads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_staged import staged, understand


def recorded_invalid_summaries():
    root = Path(__file__).resolve().parents[3]
    report = json.loads((root / 'agent/tests/fixtures/regressions/chat-refund-live-v1/runtime-results.json').read_text(encoding='utf-8'))
    return [c['response_json']['decision'] for r in report['support_runs'] if r['status'] == 'FAILED'
            for c in r['calls'] if c['kind'] == 'model' and c['position'] in {6, 7}]


@pytest.mark.parametrize('payload', recorded_invalid_summaries())
def test_saved_live_summary_errors_get_precise_root_string_repair_without_coercion(payload):
    before = deepcopy(payload)
    with pytest.raises(ValidationError) as error:
        DECISION.validate_python(payload)
    feedback = json.loads(decision_feedback(error.value, payload, ['O1', 'O2', 'O3', 'P2']))
    assert feedback['field'] == 'refund_summary'
    assert feedback['location'] == 'ROOT' and feedback['type'] == 'string'
    assert feedback['max_length'] == 2000
    example = DECISION.validate_python(feedback['example'])
    assert example.refund_summary and example.parts[0].task_id == 't2'
    assert example.parts[0].next_steps[0].source == 'O3'
    assert 'refund_summary' not in example.parts[0].model_dump()
    assert payload == before


def test_actual_investigation_prompt_has_a_valid_root_string_summary_example():
    examples = [json.loads(line) for line in INVESTIGATION_SYSTEM.splitlines()
                if line.startswith('{"kind":"ANSWER_PARTS"') and 'refund_summary' in line]
    assert len(examples) == 1
    assert DECISION.validate_python(examples[0]).refund_summary


@pytest.mark.parametrize('bad', recorded_invalid_summaries())
def test_saved_live_summary_shape_can_use_only_one_existing_repair(bad):
    req = request()
    good = parts({**part('trace', '请核对申请原因后确认。', ['O1']),
                  'next_steps': [{'action': 'REFUND_APPLICATION', 'source': 'O1'}]})
    good['refund_summary'] = '客户陈述：未收到商品。诉求：申请整件退款，待本人核对提交。'
    opening = understand(req, intent='APPLICATION', needs=['GUIDE'])
    result, model, sources, agent = staged(req, [opening, read('get_support_guide'), bad, good], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['refund_summary'] == good['refund_summary']
    assert json.loads(model.packets[-1]['feedback'])['field'] == 'refund_summary'
    assert agent.repairs == 1 and model.calls == 4 and len(sources.calls) == 1
    failed, model, _, agent = staged(req, [opening, read('get_support_guide'), bad, bad], GuideReads())
    assert failed['status'] == 'FAILED' and failed['answer'] is None
    assert agent.repairs == 1 and model.calls == 4


def test_application_summary_survives_publication_without_an_extra_model_round():
    req = request()
    value = parts({**part('trace', '可核对申请摘要后自行确认。', ['O1']),
                   'next_steps': [{'action': 'REFUND_APPLICATION', 'source': 'O1'}]})
    value['refund_summary'] = '客户反馈商品未收到，希望核实签收后退款。'
    result, model, sources, _ = staged(req, [understand(req, intent='APPLICATION', needs=['GUIDE']),
        read('get_support_guide'), value], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['refund_summary'] == value['refund_summary']
    assert result['answer']['handoff_summary'] is None
    assert model.calls == 3 and sources.calls == [('get_support_guide', {})]
    assert '确认提交申请' in result['answer']['text']


def test_unselected_application_summary_is_rejected_then_repaired_not_silently_published():
    req = request()
    bad = {**parts(part('trace', '先核实情况。')), 'refund_summary': '请立即退款'}
    result, model, sources, agent = staged(req, [understand(req, intent='OTHER', needs=[]),
        bad, parts(part('trace', '请补充你需要了解的问题。'))], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert 'refund_summary' not in result['answer']
    assert model.calls == 3 and agent.repairs == 1 and sources.calls == []


def test_invalid_application_result_never_exposes_a_summary():
    req = request()
    bad = {**parts(part('trace', '先核实情况。')), 'refund_summary': '请立即退款'}
    result, _, _, _ = staged(req, [understand(req, intent='OTHER', needs=[]), bad, bad], GuideReads())
    assert result['status'] == 'FAILED' and result['answer'] is None
