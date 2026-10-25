# 客服状态与摘要引用收尾

2026-10-25，沿用[实施说明](../../docs/customer-boundary-closeout-v1.md)，保留原固定验收全部失败，不换架构。

第一步多目标纠正：`CustomerClaim.targets`显式选择被同一更正取代的多条旧陈述，单target兼容；新条目及追加关系均在副本验证后一次接纳。原话、替代/撤回关系及未选独立陈述保留，不按同主题自动清除。

先增失败测试2红/4过，再实现；`python -m pytest agent/tests/unit/test_support_boundary_closeout.py agent/tests/unit/test_support_customer_claims.py agent/tests/unit/test_support_memory.py -q`最终36通过，新/三生产文件Ruff通过。包括多目标REPLACE/RETRACT、恢复后的有效集合、坏目标/跨主题/重复/双字段、已追加同句的原子扩展及重复幂等。0真实模型请求，ledger2410，原数据/四历史脏文件保持。摘要候选和状态衔接尚待第二步；尚未真实验证模型会完整选中所有语义目标。

## 第二步：合法引用与事项衔接

多目标纠正b929687已普通push核实。COMPOSE实际请求增加summary_candidates，仅含本轮短原文、明确操作请求及有效客户记忆；长输入不截前300字当完整原话。模型以customer_refs选择，程序解析并调用原ground_summary，事实/来源及待本人确认边界保持。未知引用反馈具体非法ref及当前合法列表，不自动猜替或开放任意H历史；旧customer_quotes仍经原严格校验兼容。

同一问题可保留事项id并更新intent/goal，PAUSED必须显式RESUME；新提示明确这一合同，实际SDK测试确认查询→退款准备后原id为OPEN，不批量恢复其他暂停事项。已有状态代码支持这个转换，此步未增关键词状态推断。

- 新针对测试先红；长文本fixture最初先触发旧focus长度限制，修正构造后验证不截断。兼容旧无id的直接grounding测试最初KeyError，修正候选仅接受有id条目，旧原文兼容入口保持；新脚本一次tests.unit导入路径错误已改为独立datetime，Ruff import顺序修正。
- `python -m pytest`四个针对文件52通过；全部`test_support*.py`单元514通过。实际原PG七个integration文件17通过，包括新多目标+引用摘要同run恢复，恢复0新模型/工具且结果全等；均脚本模型，不算真实质量。
- `python -m scripts.diagnose_customer_closeout_v1`在禁止外部HTTP/网络下对原F01/4、F01/5、F03/3进行三项明确合同适配，全部成功，见[离线输出](offline-adaptations.json)。适配由开发者指定，不是模型自主选对或严格旧manifest回放，不写成新成功率。
- 生产三个文件、新测试和诊断脚本Ruff通过。当前0新供应商请求、ledger2410；临时PG测试schema清理，业务服务未启。工程提交普通push核实后才冻结原11轮一次真实确认。
