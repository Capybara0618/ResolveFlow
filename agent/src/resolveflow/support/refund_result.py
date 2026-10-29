"""Buyer refund receipts from the current Java projection; no model-authored next step."""

from typing import Any

from resolveflow.support.grounding import GroundingError, value_for
from resolveflow.support.protocol import SupportInput

VERSION = "buyer-refund-result-v1"


def render_refund_result(source: dict[str, Any], request: SupportInput) -> str:
    message = value_for("REFUND_STATUS", source, request)
    application = source["data"]["refund_application"]
    status = application.get("status")
    if status == "NONE":
        return "当前还没有提交退款申请。聊天中咨询或准备原因，不会自动提交申请。"
    if status == "CLOSED_SUCCESS":
        try:
            amount = value_for("REFUNDED_AMOUNT", source, request).removesuffix(" CNY") + "元"
            return f"这笔模拟退款已完成，金额{amount}，你不需要再操作。本次不涉及真实资金到账。"
        except GroundingError:
            return "这笔模拟退款已完成，退款金额暂时无法确认。本次不涉及真实资金到账。"
    next_step = {
        "QUEUED": "暂时不需要操作，有进展会在申请记录中更新。",
        "ANALYZING": "暂时不需要操作，有进展会在申请记录中更新。",
        "PENDING_REVIEW": "你可以在申请记录中查看最新进展。",
        "WAITING_CUSTOMER": "请到申请详情查看需要补充的说明。",
        "AUTHORIZED": "批准还不代表退款完成，请等待申请记录更新。",
        "EXECUTING": "请等待结果，不需要重复申请。",
        "RECONCILING": "目前还不能确认是否完成，请勿重复申请。",
        "CLOSED_REJECTED": "你可以在申请详情查看商家的处理说明。",
        "CANCELLED": "本次申请已结束，处理记录仍可查看。",
    }.get(status)
    if next_step is None:
        raise GroundingError("未知退款状态不能生成确定性结果。")
    return f"{message}。{next_step}"
