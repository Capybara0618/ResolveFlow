"""Evaluation-only fixed full investigation; common production meaning/grounding/journal."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

from resolveflow.harness.context import canonical_json
from resolveflow.harness.sdk_adapter import messenger_message, raw_text_message
from resolveflow.support import service
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.store import SupportStore

VERSION = "fixed-full-investigation-current-v1"
QUERY_SYSTEM = """固定全量调查的政策Query生成阶段，理解/记忆已接受，订单与物流固定读取完成。
结合current_request、stage.focus及实际观察生成本店政策query；不要把客户假设当真实事实。
只输出单JSON：{"kind":"READ_TOOL","tool_name":"search_policy","arguments":{"query":"实际场景的政策条件问题","top_k":3}}。
即使是流程问题也生成相关政策query，固定流程不能跳过该步。不要重声明事项/记忆、回答或选择其他工具。
"""


class FixedFullInvestigation(SupportAgent):
    fixed_phase = "UNDERSTAND"

    def _prepare(self, packet):
        if self.fixed_phase != "QUERY":
            return super()._prepare(packet)
        messages = [raw_text_message(QUERY_SYSTEM, role="system"), messenger_message(packet)]
        prepare = getattr(self.model, "prepare_request", None)
        body = prepare(system="", messages=messages, max_output_tokens=self.budget.step_output_tokens) if prepare else {
            "messages": [{"role": "system", "content": QUERY_SYSTEM},
                         {"role": "user", "content": canonical_json(packet)}],
            "max_output_tokens": self.budget.step_output_tokens}
        return body, messages

    async def _drive(self):
        # Deterministic evaluation controller only; the production SDK loop is unchanged.
        self.execute("get_support_guide", {})
        while self.stage.pending:
            decision = self.decide().decision
            if decision.get("tool_name") not in {"__support_feedback", "__support_stage_ready"}:
                raise SupportFailure("FIXED_UNDERSTANDING_REQUIRED")
        for tool in ("get_order_context", "get_shipment_trace"):
            self.execute(tool, {})
        self.fixed_phase = "QUERY"
        while True:
            decision = self.decide().decision
            if decision.get("tool_name") == "__support_feedback":
                continue
            if decision.get("kind") != "READ_TOOL" or decision.get("tool_name") != "search_policy":
                self.final = None
                raise SupportFailure("FIXED_POLICY_QUERY_REQUIRED")
            self.execute("search_policy", decision["arguments"])
            break
        self.fixed_phase = "COMPOSE"
        while self.final is None:
            decision = self.decide().decision
            if self.final is not None:
                break
            if decision.get("tool_name") not in {"__support_feedback", "__support_stage_ready"}:
                raise SupportFailure("FIXED_NO_ADDITIONAL_INVESTIGATION")
            # Genuine goal review/format repair can continue, but no new source actions.


class FixedStore(SupportStore):
    def claim(self, request, manifest):
        manifest = {**manifest, "evaluation_controller": VERSION,
                    "fixed_controller_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        return super().claim(request, manifest)


class FixedCurrentRuntime(service.SupportRuntime):
    def run(self, request, token, *, progress_token=None):
        # Evaluation runner is sequential; patch scope cannot affect separate business processes.
        with patch.multiple(service, SupportAgent=FixedFullInvestigation, SupportStore=FixedStore):
            return super().run(request, token, progress_token=progress_token)
