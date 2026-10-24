# 操作意愿与代表性多轮真实收口

2026-10-24，业务基线14f2c7e，用户授权按[本批规格](../../docs/customer-agent-intent-v1.md)一次代表性多轮确认。[冻结输入](../../evals/customer-agent-close-v1/scenarios.json)/[manifest](../../evals/customer-agent-close-v1/manifest.json)为3组10轮、最多40次真实请求；不新增真实业务动作，不重算旧六条或44轮。

准备驱动2单元通过，Ruff两文件通过，首次2项导入分组整理后通过；固定代码/数据/本地权重及usage2290。[只读预检](preflight.json)核实精确generation和11公共表不变，0新模型。原业务HTTP为冻结合成快照，PG索引真实；运行只写独占临时schema，不起Java/网页/正常调查worker。

准备精确提交/普通push核实后，execute一次；每轮继承本组实际前序答案及已接受状态，失败也保留，不编成功历史。原输入/Gold/业务实现运行中固定，结果按每轮语义和完整会话评判；不把新字段拦住旧输出当成真实质量提升。当前进度只在tasks/todo.md顶部。
