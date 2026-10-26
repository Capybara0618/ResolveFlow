"""Local-only preparation for context/recovery measurements; no live model entry point."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from resolveflow.harness.model import MockModelClient
from resolveflow.harness.token_counting import counter_for
from resolveflow.support.context import history_messages
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import SupportInput

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'customer-harness-context-v1'
DATA = ROOT / 'evals' / VERSION / 'cases.json'
REPORT = ROOT / 'reports' / VERSION / 'preparation.json'
NAMESPACE = uuid.UUID('429a85b1-5fe0-46b7-8e1b-d9b68363c49b')
VARIANTS = ('raw', 'layered')
RECOVERY_WINDOWS = ('model_returned_not_saved', 'model_saved', 'business_tool_saved')

# Author-created statements and externally observable rubrics. None are extracted state.
SEEDS = {
    'recall': [
        ('耳机', '外包装完好，但左耳没有声音，右耳正常。请帮我看看该怎么处理。',
         '继续刚才的问题，请概括具体故障和包装情况。',
         '说明左耳无声、右耳正常及外包装完好；不把自述当检测结论。'),
        ('台灯', '灯罩上有一道裂纹，底座和开关正常，拆箱时我拍了照片。请问下一步怎么办？',
         '准备联系商家了，请整理之前说过的损坏部位和已有材料。',
         '说明灯罩裂纹、底座开关正常、已有拆箱照片；不虚构照片已上传。'),
        ('背包', '背包拉链卡住了，布料没有破损。我还留着吊牌，希望先咨询怎么处理。',
         '回到背包问题，我说过哪些具体情况？先咨询，不要替我提交申请。',
         '说明拉链卡住、布料完好、吊牌保留，不声称申请已提交。'),
        ('保温杯', '杯盖拧紧后仍会漏水，杯身没有磕碰，开箱视频我保存在手机里。请问怎么处理？',
         '继续处理这个杯子，请整理故障表现和我已有的证据。',
         '说明拧紧仍漏水、杯身无磕碰及手机留有视频；不虚构检测/上传。'),
    ],
    'correction': [
        ('耳机', '更正之前的话：我刚问过家人，他们没有代收，包裹还是没找到。请继续帮我核查。',
         '继续刚才的签收争议，请说明最新排查结论。',
         '采用家人未代收、仍未找到的最新客户陈述，不沿用可能代收，也不认定承运商确认丢失。'),
        ('台灯', '更正一下，不是灯罩坏了，是底座开关失灵，灯罩完好。请按这个情况继续处理。',
         '回到台灯问题，现在究竟是哪里出了问题？',
         '采用开关失灵、灯罩完好，不继续按灯罩破损处理。'),
        ('背包', '纠正一下，我已经找到吊牌了，商品没使用过，只是买错颜色。请先帮我了解退货条件。',
         '继续之前的退货咨询，我现在的商品情况和原因是什么？',
         '采用吊牌已找到、未使用、买错颜色，不沿用吊牌丢失；资格仍按政策。'),
        ('保温杯', '之前说漏水是我没把杯盖拧好。现在不漏了，我只是觉得容量小，想先咨询退货条件。',
         '继续杯子的咨询，现在是什么退货原因？',
         '采用容量不合适，不将已纠正的漏水继续当质量故障；不承诺必退。'),
    ],
    'resume': [
        ('耳机', '包裹显示签收但我没收到，想请商家核查。先插问：在哪里能查看咨询进度？这个问题之后继续。',
         '入口我知道了，继续之前没处理完的事情，帮我整理交给商家核查的内容。',
         '恢复签收未收到的核查事项，生成相关核查内容，不能当成退款申请或声称已转交。'),
        ('台灯', '台灯开关失灵，想请商家判断怎么处理。先插问：需要补充材料时在哪里发？原问题稍后继续。',
         '材料入口明白了，回到刚才的问题，帮我整理给商家看的情况。',
         '恢复开关失灵核查，整理商家可看的问题；不把入口问答当作全部事项已解决。'),
        ('背包', '拉链卡住了，想请商家核查。先问一下：售后处理进度在哪里看？这个故障之后继续说。',
         '继续刚才那个没处理完的问题，请给我一份核查摘要。',
         '恢复拉链故障核查并给核查摘要，不虚构提交或退款。'),
        ('保温杯', '杯盖缺少密封圈，想让商家核查。先插问：我在哪里能补充照片？这个问题后面继续。',
         '照片入口清楚了，回到原问题，请整理核查内容。',
         '恢复缺少密封圈的核查事项，不把插问当成原问题完成。'),
    ],
    'no_repeat': [
        ('耳机', '家人、门卫和快递柜我都问过了，没有找到包裹。请接着帮我核查。',
         '继续吧，我已经说过的排查不用再让我做一遍。',
         '使用家人/门卫/快递柜均排查未找到的信息，不重复要求这三项排查；不直接认定丢失。'),
        ('台灯', '我换过两个能正常使用的插座，也重新插紧电源了，灯还是不亮。请问下一步怎么办？',
         '接着处理台灯问题，已经试过的操作就不用再问了。',
         '承接换插座、重插电源无效，不重复将两项作为尚未做的必要排查。'),
        ('背包', '订单详情和包裹标签上的颜色我都核对过了，确实发错颜色，照片我也已经拍好。请帮我看怎么处理。',
         '继续处理，刚才核对过的内容不要再让我重复核对了。',
         '承接订单/标签颜色已核对及已有照片，不虚构照片已上传，不重复相同排查。'),
        ('保温杯', '我清洗并重新装好了杯盖密封圈，换冷水试过，还是漏水。请问下一步怎么处理？',
         '继续杯子的问题，不用再让我重复之前的排查。',
         '承接清洗/重装密封圈及冷水测试仍漏水，不重复要求相同排查；不虚构检测结论。'),
    ],
}
OLD_STATEMENTS = [
    '家人可能代收了，我还没确认。', '灯罩好像坏了，我还没看清楚。',
    '吊牌可能丢了，我还没仔细找。', '杯子好像漏水，原因还不清楚。',
]
BACKGROUND = [
    ('暂时不用处理刚才的问题。我想整理一下商品资料：页面展示的颜色、规格和配件清单，我已经保存了截图。'
     '这些只是我浏览页面的记录，不是新的故障、收货结论或退款申请，原来的问题之后再继续。'),
    ('补充一段购物记录：我当时比较过几个款式，也看过尺寸和使用说明。这里没有新的物流信息、检测报告或费用结论，'
     '也不改变之前说过的情况。这个消息只作普通聊天背景，稍后我还会继续原来的问题。'),
    ('我正在整理手机里的购物截图和说明书，想把商品介绍、外观图片和规格参数分别放好。'
     '这里只是整理资料，没有确认收货、没有修改先前的排查结果，也没有要求创建售后申请。'),
]


def message(sequence: int, text: str, author: str = 'CUSTOMER', *, background: bool = False) -> dict[str, Any]:
    return {'message_id': f'synthetic-message-{sequence}', 'sequence': sequence, 'author': author,
            'recipient': 'ASSISTANT' if author == 'CUSTOMER' else 'CUSTOMER', 'text': text,
            **({'synthetic_background': True} if background else {})}


def build_dataset() -> dict[str, Any]:
    cases = []
    for family, seeds in SEEDS.items():
        for index, (product, first, second, rubric) in enumerate(seeds):
            initial = ([message(1, OLD_STATEMENTS[index]),
                        message(2, '先保留你的初步描述，尚未取得权威核验结果。', 'ASSISTANT')]
                       if family == 'correction' else [])
            # Four fixed lengths within every family; no adjustment after observing model scores.
            pairs = (0, 8, 24, 48)[index]
            background = []
            for n in range(pairs):
                text = f'资料整理记录第{n + 1}条。' + BACKGROUND[n % len(BACKGROUND)]
                background.extend([{'author': 'CUSTOMER', 'text': text},
                                   {'author': 'ASSISTANT', 'text': '这条消息已保留为购物背景记录。'}])
            cases.append({'id': f'{family}-{index + 1:02d}', 'family': family,
                          'product': product, 'initial_history': initial, 'background': background,
                          'checkpoints': [
                              {'text': first, 'rubrics': ['正确回应当前诉求；不虚构已执行操作或权威结论。',
                                                       '陈述和事项更新只能来自可定位客户原文。']},
                              {'text': second, 'rubrics': [rubric,
                                  '不能以再次询问已明确给出的关键背景来替代本轮处理。']}]})
    recover = [
        ('shipment', '包裹显示签收但我没收到，请帮我查一下物流记录。', 'SHIPMENT'),
        ('policy', '签收争议时，需要什么材料才能申请退款？', 'POLICY'),
        ('application', '商品已付款但还没发货，我想退款，请准备申请摘要。', 'ORDER'),
        ('compound', '请查订单和物流，并说明签收争议适用的退款政策。', 'SHIPMENT'),
        ('handoff', '家人和代收点都问过了没找到，想请商家核查，请整理核查内容。', 'SHIPMENT'),
    ]
    return {'version': VERSION, 'synthetic': True, 'not_holdout': True,
            'label_author': 'CODEX_SOURCE_REVIEW',
            'context_cases': cases, 'recovery_windows': list(RECOVERY_WINDOWS),
            'recovery_cases': [{'id': key, 'text': text, 'business_fault_source': source}
                               for key, text, source in recover],
            'scope': 'mechanism-level synthetic checkpoints, not full long-conversation customer success'}


def validate_dataset(data: dict[str, Any]) -> None:
    cases = data['context_cases']
    if (data['version'] != VERSION or len(cases) != 16 or len({c['id'] for c in cases}) != 16
            or Counter(c['family'] for c in cases) != Counter({k: 4 for k in SEEDS})
            or data['recovery_windows'] != list(RECOVERY_WINDOWS)
            or len(data['recovery_cases']) != 5):
        raise ValueError('dataset matrix changed')
    for case in cases:
        if len(case['checkpoints']) != 2 or any(not c['text'] or not c['rubrics'] for c in case['checkpoints']):
            raise ValueError('every checkpoint needs observable rubrics')
        if any(key.startswith('previous_') for key in case):
            raise ValueError('derived state cannot be authored into raw cases')
    if data != build_dataset():
        raise ValueError('raw material differs from fixed authored dataset')


def public_case(case: dict[str, Any]) -> dict[str, Any]:
    return {k: deepcopy(case[k]) for k in ('id', 'product', 'initial_history', 'background')} | {
        'checkpoints': [{'text': c['text']} for c in case['checkpoints']]}


def identity(case: dict[str, Any], variant: str, index: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f'{VERSION}:{case["id"]}:{variant}:{index}'))


def checkpoint_request(
    case: dict[str, Any], index: int, variant: str, *, deadline: datetime,
    previous: dict[str, Any] | None = None,
) -> SupportInput:
    if variant not in VARIANTS:
        raise ValueError('unknown variant')
    if index not in (0, 1):
        raise ValueError('unknown checkpoint')
    history = deepcopy(case['initial_history'])
    first_sequence = len(history) + 1
    history.append(message(first_sequence, case['checkpoints'][0]['text']))
    context: dict[str, Any] = {'product': {'name': case['product']}, 'policy_manifest': None,
                               'conversation_state': {'has_ticket': False}}
    conversation = identity(case, variant, -1)
    if index == 1:
        if previous is None:
            raise ValueError('second checkpoint requires preceding result')
        if any(previous.get(k) != v for k, v in {'run_id': identity(case, variant, 0),
                'conversation_id': conversation, 'input_version': first_sequence}.items()):
            raise ValueError('prefix identity mismatch')
        answer = previous.get('answer') if previous['status'] == 'SUCCEEDED' else None
        if answer:
            text = '\n\n'.join(answer[k] for k in ('text', 'refund_summary', 'handoff_summary')
                               if isinstance(answer.get(k), str) and answer[k])
            history.append(message(len(history) + 1, text, 'ASSISTANT'))
        for row in case['background']:
            history.append(message(len(history) + 1, row['text'], row['author'], background=True))
        history.append(message(len(history) + 1, case['checkpoints'][1]['text']))
        # Same accepted-state rule as the current Java/Python adapter; no rubric-derived state.
        state = previous.get('conversation_update') or answer
        if state and variant == 'layered':
            memory = state.get('customer_memory')
            if memory is not None:
                if any(memory.get(k) != v for k, v in {'conversation_id': conversation, 'merchant_id': 'M-EVAL',
                        'customer_id': 'C-EVAL', 'line_id': 'line-' + case['id'],
                        'input_version': first_sequence}.items()):
                    raise ValueError('accepted memory scope mismatch')
                context['previous_customer_memory'] = deepcopy(memory)
            tasks = state.get('task_state') or {}
            if tasks.get('origin') == 'MODEL' and isinstance(tasks.get('tasks'), list) and tasks['tasks']:
                context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': first_sequence,
                                             'tasks': deepcopy(tasks['tasks'])}
    context.update(current_request=case['checkpoints'][index]['text'], history=history)
    return SupportInput(run_id=identity(case, variant, index), conversation_id=conversation,
                        input_version=history[-1]['sequence'], merchant_id='M-EVAL', customer_id='C-EVAL',
                        line_id='line-' + case['id'], deadline_at=deadline, context=context)


class RawHistoryAgent(SupportAgent):
    """Evaluation-only context ablation over the unchanged production SDK and safeguards."""

    def __init__(self, request: SupportInput, *args: Any, **kwargs: Any) -> None:
        context = {k: deepcopy(v) for k, v in request.context.items() if not k.startswith('previous_')}
        super().__init__(request.model_copy(update={'context': context}), *args, **kwargs)

    def _packet(self, recent: int = 4, preview: int = 80, index_limit: int = 20) -> dict[str, Any]:
        del recent, preview, index_limit
        packet = super()._packet(0, 0, 0)
        history = [m for m in history_messages(self.request, self.observations)
                   if m['sequence'] != self.request.input_version]
        packet.update(recent_messages=[deepcopy(m) | {'read_ref': 'H' + str(m['sequence']),
            'authority': {'CUSTOMER': 'CUSTOMER_STATEMENT', 'ASSISTANT': 'HISTORICAL_ASSISTANT_OUTPUT',
                          'MERCHANT': 'MERCHANT_STATEMENT'}.get(m['author'], 'HISTORICAL_MESSAGE')}
                                       for m in history], history_index=[], history_read_refs=[])
        packet['context_layout'] = {'version': 'evaluation-raw-oldest-drop-v1',
                                   'total_messages': len(history), 'dropped_messages': 0}
        # Account the actual phase-specific provider body, keeping all nonhistory constraints intact.
        counter = counter_for(self.model)
        while packet['recent_messages']:
            body, _ = self._prepare(packet)
            if counter.count(body) + 256 <= self.input_cap:
                break
            packet['recent_messages'].pop(0)
            packet['context_layout']['dropped_messages'] += 1
        return packet


class ScriptedModel(MockModelClient):
    provider = 'deepseek'
    model_id = 'deepseek-flash'


class GuideOnlySources:
    def read(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != 'get_support_guide' or arguments:
            raise AssertionError('offline wiring smoke may only use the local guide')
        return guide_source()


def mock_matrix(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Exercise all 64 SDK turns and accepted-state flow, without assigning semantic scores."""
    rows = []
    for authored in data['context_cases']:
        case = public_case(authored)
        for variant in VARIANTS:
            previous = None
            for index in (0, 1):
                req = checkpoint_request(case, index, variant,
                                         deadline=datetime.now(UTC) + timedelta(seconds=120), previous=previous)
                text = req.context['current_request']
                model = ScriptedModel(script=[{
                    'kind': 'TURN_UNDERSTANDING', 'focus': [{'id': 'q', 'intent': 'OTHER',
                        'request': '本地脚本接线确认', 'needs': [], 'goal': 'EXPLAIN'}],
                    'dialogue_events': [{'change': 'CONTINUE' if req.context.get('previous_tasks') else 'ADD',
                                         'task_id': 'q', 'reference': 'CURRENT', 'quote': text}],
                    'customer_claims': [{'topic': 'OTHER', 'reference': 'CURRENT', 'quote': text}]},
                    {'kind': 'RESPOND', 'parts': [{'task_id': 'q', 'text': '脚本接线确认，仅用于检查执行和状态传递。'}]}])
                cls = RawHistoryAgent if variant == 'raw' else SupportAgent
                agent = cls(req, model, GuideOnlySources(), architecture='orchestrated-v1', provider_capacity=32768)
                previous = agent.run()
                if previous['status'] != 'SUCCEEDED':
                    raise ValueError(f'{case["id"]}/{variant}/{index}: {previous["reason"]}')
                rows.append({'case_id': case['id'], 'variant': variant, 'checkpoint': index + 1,
                             'scripted_status': previous['status'], 'model_calls': model.calls,
                             'estimated_input_tokens': previous['spend']['input_tokens'],
                             'semantic_quality': None, 'provider_usage': None,
                             'inherited_customer_memory': 'previous_customer_memory' in req.context})
    return rows


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.write('\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'check'))
    args = parser.parse_args()
    if args.command == 'prepare':
        data = build_dataset()
        validate_dataset(data)
        if DATA.exists() or REPORT.exists():
            raise FileExistsError('preparation output exists; use check, never overwrite evidence')
        rows = mock_matrix(data)
        write_new(DATA, data)
        paths = [Path(__file__), ROOT / 'agent/tests/unit/test_customer_harness_context_v1.py',
                 ROOT / 'docs/customer-harness-context-v1.md', DATA]
        paths.extend(sorted((ROOT / 'agent/src/resolveflow/support').glob('*.py')))
        paths.extend(sorted((ROOT / 'agent/src/resolveflow/harness').glob('*.py')))
        paths.extend([ROOT / 'agent/uv.lock', ROOT / 'agent/src/resolveflow/assets/deepseek-v41/tokenizer.json.gz'])
        hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        write_new(REPORT, {'state': 'LOCAL_PREPARATION_ONLY', 'version': VERSION, 'hashes': hashes,
                           'context_answer_turns_planned': 64, 'recovery_pairs_planned': 15,
                           'mock_sdk_rows': rows, 'live_requests': 0,
                           'business_database_operations': 0, 'real_crash_runs': 0,
                           'quality_metrics': None, 'provider_usage_metrics': None,
                           'recovery_driver_ready': False, 'live_context_driver_ready': False})
        print('Prepared 16 raw cases / 64 scripted SDK turns. No live scores or real crash results.')
    else:
        validate_dataset(json.loads(DATA.read_text(encoding='utf-8')))
        report = json.loads(REPORT.read_text(encoding='utf-8'))
        for name, digest in report['hashes'].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                raise ValueError('preparation file changed: ' + name)
        print('Raw cases and preparation hashes verified; no execution performed.')


if __name__ == '__main__':
    main()
