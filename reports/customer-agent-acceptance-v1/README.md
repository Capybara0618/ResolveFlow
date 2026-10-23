# Agent冻结前小规模真实验收

2026-10-23，生产代码8c899f5、准备779d3a4，按[方案](../../docs/customer-agent-acceptance-v1.md)及[冻结清单](../../evals/customer-agent-acceptance-v1/manifest.json)只执行一次。**四轮自然对话3轮发布且完整、1轮未发布；单独恢复探针成功补读指南，但最终回答未发布。当前演示版本不标记验收完成，架构/功能范围保持不扩展。** 本批未修改生产代码、提示或规则，未因失败继续收费重跑。

## 逐项结果

| 场景 | 实际结果 | 证据 |
| --- | --- | --- |
| A01-1 物流签收与未收到 | 发布/完整 | 自主读物流，区分承运DELIVERED和客户陈述，三项陈述独立保存；只答事实，未附无关办理步骤 |
| A01-2 暂停插问退款入口 | 未发布 | t1暂停、新t2和指南读取正确；选择REFUND_APPLICATION，说明中正确写“我的售后”，初答及唯一修复均被页面名禁用规则拒绝 |
| A01-3 恢复原事项并更正家人情况 | 发布/完整 | t1原id恢复OPEN，家人旧陈述显式REPLACE为尚未问清；门卫原事实保留，物流/指南齐全，程序生成人工核查正确入口 |
| A01-4 再确认无人代收、仅人工核查 | 发布/完整 | 再次REPLACE不确定陈述，旧条SUPERSEDED；正确核查步骤和确认共享，不虚构转交或退款 |
| R01 显式缺指南故障注入恢复 | 补读通过/最终未发布 | 两条mock前缀触发真实Harness错误；首条真实模型决定读get_support_guide，第二条引用实际O1并选MERCHANT_REVIEW，但正确提到“售后咨询”而被拒 |

完整问答及未发布决定见[对话](conversations.md)，逐项依据见[源审](review.json)，请求/用量见[统计](statistics.json)。[自然四轮raw](natural-results.json)与[恢复探针raw](repair-results.json)分别保存完整请求、实际响应、工具及PG持久调用账；源审为Codex核对，非独立人工Gold、留出集或简历指标。不把3/4外推为一般成功率，不把注入探针并入自然对话分母。

## 已确认的进展与阻塞

缺指南的新反馈在本次真实模型上生效：R01的第一条供应商决定是READ_TOOL get_support_guide，读取后才引用O1，没有继续猜未读取的来源。探针的理解和第一次错误答复是两条明确的SCRIPTED_FAULT_INJECTION/mock记录；实际供应商仅生成后续两条，没有替换或丢弃真实模型响应。

主要阻塞集中在`navigation.py`的PAGE_LABELS条件：解释只要含“我的售后”或“售后咨询”就拒绝，连正确的页面说明也拒绝。A01-2已经读到指南、选择正确动作，R01也已补读并选择正确动作；当前规则仍使客户收不到回答。模型同时给结构化操作和自然说明，这条禁止名称的条件与正常解释发生冲突。应直接收口这一发布条件与结构化指引的关系，不据此再改Agent架构或继续加提示追分；本批只验收，不实施下一修复。

补充[离线定位](diagnostic.json)用两个失败的原始决定和工具复算，仅在诊断进程临时禁用PAGE_LABELS谓词：保留条件时两例FAILED，禁用这一条后两例均通过其余原校验，结束恢复原常量。原文件、模型响应、程序模板、来源、金额/权限和生产部署均未修改，没有新模型请求。这是定位谓词的离线诊断，不是strict回放、生产旁路或新的成功生成，不回填真实成绩。

A01-2反馈中的GUIDE source_gaps不表示文档未读取：该轮实际指南已返回，但模型只在next_steps声明source，页面名检查先抛错、尚未合并其引用，后续诊断据此报缺引用。需要区分“来源已读”和“最终part引用尚未处理”，避免继续把它归为RAG效果或速度问题。

非阻塞观察：A01-3可选门卫陈述误用CONTINUE（陈述仅支持APPEND/REPLACE/RETRACT），被拒后有warning且旧门卫事实/当前原文保留；不记为更新成功。A01-4门卫同义条目仍追加；解释与固定步骤有重复。两次家人REPLACE和原事项OPEN→PAUSED→OPEN真实生效，失败的退款事项保留OPEN/PENDING，没有伪造完成或失败轮助手回答。

## 调用与验证范围

共17次真实deepseek-flash请求，Provider输入42653、输出1838、estimated=false，usage1977→1994；另两条注入决定为mock且不计Provider请求/Token。SDK总19决定、7工具，导出5run/26调用账，模式可逐条核查。自然四轮合计20.107秒、预热9.770秒另列；探针3.064秒。Harness保守输入估计自然44782、探针8815（含注入前缀）另列，不混成Provider计数。

本批使用真实模型、AgentScope、ASGI及独立PG；指南来自当前正式资产，Commerce/Case是原固定合成HTTP。未启动Java或网页，未执行退款/分享写入、政策RAG召回/速度评测或压测，不代表完整业务端到端。

新准备单元/实际隔离PG4通过（4.07秒），测试与执行器Ruff通过。两条导入分组lint在正式执行前修正，当前清单重新冻结并验证；未改旧清单。工程测试覆盖注入/供应商分离、真实Harness反馈和0调用恢复；不会替代本批失败的真实结果。源码/权重/数据库执行前后预检通过，离线诊断重复结果一致。生产代码与8c899f5逐文件差异为空。

public11表全行hash和原四脏文件、旧raw/旧清单/旧诊断共11文件hash前后相同，见[保全指纹](preservation.json)；自有schema导出后清理，原数据/政策/旧失败/简历保持。收尾只停止本轮启动的原PG，保留卷；不自动启动业务服务。最终容器/端口和用量锁状态见任务账本。

原始文件SHA256：自然`0634f803d06db29517f5359e5420895a2e064f5d3263e7df89b543025c5291f0`，探针`fc382cb47ee8fcdae2d412c6ca6e6a6cbdb15f92873fd6d97cbb447f0f548b9e`。

主要实际命令（真实execute已执行，不再次调用）：

```powershell
# agent目录，实际隔离PG测试
.venv/Scripts/python.exe -m pytest tests/unit/test_customer_agent_acceptance_v1.py tests/integration/test_customer_agent_acceptance_v1.py -q
# 仓库根目录，check --database需原PG已启动
agent/.venv/Scripts/python.exe scripts/customer_agent_acceptance_v1.py --check --database
agent/.venv/Scripts/python.exe scripts/customer_agent_acceptance_diagnose_v1.py --output reports/customer-agent-acceptance-v1/diagnostic.json
```
