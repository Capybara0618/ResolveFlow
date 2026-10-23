"""Render two stable application instructions from an observed controlled guide; never execute them."""

from __future__ import annotations

import re
from typing import Any

from resolveflow.support.grounding import GroundingError
from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import Answer, AnswerPart, AnswerParts

PAGE_LABELS = ('售后咨询', '我的售后')
PAGE_ACTIONS = {'售后咨询': {'MERCHANT_REVIEW', 'REFUND_APPLICATION'}, '我的售后': {'REFUND_APPLICATION'}}
DIRECT_CROSSED_ROUTES = (
    r'我的售后[”」"\']?(?:页面)?[中里内的]?\s*[，,:：→-]*\s*(?:点击|选择|使用)\s*[“「"\']?请商家核查',
)
INSTRUCTIONS = {
    'MERCHANT_REVIEW': '人工核查：打开“售后咨询”，选择对应订单商品，点击“请商家核查”。'
                       '预览并编辑核查摘要，选择要共享的原文和调查依据，确认后才转交商家。'
                       '私有对话不会默认全部共享；此操作不需要填写退款金额，也不会自动提交退款申请。',
    'REFUND_APPLICATION': '正式退款：在当前会话点击“申请退款”，核对整行实付金额和申请原因，可编辑后点击“确认提交申请”。'
                          '提交后在当前会话查看进度，也可到“我的售后”查看同一笔申请详情和补充材料。'
                          '聊天表达退款意愿或转交人工核查不会自动创建退款工单；助手没有替你提交申请。',
}
EXISTING_REVIEW = ('人工咨询：当前已有商家核查记录。在当前会话选择“补充给商家”，'
                   '填写本次要咨询或补充的内容，点击“发送”，消息会进入原核查单。'
                   '已解决的核查单也可通过再次补充接续，无需重新转交。'
                   '只会共享本次发给商家的内容，私有助手对话不会自动全部共享；'
                   '此操作不会自动提交退款申请。')


class NavigationError(GroundingError):
    pass


class NavigationSourceError(NavigationError):
    pass


def navigation_references(decision: Answer | AnswerParts, citations: dict[str, dict[str, Any]]) -> Answer | AnswerParts:
    """Merge only observed guide references; also usable for metadata-only rejection diagnostics."""
    trusted = guide_source()

    def references(piece: Answer | AnswerPart) -> list[str]:
        refs = list(piece.citations)
        for step in piece.next_steps:
            source = citations.get(step.source, {})
            if (source.get('source_type') != 'KNOWLEDGE' or source.get('version') != trusted['version']
                    or source.get('data') != trusted['data'] or 'error' in source):
                raise NavigationSourceError('next_steps.source须实际读取的当前受控get_support_guide来源。')
            if step.source not in refs:
                refs.append(step.source)
        return refs

    if isinstance(decision, AnswerParts):
        return decision.model_copy(update={'parts': [p.model_copy(update={'citations': references(p)})
                                                     for p in decision.parts]})
    return decision.model_copy(update={'citations': references(decision)})


def render_navigation(
    decision: Answer | AnswerParts, citations: dict[str, dict[str, Any]], *, strict: bool = False,
    required: dict[str, str] | None = None,
    conversation_state: dict[str, Any] | None = None,
) -> Answer | AnswerParts:
    decision = navigation_references(decision, citations)
    rendered = []
    for piece in decision.parts if isinstance(decision, AnswerParts) else [decision]:
        actions = [step.action for step in piece.next_steps]
        if strict:
            for label in PAGE_LABELS:
                if label in piece.text and not PAGE_ACTIONS[label].intersection(actions):
                    choices = sorted(PAGE_ACTIONS[label])
                    raise NavigationError(f'页面“{label}”须对应next_steps.action={choices}及本run指南。')
            # Finite direct UI pairs, not a general classifier of prose or negation.
            if any(re.search(pattern, piece.text) for pattern in DIRECT_CROSSED_ROUTES):
                raise NavigationError('页面与直接操作错配：请商家核查须在售后咨询；退款可在当前会话确认。')
        if len(actions) != len(set(actions)):
            raise NavigationError('同一段next_steps.action不可重复。')
        expected = (required or {}).get(getattr(piece, 'task_id', ''))
        status = getattr(piece, 'status', 'ANSWERED')
        if expected and status in {'ANSWERED', 'NEEDS_MERCHANT'} and expected not in actions:
            raise NavigationError(f'当前事项须选择next_steps.action={expected}，并引用本run指南。')
        if actions and status not in {'ANSWERED', 'NEEDS_MERCHANT'}:
            raise NavigationError('暂停、取消、未完成或来源失败段不能附带办理步骤。')
        # Java freezes this state with the input. It is not inferred from customer/model prose.
        existing_ticket = (conversation_state or {}).get('has_ticket') is True
        # Pure application guidance is program-owned. Do not append the same route to a model's
        # free-form version of it. Mixed investigation/fact explanations remain intact.
        guide_only = (expected is not None and len(actions) == 1 and actions[0] == expected
                      and set(piece.citations) <= {step.source for step in piece.next_steps})
        text, refs = ('' if guide_only else piece.text), list(piece.citations)
        for step in piece.next_steps:
            instruction = (EXISTING_REVIEW if existing_ticket and step.action == 'MERCHANT_REVIEW'
                           else INSTRUCTIONS[step.action])
            text += ('\n\n' if text else '') + instruction
        if len(text) > 4000 or len(refs) > 8:
            raise NavigationError('生成步骤后仍须满足4000字符和8引用限制。')
        rendered.append(piece.model_copy(update={'text': text, 'citations': refs, 'next_steps': []}))
    if isinstance(decision, AnswerParts):
        return decision.model_copy(update={'parts': rendered})
    single = rendered[0]
    assert isinstance(single, Answer)
    return single
