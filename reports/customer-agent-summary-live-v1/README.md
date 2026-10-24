# 摘要来源修复后的真实验收

2026-10-24，按用户授权执行[本批规格](../../docs/customer-agent-summary-live-v1.md)：2组5轮自由对话、独立受控故障后的真实模型续验、1条真实网页退款草稿编辑与刷新。固定[场景及判据](../../evals/customer-agent-summary-live-v1/scenarios.json)与[manifest](../../evals/customer-agent-summary-live-v1/manifest.json)，业务4a1b0b0不改。

准备：驱动4单元通过，Ruff两文件通过（首次导入排序已整理）；[0模型预检](preflight.json)精确PG政策generation及公共表保持。启动前核实无旧待处理run，再正常start -SkipBuild -NoBrowser，全栈及索引健康；网页仅新建一笔合成329元耳机订单/LOST物流及空会话，provider请求0，全局usage2329。

自由组最多24新请求、受控续验6、网页原单轮12，总最多42，失败也计账、不追加追题。受控前三个决定明确mock，后续真实决定另列，不并成自然成功率。准备精确提交普通push核实后各部分只执行一次，逐轮源审，最后保留旧业务/报告并恢复本批资源。
