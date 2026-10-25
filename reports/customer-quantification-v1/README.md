# 当前客服 Agent / RAG 正式量化

2026-10-25，用户明确要求开始正式评测。使用已冻结7cf1b3f准备及两个manifest，原规格/输入/判据/权重不变；本批新生成API上限800请求，ledger起点2447，最多至3247。按准备报告已公布建议值执行，不沿用旧批额度、不自动追加收费重跑。

Agent32场景×动态/固定×2次=128会话运行/200客服轮。复杂24组每组48运行，以完整会话的来源审查判完成；失败/预算耗尽保留全部分母和费用。RAG40问×5方案×3次=600本地检索，主候选RRF事前选定，直接/展开证据覆盖分开。两套测量顺序运行避免资源互相干扰；来源可见合成工程验收，非独立真实用户数据。

正式命令：`python -m scripts.customer_quantification_agent execute --live --max-provider-requests 800 --output reports/customer-quantification-v1/agent-runtime.json`；随后`python -m scripts.customer_quantification_rag execute --output reports/customer-quantification-v1/rag-results.json`。运行结束后生成完整源审模板、核对实际事实/政策/摘要/记忆/状态并汇总，不把SUCCEEDED等同语义正确。此页后续追加真实结果，不先填简历数字。

本批不改生产实现/基线、简历或旧结果，不启业务应用/Java worker；仅用原PG只读政策与所属临时schema，真实模型+冻结HTTP事实，不冒充新Java/UI退款验收。原数据、历史报告和四历史脏文件保持。当前通过/失败/未运行及环境限制将完整记录。
