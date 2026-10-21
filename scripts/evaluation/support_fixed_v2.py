"""Evaluation-only fixed scheduling over the actual support context, gates and journal. No production loop."""

from resolveflow.harness.budget import RunBudget
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.store import SupportStore


class FixedSupportAgent(SupportAgent):
    phase = "QUERY"

    def _packet(self, *args, **kwargs):
        packet = super()._packet(*args, **kwargs)
        packet["fixed_stage"] = self.phase
        packet["fixed_instruction"] = (
            "评测固定流程QUERY阶段：仅输出SEARCH_POLICY，生成结合当前对话的本店政策query，top_k=3。"
            "同次标注当前tasks/变化与必要客户陈述。接下来程序固定读取订单、物流、指南并检索。"
            if self.phase == "QUERY" else
            "评测固定流程ANSWER阶段：固定读取已完成，只输出ANSWER，不追加任何工具或检索。"
            "按现有依据回答全部问题、缺信息则说明，任务引用与回答相符。"
        )
        return packet

    def ask(self, kind):
        for _ in range(2):
            decision = self.decide().decision
            if decision.get("tool_name") == "__support_feedback":
                continue
            if decision.get("kind") != kind:
                self.final = None
                raise SupportFailure("FIXED_" + self.phase + "_REQUIRED")
            return decision
        raise SupportFailure("INVALID_DECISION")

    async def _drive(self):
        query = self.ask("SEARCH_POLICY")
        for name in ["get_order_context", "get_shipment_trace", "get_support_guide"]:
            for _ in range(2):
                observed = self.execute(name, {})
                if not any(o.get("retryable") for o in observed if "error" in o):
                    break
        self.execute("search_policy", {"query": query["query"], "top_k": 3})
        self.phase = "ANSWER"
        self.ask("ANSWER")


class FixedSupportRuntime:
    """Same request/result API and store, but explicitly pinned evaluation scheduling."""

    def __init__(self, database, runtime, sources_factory, plan_sha256):
        self.database, self.runtime = database, runtime
        self.sources_factory, self.plan_sha256 = sources_factory, plan_sha256

    def run(self, request, token):
        from dataclasses import asdict

        manifest = {"version": "support-fixed-eval-v2", "plan_sha256": self.plan_sha256,
                    "budget": asdict(RunBudget()), "provider_capacity": self.runtime.config.context_window_tokens}
        journal, cached = SupportStore(self.database).claim(request, manifest)
        if cached is not None:
            return cached
        model = self.runtime._model()
        sources = self.sources_factory(request, token, journal)
        try:
            result = FixedSupportAgent(request, model, sources, journal=journal,
                                       provider_capacity=self.runtime.config.context_window_tokens).run()
            journal.finish(result)
            return result
        finally:
            sources.close()
