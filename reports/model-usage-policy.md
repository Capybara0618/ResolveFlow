# 取消模型消费上限

2026-10-05，按用户明确要求实施。规格见[用量规则](../docs/model-usage-policy.md)。无真实模型请求、服务重启或业务库写入；原用量文件未清零，原冻结数据及报告不改。

第一步：移除评测累计调用/美元/费用估算输入输出拦截，保留调用前持久计数和进程锁。新命名LiveUsage，兼容LiveBudget，默认继续原累计文件。

关键失败测试先证明：旧96次/.50上限仍阻止新请求，输入/输出费用门槛仍拦截。首次测试另有一个Msg内容形状错误，修正为SDK TextBlock后再次确认旧调用上限失败。实现后`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_evaluation_controls.py -q`为32 passed；测试使用本地桩，不调用供应商。

后续步骤：取消新运行默认累计token限制，同步持久恢复和严格回放，集中验证后追加真实结果。
