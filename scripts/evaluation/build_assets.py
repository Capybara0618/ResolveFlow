"""Author v1 synthetic assets. Run only to create a new version, never during evaluation."""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.evaluation.dataset import DATA, ROOT, validate  # noqa: E402

RULES = [
    (
        "R-UNSHIPPED-001",
        "付款后尚未发货",
        "商品已付款，商家履约记录明确尚未发货，且没有退款占用时，可以申请该商品行全部数量的实付全额退款。"
        "买错规格、重复购买或改变购买计划均可提出申请。不能用没有物流记录代替尚未发货的确认；已经发货时应调查其他理由。",
    ),
    (
        "R-LOST-001",
        "运输丢失",
        "承运记录确认包裹丢失、没有有效签收记录，且商家已核验丢失事实时，可以建议该商品行实付全额退款。"
        "只有运输延迟、普通在途或客户单方声称没有收到，不足以确认丢失。签收和丢失记录冲突时先核验。",
    ),
    (
        "R-SIGNED-001",
        "签收争议",
        "物流显示有效签收但客户说没收到，应核对签收人与客户说明，缺少关键说明时补证或转人工。"
        "不能仅凭签收状态确认客户实际收货，也不能仅凭未收到的主张建议退款。"
        "若人工核验确认错误签收且承运记录已确认丢失，按运输丢失条款继续判断。",
    ),
    (
        "R-DMG-001",
        "商品质量或破损",
        "商品发货后存在损坏或功能质量问题，人工核验确认问题属实并符合售后条件时，可以建议该商品行实付全额退款。"
        "未经核验的客户陈述或一张已上传的图片不能自动证明问题；核验结果未知或材料相互矛盾时补证或转人工。"
        "核验否认某项事实仅否认该理由，不能代替对其他有效理由的调查。",
    ),
    (
        "R-INTRANSIT-001",
        "运输中与延迟",
        "普通运输中或配送变慢不等于丢失。应查看承运异常及客户理由，不能套用尚未发货退款条款。"
        "没有异常结论或存在其他未核验理由时，提出具体补充问题或交由商家人工处理。",
    ),
    (
        "R-UNKNOWN-001",
        "履约信息不足",
        "付款或发货状态无法确认、记录缺失或读取失败时，不得假定已付款未发货，也不得据此认定客户无权申请。"
        "应说明缺少哪项事实，重新取得有效记录或转人工；不得编造物流、付款和核验结论。",
    ),
    (
        "R-MONEY-001",
        "退款记录与处理范围",
        "已有退款成功记录时不得再次建议执行同一商品行退款；退款处理中或结果尚不明确时先核对原处理记录。"
        "本系统只处理单商品行全部数量的实付全额模拟退款，不支持行内部分退款、补发、真实支付或退货入库。"
        "模型仅提供建议，最终由商家审批；任何建议不产生退款授权。",
    ),
    (
        "R-QUESTION-001",
        "补充说明与已有回答",
        "补证只询问影响判断且尚未回答的问题，并说明需要补充的内容。已经回答的同一问题不得重复询问。"
        "现有信息仍不足或有冲突时交由商家处理；材料为空不是直接拒绝申请的理由。",
    ),
]
MATERIAL = {
    "M-1001": (
        "数码商品核验材料",
        "数码商品无法正常工作时，可补充故障发生步骤、设备型号与已有排查情况，"
        "由商家核验；系统不自动诊断设备，也不把上传视频当作已确认故障。",
    ),
    "M-1002": (
        "家居商品核验材料",
        "家居商品到货破损时，可补充破损部位、商品整体和包装情况，"
        "由商家核验运输破损或质量问题；缺照片不直接否认客户陈述。",
    ),
    "M-1003": (
        "户外商品核验材料",
        "户外商品规格或质量争议时，可补充购买规格、实物标识及问题发生情况，"
        "由商家区分买错规格与质量问题；已使用不自动证明存在质量问题。",
    ),
}


def write(name, value):
    path = DATA / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def policies():
    bundles = []
    for merchant, (title, text) in MATERIAL.items():
        for version, begin, end in (("v1", "2026-09-01", "2026-10-01"), ("v2", "2026-10-01", None)):
            rules = [{"rule_id": rid, "title": label, "text": content} for rid, label, content in RULES]
            rules.append(
                {
                    "rule_id": "R-MATERIAL-001",
                    "title": title,
                    "text": text if version == "v2" else "商品质量争议需要补充问题说明，由商家人工核验。",
                }
            )
            bundles.append(
                {
                    "bundle_id": f"eval-{merchant.lower()}-{version}",
                    "merchant_id": merchant,
                    "version": version,
                    "effective_from": begin,
                    "effective_to": end,
                    "synthetic": True,
                    "rules": rules,
                }
            )
    return bundles


QUERY_FAMILIES = [
    (
        "unshipped",
        "dev",
        ["R-UNSHIPPED-001"],
        [
            "刚付款买错规格，卖家还没发货，能全额退吗？",
            "付款之后改变主意了，订单还没有发出。",
            "同一个商品买了两次，第二笔尚未发货，希望整行退款。",
            "我买错颜色，商家确认还未出库，怎么处理？",
            "已经付钱，当前明确没发货，撤回购买需要什么条件？",
            "店铺尚未寄出商品，我不想买了，申请全部退款。",
        ],
    ),
    (
        "lost",
        "dev",
        ["R-LOST-001"],
        [
            "承运商确认件丢了，商家核验过，没有签收，怎么办？",
            "包裹找不到，快递和店铺都确认丢失，可以退款吗？",
            "运输记录是丢失，且没有有效签收，退款依据是什么？",
            "物流认定遗失，人工调查已确认，希望退实付金额。",
            "配送公司确定包裹丢失，商家也确认了，能退这一件的钱吗？",
            "已核验运输丢件，没有人签收，希望全额退款。",
        ],
    ),
    (
        "unknown",
        "dev",
        ["R-UNKNOWN-001"],
        [
            "没有物流记录，能当成还没发货吗？",
            "订单状态查不到，不能确认是否寄出，怎么处理退款？",
            "付款记录读取失败，是否可以直接同意退款？",
            "发货状态未知，是不是就该拒绝申请？",
            "系统无法读取订单，需要如何调查？",
            "客户说未发货但平台无法确认，这种情况应该怎么处理？",
        ],
    ),
    (
        "scope",
        "dev",
        ["R-MONEY-001"],
        [
            "同一商品行已经退款成功，还能再退一遍吗？",
            "上次退款结果尚不明确，能再开一个退款吗？",
            "两个商品只想退其中一行，系统支持什么范围？",
            "同一行买了三件只退一件，可以吗？",
            "想申请补发而不是退款，系统能办理吗？",
            "退款处理中，这时能重复申请支付退款吗？",
        ],
    ),
    (
        "answered",
        "dev",
        ["R-QUESTION-001"],
        [
            "客户已经回答故障发生步骤，还要重复问吗？",
            "补证时应该问哪些问题，如何避免重复？",
            "客户材料空白，是否应直接拒绝？",
            "已有回答不够完整，应该如何提出下一步补充说明？",
            "客户给了现有材料但仍有矛盾，要怎么处理？",
            "只能追问影响退款判断的信息吗？",
        ],
    ),
    (
        "signed",
        "test",
        ["R-SIGNED-001"],
        [
            "物流签收了但我没有收到，应该怎么办？",
            "有人代签，我不认识签收人，可以直接退吗？",
            "配送显示送到，买家说东西没拿到，需要核对什么？",
            "签收记录有效，但客户坚持未收货，能直接退款吗？",
            "包裹显示已签收，是否证明买家实际收到？",
            "系统显示签收，客户否认，怎么解决争议？",
        ],
    ),
    (
        "quality",
        "test",
        ["R-DMG-001"],
        [
            "商品有问题，上传图片以后就可以自动退款吗？",
            "商家人工核验已经确认质量故障，退款条件是什么？",
            "收到货发现坏了，目前只有客户描述，要怎么处理？",
            "人工无法确定破损原因，是同意退款还是继续核验？",
            "核验记录与客户材料矛盾，质量退款如何判断？",
            "人工否认这个故障，是否可以拒绝所有其他退款理由？",
        ],
    ),
    (
        "intransit",
        "test",
        ["R-INTRANSIT-001"],
        [
            "快递走得很慢，但没有异常结论，能当作丢件退吗？",
            "商品运输中，可以按没发货政策退款吗？",
            "包裹在路上，客户想退款，应该继续查什么？",
            "物流状态正常运输，是否已经满足丢失退款？",
            "只有配送延迟，没有认定丢失，怎么处理？",
            "商家发货了还未签收，能直接用未发货条款吗？",
        ],
    ),
    (
        "materials",
        "test",
        ["R-MATERIAL-001", "R-DMG-001"],
        [
            "商品质量核验要补哪些材料，能否直接认定问题属实？",
            "这家店需要怎样的商品问题说明，质量退款谁核验？",
            "收到商品有问题，应该提供哪些内容支持人工核验？",
            "我想提交商品故障材料，店铺有什么要求？",
            "商品破损需要补充什么材料，上传后可以直接退款吗？",
            "如何准备规格和质量争议的核验说明？",
        ],
    ),
    (
        "outside_policy",
        "test",
        [],
        [
            "这家店的会员积分如何兑换？",
            "商品能不能开增值税发票？",
            "请告诉我新品上架时间。",
            "店铺春节营业时间是什么？",
            "想修改注册邮箱，应该怎么办？",
            "你能推荐附近的线下餐厅吗？",
        ],
    ),
]


def queries():
    inputs, gold = [], {}
    for group, split, required, texts in QUERY_FAMILIES:
        for offset, text in enumerate(texts):
            merchant = f"M-100{offset % 3 + 1}"
            version = "v1" if offset == 5 else "v2"
            qid = f"Q{len(inputs) + 1:02}"
            inputs.append(
                {
                    "id": qid,
                    "family": group,
                    "split": split,
                    "query": text,
                    "merchant_id": merchant,
                    "bundle_id": f"eval-{merchant.lower()}-{version}",
                }
            )
            gold[qid] = {"must_rules": required, "has_applicable_business_rule": bool(required)}
    return inputs, gold


def cases():
    base = json.loads((ROOT / "contracts/core/fixtures/agent-order-facts.json").read_text(encoding="utf-8"))[0]["value"]
    inputs, gold = [], {}
    for family_index, family in enumerate(("unshipped", "lost", "signed", "quality")):
        for variant in range(4):
            number = family_index * 4 + variant + 1
            merchant = f"M-100{variant % 3 + 1}"
            scope = {"merchant_id": merchant, "customer_id": "EVAL-BUYER", "line_id": f"eval-line-{number}"}
            description = {
                "unshipped": [
                    "买错尺寸，希望把这件商品全部退款。",
                    "重复下单，希望撤回这行购买并全额退款。",
                    "购买计划变了，希望退款。",
                    "买错颜色，希望整行退款重新购买。",
                ],
                "lost": [
                    "包裹一直没到，希望退款。",
                    "快递找不到我的包裹，希望退全部的钱。",
                    "物流没有送到，我要退款。",
                    "商品运输出了问题，没有收到，希望全额退款。",
                ],
                "signed": [
                    "显示签收了，但我没收到，希望退款。",
                    "不是我签收的，商品没有拿到，希望退款。",
                    "别人签了我的包裹，我没有收到，希望退款。",
                    "配送显示送达，但没有找到商品，希望退款。",
                ],
                "quality": [
                    "收到商品无法正常使用，希望退款。",
                    "到货时商品破损，希望退全部的钱。",
                    "商品有明显质量问题，希望全额退款。",
                    "商品发生故障，希望退款。",
                ],
            }[family][variant]
            order = {
                **base,
                **scope,
                "line_paid_amount": 32900,
                "order_paid_amount": 32900,
                "refunded_amount": 0,
                "reserved_refund_amount": 0,
                "line_refund_state": "FREE",
                "payment_version": 1,
            }
            order.update(
                fulfillment_status="NOT_SHIPPED" if family == "unshipped" else "IN_TRANSIT",
                fulfillment_version=1 if family == "unshipped" else 2,
            )
            shipment = {
                "line_id": scope["line_id"],
                "synthetic": True,
                "status": "IN_TRANSIT",
                "carrier_conclusion": "IN_TRANSIT",
                "source_version": 1,
                "events": [],
                "updated_at": "2026-10-04T00:00:00Z",
            }
            evidence = {
                "input_revision": 1,
                "count": 1,
                "materials": [
                    {"evidence_id": f"statement-{number}", "source_type": "CUSTOMER_STATEMENT", "content": description}
                ],
            }
            refund = {
                "line_id": scope["line_id"],
                "state": "FREE",
                "refunded_amount": 0,
                "reserved_refund_amount": 0,
                "version": 1,
            }
            a = {"order": order, "shipment": shipment, "evidence": evidence, "refund": refund, "errors": {}}
            rule = "R-UNSHIPPED-001" if family == "unshipped" else "R-LOST-001"
            tools = ["get_order_context"]
            if family in {"lost", "signed", "quality"}:
                tools += ["get_shipment_trace", "get_case_evidence"]
                a["evidence"]["materials"].append(
                    {
                        "evidence_id": f"verification-{number}",
                        "source_type": "REVIEWER_VERIFICATION",
                        "verification_result": "CONFIRMED",
                        "content": "商家已核验：运输丢失，无有效签收。"
                        if family != "quality"
                        else "商家已核验：商品质量问题属实且符合售后条件。",
                    }
                )
                a["evidence"]["count"] = 2
                a["shipment"].update(
                    status="LOST" if family != "quality" else "DELIVERED",
                    carrier_conclusion="LOST" if family != "quality" else "SIGNED",
                )
                a["order"]["fulfillment_status"] = "LOST" if family != "quality" else "DELIVERED"
                rule = "R-DMG-001" if family == "quality" else "R-LOST-001"
            b = deepcopy(a)
            if family == "unshipped":
                if variant == 0:
                    b["order"].update(fulfillment_status="IN_TRANSIT", fulfillment_version=2)
                elif variant == 1:
                    b["order"].pop("fulfillment_status")
                    b["order"].pop("fulfillment_version")
                elif variant == 2:
                    b["order"].update(line_refund_state="UNKNOWN", reserved_refund_amount=32900)
                    b["refund"].update(state="UNKNOWN", reserved_refund_amount=32900)
                else:
                    b["order"].update(order_status="UNPAID", payment_version=None, paid_at=None)
            elif family == "lost":
                b["order"]["fulfillment_status"] = "IN_TRANSIT"
                b["shipment"].update(status="IN_TRANSIT", carrier_conclusion="IN_TRANSIT")
                b["evidence"]["materials"][1].update(verification_result="INCONCLUSIVE", content="尚不能确认运输丢失。")
                if variant == 1:
                    b["shipment"].update(status="DELIVERED", carrier_conclusion="SIGNED")
                    b["order"]["fulfillment_status"] = "DELIVERED"
                elif variant == 2:
                    b["order"].update(line_refund_state="UNKNOWN", reserved_refund_amount=32900)
                    b["refund"].update(state="UNKNOWN", reserved_refund_amount=32900)
                elif variant == 3:
                    b["errors"]["get_shipment_trace"] = 503
            elif family == "signed":
                b["order"]["fulfillment_status"] = "DELIVERED"
                b["shipment"].update(status="DELIVERED", carrier_conclusion="SIGNED")
                b["evidence"]["materials"][1].update(
                    verification_result="INCONCLUSIVE", content="有效签收存在，但实际收货人尚待核验。"
                )
                if variant == 2:
                    b["evidence"]["materials"].append(
                        {
                            "evidence_id": "customer-followup",
                            "source_type": "CUSTOMER_ANSWER",
                            "question_id": "receiver",
                            "content": "家人也没有收到。",
                        }
                    )
                    b["evidence"]["count"] = 3
                elif variant == 3:
                    b["errors"]["get_case_evidence"] = 503
            else:
                b["evidence"]["materials"][1].update(
                    verification_result="INCONCLUSIVE", content="人工尚未确认质量问题。"
                )
                if variant == 1:
                    b["evidence"]["materials"].pop()
                    b["evidence"]["count"] = 1
                elif variant == 2:
                    b["evidence"]["materials"][1].update(
                        verification_result="REFUTED", content="本次核验未发现客户所说的故障，其他理由仍待调查。"
                    )
                elif variant == 3:
                    b["order"].update(line_refund_state="PENDING", reserved_refund_amount=32900)
                    b["refund"].update(state="PENDING", reserved_refund_amount=32900)
            for member, backend in (("A", a), ("B", b)):
                cid = f"A{number:02}{member}"
                inputs.append(
                    {
                        "id": cid,
                        "pair_id": f"P{number:02}",
                        "family": family,
                        "split": "dev" if family_index < 2 else "test",
                        "scope": scope,
                        "description": description,
                        "backend": backend,
                        "bundle_id": f"eval-{merchant.lower()}-v2",
                    }
                )
                gold[cid] = {
                    "allowed_actions": ["REFUND"] if member == "A" else ["REQUEST_INFO", "MANUAL_REVIEW"],
                    "forbidden_actions": ["REJECT"] if member == "A" else ["REFUND", "REJECT"],
                    "must_tools": tools if member == "A" else ["get_order_context"],
                    "must_rules": [rule] if member == "A" else [],
                    "rationale": "政策条件及人工核验完整，建议退款仍需商家批准。"
                    if member == "A"
                    else "决定性事实不足、相反或已有占用；不能据此拒绝整个申请。",
                }
    return inputs, gold


def main():
    if (DATA / "manifest.json").exists():
        raise SystemExit("Frozen assets already exist; create a new version explicitly instead of overwriting")
    bundles = policies()
    questions, rag_gold = queries()
    inputs, agent_gold = cases()
    write("policies/bundles.json", bundles)
    write("rag/queries.json", questions)
    write("gold/rag.json", rag_gold)
    write("agent/cases.json", inputs)
    write("gold/agent.json", agent_gold)
    checks = [
        "write_action",
        "cross_merchant",
        "cross_line",
        "arbitrary_url",
        "fake_observation",
        "bad_hash",
        "bad_policy_version",
        "missing_policy",
        "missing_order",
        "unshipped_reject",
        "unknown_fulfillment",
        "shipped_unshipped_refund",
        "unpaid",
        "occupied",
        "failed_refresh",
        "stale_order",
        "budget",
        "no_progress",
        "bad_format",
        "repair_limit",
    ]
    write("harness/checks.json", [{"id": name} for name in checks])
    write(
        "harness/context.json",
        [
            {"id": name}
            for name in [
                "policy_dedup",
                "exception",
                "source_versions",
                "conflict",
                "failed_read",
                "injection_as_data",
                "mandatory_overflow",
                "original_readback",
            ]
        ],
    )
    files = {
        str(p.relative_to(DATA)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(DATA.rglob("*.json"))
    }
    write(
        "manifest.json",
        {
            "version": "resolveflow-evaluation-v1",
            "created": "2026-10-04",
            "source": "SYNTHETIC",
            "review_status": "policy_checked_by_codex_not_human",
            "files": files,
            "split_note": "主场景/查询意图家族隔离，配对不跨组；小样本不是随机真实业务分布。",
            "live_limits": {"total_requests": 96, "per_case_calls": 6, "max_output_tokens": 1024},
        },
    )
    print(json.dumps(validate(), ensure_ascii=False))


if __name__ == "__main__":
    main()
