"""Standalone two-call customer workflow. No production Agent classes or prompts."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

VERSION = "basic-customer-workflow-v1"
PATHS = {"ORDER": ("ORDER",), "LOGISTICS": ("SHIPMENT",), "QUALITY": ("ORDER", "POLICY"),
    "POLICY": ("POLICY",), "REFUND": ("ORDER", "SHIPMENT", "POLICY"),
    "HANDOFF": (), "GUIDE": (), "OTHER": ()}

ROUTER_PROMPT = """你是商城售后客服的分类节点。根据本条消息和最近原始聊天记录，选择本轮主要意图。
ORDER=问订单或实付；LOGISTICS=查运输；QUALITY=商品故障；POLICY=问售后条件；
REFUND=要求准备退款原因或申请草稿；HANDOFF=要求商家核查或整理核查草稿；
GUIDE=问操作流程、隐私共享和进度；OTHER=普通交流或需要澄清。
每次只选择一个最能代表客户当前目的的意图；可以根据历史处理更正或回到之前的话题。
customer_description概括客户当前有效描述，不能写成系统已核验事实。
需要政策的意图同时用policy_query给出简洁查询问题；其他意图可为null。
只输出JSON：{"intent":"LOGISTICS","customer_description":"客户称未收到","policy_query":null}。
不要输出工具动作、事项列表、状态事件或最终回答。客户表达退款不等于已退款。
"""

ANSWER_PROMPT = """你是商城售后客服，现根据客户当前问题、原始聊天记录及本轮接口结果回答。
原始observations含使用指南和已查询的业务结果。客户说法未经核验，旧助手话语不证明当前事实。
物流签收不等于本人已收到，接口失败或未找到不证明丢失/不存在；没有依据的金额与政策不猜。
回答客户本轮要求，已有依据能支持的其他子问题也一起回答；没有读到的信息如实说明，必要时追问或建议人工。
可以按本轮明确要求整理退款或商家核查草稿，客户尚未确认，不能声称已经提交、转发、批准或退款。
草稿自行从当前及历史原文整理，采纳纠正，标明客户陈述和待确认；停止准备或只问流程时不附操作草稿。
只输出JSON：{"text":"给客户的回答","refund_summary":null,"handoff_summary":null}。
需要的草稿字段填文本，不需要的填null；可选citations填写实际观察的source_id。
本节点不再调用工具，不输出READ_TOOL、任务状态或对客户未公开的推理。
"""


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["ORDER", "LOGISTICS", "QUALITY", "POLICY", "REFUND", "HANDOFF", "GUIDE", "OTHER"]
    customer_description: str = Field(default="", max_length=1500)
    policy_query: str | None = Field(default=None, max_length=1000)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=12000)
    refund_summary: str | None = Field(default=None, max_length=6000)
    handoff_summary: str | None = Field(default=None, max_length=6000)
    citations: list[str] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True)
class ModelReply:
    text: str
    usage: dict | None = None
    mode: str = "UNKNOWN"
    first_text_ms: float | None = None


class WorkflowFailure(RuntimeError):
    pass


def run_turn(*, current_request, history, subject, model, read, timeout_seconds=120,
             max_model_calls=12, max_output_tokens=2048, on_record=None):
    """Injected model/source clients own transport; baseline stores no state across turns."""
    started = time.monotonic()
    result = {"version": VERSION, "status": "RUNNING", "answer": None, "route": None,
        "models": [], "tools": [], "first_body_ms": None, "first_body_scope": "NOT_MEASURED"}
    packet = {"current_request": current_request,
        "history": [{"role": m["role"], "content": m["content"]} for m in history[-20:]],
        "subject": {k: deepcopy(subject[k]) for k in ("merchant_id", "customer_id", "line_id", "product")
                    if k in subject}}

    def save():
        if on_record is not None:
            on_record(deepcopy(result))

    def check_deadline():
        if time.monotonic() - started >= timeout_seconds:
            raise WorkflowFailure("TIMEOUT")

    def observe(category, query=None):
        for attempt in range(2):
            check_deadline()
            record = {"category": category, "query": query, "attempt": attempt + 1,
                "source_id": "S" + str(len(result["tools"]) + 1)}
            result["tools"].append(record)
            save()
            at = time.monotonic()
            try:
                response = read(category, query=query)
            except TimeoutError:
                response = {"status_code": 504, "body": {"error": "TIMEOUT"}}
            record["elapsed_ms"] = (time.monotonic() - at) * 1000
            record["response"] = deepcopy(response)
            save()
            if not isinstance(response, dict) or not isinstance(response.get("status_code"), int):
                raise WorkflowFailure("INVALID_SOURCE_RESPONSE")
            if response["status_code"] not in {503, 504}:
                break

    def complete(stage, prompt, schema, value):
        messages = [{"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(value, ensure_ascii=False)}]
        for attempt in range(2):
            check_deadline()
            if len(result["models"]) >= max_model_calls:
                raise WorkflowFailure("BUDGET_EXHAUSTED")
            record = {"stage": stage, "messages": deepcopy(messages), "state": "STARTED", "usage": None}
            result["models"].append(record)
            save()
            at = time.monotonic()
            try:
                reply = model.complete(stage=stage, messages=deepcopy(messages), max_output_tokens=max_output_tokens)
            except Exception as error:
                record.update(state="ERROR", error_type=type(error).__name__,
                    elapsed_ms=(time.monotonic() - at) * 1000,
                    provider_sent=getattr(model, "last_sent", None),
                    body=deepcopy(getattr(model, "last_request", None)))
                save()
                if str(error) == "BUDGET_EXHAUSTED":
                    raise WorkflowFailure("BUDGET_EXHAUSTED") from None
                raise
            record.update(state="COMPLETE", raw_response=reply.text, usage=deepcopy(reply.usage), mode=reply.mode,
                elapsed_ms=(time.monotonic() - at) * 1000)
            record["provider_sent"] = getattr(model, "last_sent", None)
            record["body"] = deepcopy(getattr(model, "last_request", None))
            record["first_text_ms"] = reply.first_text_ms
            record["started_ms"] = (at - started) * 1000
            save()
            check_deadline()
            try:
                return schema.model_validate_json(reply.text)
            except ValidationError as error:
                record["format_error"] = str(error)[:1000]
                save()
                if attempt:
                    raise WorkflowFailure("INVALID_JSON_RESPONSE") from None
                # Same stage and same sources: format repair is not another investigation.
                messages += [{"role": "assistant", "content": reply.text}, {"role": "user", "content":
                    "JSON格式或字段不符合要求，请按原节点格式修正一次，不改变本节点职责。错误：" + str(error)[:1000]}]
        raise AssertionError("unreachable")

    try:
        observe("GUIDE")
        route = complete("ROUTE", ROUTER_PROMPT, Route, {**packet, "observations": deepcopy(result["tools"])})
        result["route"] = route.model_dump()
        save()
        for category in PATHS[route.intent]:
            query = None
            if category == "POLICY":
                query = (route.policy_query or route.customer_description or current_request).strip()
                if not query:
                    query = current_request
            observe(category, query)
        answer = complete("ANSWER", ANSWER_PROMPT, Answer, {**packet, "route": result["route"],
            "observations": deepcopy(result["tools"])})
        result.update(status="SUCCEEDED", answer=answer.model_dump(exclude_unset=True))
        retained = result["models"][-1]
        if answer.text.strip() and retained.get("first_text_ms") is not None:
            result.update(first_body_ms=retained["started_ms"] + retained["first_text_ms"],
                first_body_scope="SERVER_RETAINED_JSON_TEXT")
    except WorkflowFailure as error:
        reason = str(error)
        result.update(status=reason if reason in {"TIMEOUT", "BUDGET_EXHAUSTED"} else "FAILED", reason=reason)
    except Exception as error:  # noqa: BLE001 - retain client failures as failed runs without leaking credentials
        result.update(status="FAILED", reason="CLIENT_ERROR", error_type=type(error).__name__)
    finally:
        result["elapsed_ms"] = (time.monotonic() - started) * 1000
        save()
    return result
