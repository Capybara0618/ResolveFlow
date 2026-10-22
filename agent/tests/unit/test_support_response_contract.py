"""Validate the actual publication example and policy/guide separation in sent requests."""

import json
import re

import pytest

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import DECISION
from tests.unit.test_support_agent import Reads, answer, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


def test_sent_publication_example_includes_initial_tasks_and_current_source_events():
    req = request()
    model = MockModelClient(script=[answer(citations=[])])
    assert SupportAgent(req, model, Reads()).run()['status'] == 'SUCCEEDED'
    system = ''.join(b.text for b in model.conversations[0][0].get_content_blocks() if hasattr(b, 'text'))
    examples = [json.loads(line) for line in re.findall(r'^\{"kind":.*\}$', system, re.MULTILINE)]
    example = next(e for e in examples if e['kind'] == 'ANSWER_PARTS')
    assert example['tasks'][0]['id'] == example['parts'][0]['task_id']
    assert example['dialogue_events'][0]['task_ids'] == [example['tasks'][0]['id']]
    assert example['dialogue_events'][0]['reference'] == 'CURRENT'
    example['dialogue_events'][0]['quote'] = req.context['current_request']
    DECISION.validate_python(example)
    live = MockModelClient(mode='live', script=[read(), example])
    assert SupportAgent(req, live, Reads()).run()['status'] == 'SUCCEEDED'
    assert live.calls == 2 and live.packets[1]['feedback'] is None


def test_sent_contract_assigns_application_flow_to_guide_not_eligibility_policy():
    model = MockModelClient(script=[answer(citations=[])])
    SupportAgent(request(), model, Reads()).run()
    system = ''.join(b.text for b in model.conversations[0][0].get_content_blocks() if hasattr(b, 'text'))
    assert '入口/操作须读get_support_guide' in system
    assert '政策不能证明页面流程' in system
    catalog = model.packets[0]['capabilities']
    assert '无法读取' in catalog['get_support_guide']['purpose']
    assert '入口' in catalog['search_policy']['purpose']


class ApplicationSources(Reads):
    def read(self, name, arguments):
        if name == 'get_support_guide':
            self.calls.append((name, arguments))
            return guide_source()
        return super().read(name, arguments)


@pytest.mark.parametrize('utterance,response', [
    ('资料准备好了，下一步到哪里提交？', '正式退款申请入口为我的售后。'),
    ('只找商家问一下，也要先填写退多少钱吗？', '请商家核查前预览摘要并确认，无需填写退款金额。'),
    ('我选几句话给商家看，其余对话能保留吗？', '客户原文与调查依据分别勾选，仅确认共享的内容发给商家。'),
])
def test_guide_only_variants_publish_with_real_guide_source_and_no_policy_request(utterance, response):
    req = request()
    req.context['current_request'] = utterance
    final = parts(part('entry', response, ['O1']),
                  tasks=[task('entry', 'APPLICATION')],
                  dialogue_events=[group('ADD', ['entry'], utterance)])
    sources = ApplicationSources()
    model = MockModelClient(mode='live', script=[read('get_support_guide'), final])
    result = SupportAgent(req, model, sources).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert sources.calls == [('get_support_guide', {})] and model.calls == 2
    citation = result['answer']['citations'][0]
    assert citation['source_type'] == 'KNOWLEDGE' and citation['data']['authority'] == 'APPLICATION_GUIDE'
    assert model.packets[1]['task_state']['tasks'] == []
