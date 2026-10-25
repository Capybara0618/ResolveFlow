"""Offline source review of the one frozen final acceptance; never invokes a model."""

from __future__ import annotations

from statistics import median

from resolveflow.support.grounding import GroundingError, ground_summary
from resolveflow.support.memory import CustomerMemory
from resolveflow.support.protocol import SupportInput

from scripts.accept_customer_final_v1 import OUT, load_plan
from scripts.customer_agent_eval_v2 import read_json, write_new

REVIEWS = [
    ("PASS", ["实际SHIPMENT为DELIVERED；区分承运记录与本人/家人未收陈述。", "未生成退款/人工摘要。"],
     "候选正文1次reset，最终回答正常；不能用首候选冒充保留正文。"),
    ("PASS", ["家人未代收旧条目SUPERSEDED，尚未回复的新条目ACTIVE；正文没有沿用已排除代收。",
              "本人未收事项保留且无操作摘要。"], None),
    ("PASS", ["原t1=PAUSED，t2回答独立人工咨询能力，客户旧陈述保留。",
              "真实GUIDE说明确认共享，无摘要/自动发送。"], None),
    ("PARTIAL", ["退款草稿正确保留尚未核实家人代收，但新建t3=APPLICATION，旧t1仍PAUSED，未落实预设恢复原事项。",
                 "实际读取本店ORDER/SHIPMENT/POLICY；签收争议/人工核验及329元、待确认用途正确。"],
     "业务草稿可用；事项恢复判据未全过，不在结果出来后放宽为完全通过。"),
    ("FAIL", ["找到包裹被采纳且t1=RESOLVED，但三条旧RECEIPT仍ACTIVE，其中两条仍称目前未拿到。",
              "无可操作摘要，t2/t3=CANCELLED；没有声称撤销已存在退款工单。"],
     "阻断：关键纠正的有效记忆范围不完整；尚未实际执行后续轮，不声称已发生错误退款。"),
    ("PASS", ["handoff摘要引用客户原话并标未经核验，无无依据订单事实。",
              "实际GUIDE/可信交互快照说明已有已解决记录可补充接续，尚未发送且无退款摘要。"], None),
    ("PASS", ["开线旧条目SUPERSEDED，掉皮新条目ACTIVE；摘要保留不是开线的纠正语境。",
              "仍为未发送人工摘要，无退款摘要。"], None),
    ("PASS", ["原摘要准备t1=PAUSED，无本轮操作摘要。",
              "GUIDE说明只见确认共享/明确发给商家内容，私有助手历史不自动全共享；没有混同默认接收人。"], None),
    ("PASS", ["绑定M-1002当前ORDER为129元、SHIPMENT为LOST，本店政策及未经核验原话分开。",
              "退款quote摘要待确认；解释无有效签收与人工核验前提，没有假提交。"], None),
    ("PASS", ["退款t2=CANCELLED、无操作摘要，符合先不准备退款的即时效果。",
              "真实本店POLICY承接LOST/签收争议，无虚构必交材料清单，未用应用GUIDE冒充政策。"],
     "多选了正文未使用的P5在途条款；未列固定清单不能推广为商家以后永不要求补充。"),
    ("FAIL", ["正确理解MERCHANT_REVIEW且非退款，但两个RESPOND均含不合法历史quote，最终INVALID_DECISION，无回答/摘要。",
              "没有实际发送/退款；失败前仅GUIDE，本轮未读物流/政策，候选旧政策重述不能算新取证。"],
     "阻断：原话选择合同与原始历史可见范围不同，通用纠错未定位非法元素，有限修复后仍失败。"),
]


def main():
    plan, cases = load_plan()
    runtime = read_json(OUT / "runtime-results.json")
    rows = runtime["rows"]
    assert runtime["state"] == "FINISHED" and len(rows) == len(REVIEWS) == 11
    assert runtime["public_before"] == runtime["public_after"]
    assert runtime["isolated_schema_dropped"]
    assert sum(len(r["models"]) for r in rows) == runtime["usage_after"] - runtime["usage_before"] == 29
    reviewed, transcript = [], ["# 固定3组11轮实际会话", "", "真实DeepSeek；合成HTTP事实/真实只读政策；无Java/UI新验收。全部输入只执行一次。", ""]
    for row, (status, findings, note) in zip(rows, REVIEWS, strict=True):
        case = next(c for c in cases if c["id"] == row["id"])
        turn = case["turns"][row["turn"] - 1]
        answer = row["result"].get("answer") or {}
        state = answer or row["result"].get("conversation_update") or {}
        citations = [{"type": c["source_type"], "id": c["source_id"], "version": c["version"],
                      **({"title": c["title"], "text": c["data"]["text"],
                          "merchant_id": c["data"]["merchant_id"],
                          "retrieval_context": c["retrieval_context"]} if c["source_type"] == "POLICY" else {})}
                     for c in answer.get("citations", [])]
        entry = {"id": row["id"], "turn": row["turn"], "run_id": row["input"]["run_id"],
                 "publication": row["result"]["status"], "review": status,
                 "criteria": turn["criteria"], "findings": findings, "note": note,
                 "citations": citations, "task_state": state.get("task_state"),
                 "customer_memory": state.get("customer_memory"), "stream_times": row["stream_times"]}
        reviewed.append(entry)
        transcript.extend([f"## {row['id']} · 第{row['turn']}轮 · {status}", "", "客户：" + turn["text"], "",
                           "助手：" + answer.get("text", "【未发布：" + str(row["result"].get("reason")) + "】"), ""])
        for field in ("refund_summary", "handoff_summary"):
            if answer.get(field):
                transcript.extend([field + "：", "", answer[field], ""])
        transcript.extend(["源审：" + "；".join(findings), ""])
        if note:
            transcript.extend(["备注：" + note, ""])

    # Reproduce the exact rejection locally; the alternative is diagnostic, not a repaired live score.
    failed = rows[-1]
    request = SupportInput.model_validate(failed["input"])
    claims = failed["result"]["conversation_update"]["customer_memory"]["entries"]
    rejected = []
    for model in failed["models"][1:]:
        quotes = model["decision"]["handoff_reason"]["customer_quotes"]
        invalid = []
        for quote in quotes:
            try:
                ground_summary([quote], [], request, {}, claims, refund=False)
            except GroundingError as error:
                invalid.append({"quote": quote, "error": str(error)})
        try:
            ground_summary(quotes, [], request, {}, claims, refund=False)
        except GroundingError:
            rejected.append({"customer_quotes": quotes, "invalid_elements": invalid})
        else:
            raise AssertionError("recorded failed quote must still be rejected")
    assert len(rejected) == 2
    legal = ground_summary([claims[0]["quote"], request.context["current_request"]], [], request, {}, claims, refund=False)

    resolved = rows[4]
    memory = resolved["result"]["answer"]["customer_memory"]
    next_request = SupportInput.model_validate(resolved["input"]).model_copy(
        update={"input_version": resolved["input"]["input_version"] + 2,
                "context": {"previous_customer_memory": memory}})
    carried = CustomerMemory(next_request).packet()["active"]
    assert {e["quote"] for e in carried} >= {"目前我还没有拿到", "我还是没拿到"}
    diagnosis = {"mode": "offline_no_model_no_business_writes", "new_provider_requests": 0,
        "summary_quote_failure": {"exact_recorded_rejections": rejected,
            "legal_selection_passes_current_grounder": legal,
            "scope": "只证明原拒绝条件及合法候选存在，不是改提示后的真实模型成功或修复收益。",
            "source": ["agent/src/resolveflow/support/grounding.py", "agent/src/resolveflow/support/engine.py"]},
        "incomplete_correction": {"accepted_understanding": resolved["models"][0]["decision"],
            "active_in_next_version_without_new_model": carried,
            "scope": "确认旧陈述会作为ACTIVE传入下一版本；未跑下一轮，不推测实际错答。",
            "source": ["agent/src/resolveflow/support/memory.py", "agent/src/resolveflow/support/protocol.py"]}}
    write_new(OUT / "offline-diagnosis.json", diagnosis)
    successful = [r for r in rows if r["result"]["status"] == "SUCCEEDED"]
    retained = [r["stream_times"]["first_retained_ms"] for r in successful if r["stream_times"]["first_retained_ms"] is not None]
    models = [m for r in rows for m in r["models"]]
    summary = {"scope": "source-visible synthetic regression; real model; frozen HTTP; no new UI/business E2E",
        "conversations": 3, "turns": 11, "published": len(successful),
        "criteria_pass": sum(r["review"] == "PASS" for r in reviewed),
        "criteria_partial": sum(r["review"] == "PARTIAL" for r in reviewed),
        "criteria_fail": sum(r["review"] == "FAIL" for r in reviewed),
        "blocking_turns": ["F01/5", "F03/3"], "freeze_ready": False,
        "new_provider_requests": len(models), "allowance": plan["max_new_provider_attempts"],
        "usage_before": runtime["usage_before"], "usage_after": runtime["usage_after"],
        "input_tokens": sum(m["usage"]["input_tokens"] for m in models),
        "output_tokens": sum(m["usage"]["output_tokens"] for m in models),
        "estimated_usage_requests": sum(m["usage"].get("estimated", False) for m in models),
        "unknown_usage_requests": sum(not m.get("usage") for m in models),
        "successful_completion_ms": {"n": len(successful), "median": median(r["elapsed_ms"] for r in successful),
                                     "min": min(r["elapsed_ms"] for r in successful), "max": max(r["elapsed_ms"] for r in successful)},
        "retained_first_body_ms": {"n": len(retained), "median": median(retained), "min": min(retained), "max": max(retained),
                                   "not_included": "F01/1候选reset后最终发布，无保留首delta；F03/3失败，不进入成功分布。"},
        "timing_scope": "runtime event receiver; not browser timing, no stable SLA or population P95 claim",
        "policy_calls": sum(t["name"] == "search_policy" for r in rows for t in r["tools"]),
        "policy_mode": "COMPLETE_SMALL_SET; six rules per merchant, not external corpus retrieval benchmark",
        "public_unchanged": True, "isolated_schema_dropped": True}
    write_new(OUT / "source-review.json", {"reviewer": "CODEX_SOURCE_REVIEW_NOT_INDEPENDENT_HUMAN_GOLD", "summary": summary, "rows": reviewed})
    path = OUT / "conversations.md"
    if path.exists():
        raise FileExistsError(path)
    path.write_text("\n".join(transcript).rstrip() + "\n", encoding="utf-8", newline="\n")
    print(summary)


if __name__ == "__main__":
    main()
