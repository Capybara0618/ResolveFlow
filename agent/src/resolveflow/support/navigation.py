"""Render two stable application instructions from an observed controlled guide; never execute them."""

from __future__ import annotations

from typing import Any

from resolveflow.support.grounding import GroundingError
from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import Answer, AnswerParts

PAGE_LABELS = ('售后咨询', '我的售后')
INSTRUCTIONS = {
    'MERCHANT_REVIEW': '人工核查：打开“售后咨询”，选择对应订单商品，点击“请商家核查”。'
                       '预览并编辑核查摘要，选择要共享的原文和调查依据，确认后才转交商家。'
                       '私有对话不会默认全部共享；此操作不需要填写退款金额，也不会自动提交退款申请。',
    'REFUND_APPLICATION': '正式退款：打开“我的售后”，选择对应订单商品，核对申请内容后自行提交。'
                          '聊天表达退款意愿或转交人工核查不会自动创建退款工单；助手没有替你提交申请。',
}


class NavigationError(GroundingError):
    pass


class NavigationSourceError(NavigationError):
    pass


def render_navigation(
    decision: Answer | AnswerParts, citations: dict[str, dict[str, Any]], *, strict: bool = False,
    required: dict[str, str] | None = None,
) -> Answer | AnswerParts:
    trusted = guide_source()
    rendered = []
    for piece in decision.parts if isinstance(decision, AnswerParts) else [decision]:
        if strict and any(label in piece.text for label in PAGE_LABELS):
            raise NavigationError('固定页面入口由程序生成；解释段不写页面名，改用next_steps。')
        actions = [step.action for step in piece.next_steps]
        if len(actions) != len(set(actions)):
            raise NavigationError('同一段next_steps.action不可重复。')
        expected = (required or {}).get(getattr(piece, 'task_id', ''))
        status = getattr(piece, 'status', 'ANSWERED')
        if expected and status in {'ANSWERED', 'NEEDS_MERCHANT'} and expected not in actions:
            raise NavigationError(f'当前事项须选择next_steps.action={expected}，并引用本run指南。')
        if actions and status not in {'ANSWERED', 'NEEDS_MERCHANT'}:
            raise NavigationError('暂停、取消、未完成或来源失败段不能附带办理步骤。')
        text, refs = piece.text, list(piece.citations)
        for step in piece.next_steps:
            source = citations.get(step.source, {})
            if (source.get('source_type') != 'KNOWLEDGE' or source.get('version') != trusted['version']
                    or source.get('data') != trusted['data'] or 'error' in source):
                raise NavigationSourceError('next_steps.source须实际读取的当前受控get_support_guide来源。')
            text += '\n\n' + INSTRUCTIONS[step.action]
            if step.source not in refs:
                refs.append(step.source)
        if len(text) > 4000 or len(refs) > 8:
            raise NavigationError('生成步骤后仍须满足4000字符和8引用限制。')
        rendered.append(piece.model_copy(update={'text': text, 'citations': refs, 'next_steps': []}))
    if isinstance(decision, AnswerParts):
        return decision.model_copy(update={'parts': rendered})
    single = rendered[0]
    assert isinstance(single, Answer)
    return single
