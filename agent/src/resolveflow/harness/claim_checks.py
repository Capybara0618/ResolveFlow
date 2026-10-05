"""Finite high-risk assertion checks, not a general natural-language truth judge.

Only explicit supported templates are recognized. Customer claims, questions,
conditions and negations are not promoted to verified system facts.
"""

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from resolveflow.contracts.core_models import ToolObservation

# Match assertion spans, so a recommendation in a different clause cannot hide a fact.
ASSERTIONS = (
    (re.compile(r"(?:承运商|物流)(?:已)?(?:确认|判定)(?:为|已)?(?:正常)?(?:签收|送达)"
                r"|carrier confirmed delivery", re.I),
     "get_shipment_trace", "carrier_conclusion", {"DELIVERED", "SIGNED"}),
    (re.compile(r"(?:承运商|物流)(?:已)?(?:确认|判定)(?:为)?(?:丢失|遗失)|carrier confirmed lost", re.I),
     "get_shipment_trace", "carrier_conclusion", {"LOST"}),
    (re.compile(r"(?:订单|商品)(?:当前|目前|已经|已)?(?:明确)?未发货|order (?:is |was )?not shipped", re.I),
     "get_order_context", "fulfillment_status", {"NOT_SHIPPED"}),
    (re.compile(r"(?:订单|商品)(?:已经|已)(?:签收|送达)|order (?:is |was )delivered", re.I),
     "get_order_context", "fulfillment_status", {"DELIVERED"}),
    (re.compile(r"退款(?:已经|已)(?:到账|成功|完成)|refund (?:has |is |was )?(?:completed|successful)", re.I),
     "get_refund_status", "state", {"SUCCEEDED"}),
)
QUALIFIER = re.compile(r"未确认|没有确认|尚未|并未|并非|不能确认|不代表|未证明|无法确认|是否|若|如果|假设|"
                       r"客户(?:称|说|表示|声称)|买家(?:称|说|表示)|待核实|可能|据称|"
                       r"\b(?:not|if|whether|may|might|customer says|buyer says)\b", re.I)
PAID_AMOUNT = re.compile(r"(?P<scope>订单行|商品行|本行|整单|订单)?实付(?:金额)?(?:为|是|：|:)?"
                         r"\s*[¥￥]?\s*(?P<amount>\d+(?:\.\d{1,2})?)\s*元")


def unsupported_claims(*, summary: str, findings: Sequence[Mapping[str, Any]],
                       evidence_refs: Sequence[Mapping[str, Any]],
                       observations: Sequence[ToolObservation]) -> list[str]:
    refs = {r.get("observation_id") for r in evidence_refs}
    latest: dict[str, ToolObservation] = {}
    # A newer failure invalidates the prior successful read for an asserted current fact.
    for item in observations:
        latest[item.tool_name] = item
    texts = [(summary, refs), *((str(f.get("text", "")), refs.intersection(f.get("observation_ids", [])))
                              for f in findings)]
    failures: list[str] = []
    for text, cited_ids in texts:
        for clause in re.split(r"[。；;\n!?！？]|(?<!\d)\.|\.(?!\d)|，|,|但|\bbut\b", text):
            for pattern, tool, key, allowed in ASSERTIONS:
                match = pattern.search(clause)
                if not match or QUALIFIER.search(clause[:match.start()]):
                    continue
                obs = latest.get(tool)
                body = obs.result if obs and isinstance(obs.result, Mapping) else {}
                # Legacy shipment observations used conclusion; it is still a pinned source value.
                value = body.get(key, body.get("conclusion") if key == "carrier_conclusion" else None)
                if not obs or obs.error or obs.observation_id not in cited_ids or value not in allowed:
                    failures.append(f"{tool}.{key}: assertion requires cited value {'/'.join(sorted(allowed))}; "
                                    "source missing, failed, uncited or inconsistent")
            amount = PAID_AMOUNT.search(clause)
            if amount and not QUALIFIER.search(clause[:amount.end()]):
                obs = latest.get("get_order_context")
                body = obs.result if obs and isinstance(obs.result, Mapping) else {}
                claimed = int(Decimal(amount.group("amount")) * 100)
                key = "order_paid_amount" if amount.group("scope") in {"订单", "整单"} else "line_paid_amount"
                if (not obs or obs.error or obs.observation_id not in cited_ids
                        or body.get(key) != claimed):
                    failures.append(f"get_order_context.{key}: stated yuan amount must equal "
                                    "the cited current integer minor-unit payment; correct the amount or hand over")
    return list(dict.fromkeys(failures))
