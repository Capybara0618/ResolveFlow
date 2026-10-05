# 外部FAQ问法诊断 v1

11个公开京东帮助问题原话，采集日2026-10-05；来源和短问题hash见sources.json。问题由商城编写，**不是消费者会话**。题目在本批排名前选定，人工便利取样，非随机/盲测。部分帮助页面为历史页面，其回答未复制、未作为项目政策或法律结论。

每个问法绑定aligned-v2中三家商家的v2政策，共33个查询；重复商家测试不增加独立问法数量。原6份合成政策与Gold不改。来源问法涉及签收争议、支付失败、重复支付、申请进度、审核原因、取消恢复、预售、发票、错货、退换资格、审核时间，有些主题可能超出项目政策范围；**空Gold待人审，不能用词语相似度推断适用**。

manifest.json冻结sources.json、queries.json、原语料manifest、商家范围及分母。输入不含Gold。执行入口：

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe scripts/evaluation/rag_probes.py --live-report reports/agent-quality-batch5/live-all.json --output tmp/query-probes.json --review-output tmp/query-review.json
```

需要一个当前源码版本、已完成状态的真实Agent报告；mock/旧版本/零查询拒绝。脚本通过隔离PG与本地固定embedding生成正文dense/BM25候选，不联网调用LLM或写Java业务。检索准确率恒为null；逐query相关性先交给独立复核，不能拿工单最终Gold给所有中间查询计分。新报告路径必须不存在。

复核队列的must_rules=null表示未标注，空数组仅表示复核确定无适用规则。队列含完整原政策，先判断问法/条款相关性，再查看候选排名；记录复核人和时间。当前不宣称独立Gold已经完成。候选分数不是概率、退款资格或金额授权。
