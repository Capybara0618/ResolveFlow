# 动作协议修复后真实冒烟 v1

2026-10-21。db3d8b3 恢复完整动作示例/缺kind反馈，a98f4ee 冻结3类6轮/组，两组12轮实际执行。**kind遗漏已在本批消失，但整体目标未通过：自主0/6，固定2/6。** [完整轨迹](runtime-results.json) / [统计](summary.json) / [逐轮源审](semantic-review.json) / [协议](../../docs/customer-agent-action-repair-v1.md)。

27次实际DeepSeek Flash响应的顶层kind均合法；模型请求仍采用原参数/1024输出上限/预算，没有自动修补响应。自主实际读了2次物流；固定在S02/S03首轮各完成订单、物流、指南和政策读取并回答。S02正确覆盖LOST与人工核验、正式入口；S03首轮区分系统签收与客户未收到、代收未确认，未虚构已转交。两项完整按原条件由Codex源审，不是独立人审或盲测；不能把局部成功当作自主Agent可用。

| 组 | 完整/失败轮次 | 实际模型 | provider输入/输出token | 工具/政策检索 |
| --- | --- | --- | --- | --- |
| 自主 | 0/6、6/6 | 14 | 21971/2926 | 2/0 |
| 固定 | 2/6、4/6 | 13 | 25932/2637 | 8/2 |

账本1716→1743，预热9.411秒单列。真实模型/ASGI/SDK/隔离PG执行，业务HTTP/系统状态仍为冻结合成快照、政策为原保留PG版本；没有Java/网页全栈或新用户数据。12轮无重跑，旧88轮与Gold保持。

余下10轮均INVALID_DECISION。保存记录显示：dialogue_events.reference被输出为null、O1或sequence:1；字段反馈过泛，纠错又遗漏首轮tasks，或把已接受任务再次标ADD。memory quote/offset也有不一致。S03固定首轮业务回答完整，但任务被标ANSWERED，后续暂停旧任务的状态含义有冲突风险；这仍需明确任务语义与真实多轮验证，未修改原评分刷分。

132项工程通过与本批真实失败分别记录。原动作严格校验、一次纠错和作用域保持，缺失标注未自动补成正确状态。本报告及轨迹先保留；用户继续后下一修复聚焦字段示例、引用范围、完整重发和当前已接受状态提示，另立新冻结定点确认，不覆盖本批结果。

本批88旧run未碰，12新run/27模型调用已完整导出，自有schema已清理，public前后全行hash相等。临时PG暂保留运行用于用户已要求继续的修复/验证，最终收口再停止并核验；当前没有普通业务worker或队列。执行命令为 `agent/.venv/Scripts/python.exe scripts/customer_agent_action_smoke_v1.py --execute --output reports/customer-agent-action-smoke-v1/runtime-results.json`，新数据和60文件/权重见对应冻结清单。
