# 取消模型消费上限

2026-10-05，按用户明确要求实施。规格见[用量规则](../docs/model-usage-policy.md)。无真实模型请求、服务重启或业务库写入；原用量文件未清零，原冻结数据及报告不改。

第一步：移除评测累计调用/美元/费用估算输入输出拦截，保留调用前持久计数和进程锁。新命名LiveUsage，兼容LiveBudget，默认继续原累计文件。

关键失败测试先证明：旧96次/.50上限仍阻止新请求，输入/输出费用门槛仍拦截。首次测试另有一个Msg内容形状错误，修正为SDK TextBlock后再次确认旧调用上限失败。实现后`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_evaluation_controls.py -q`为32 passed；测试使用本地桩，不调用供应商。

第二步：RunBudget累计输入/输出默认null；SDK每轮不再按累计输入收缩上下文，单次输出不会因累计用量缩减。持久预占/usage结算/重建支持null；明确旧数值配置的测试和历史run仍保留原约束，恢复不会自动去除它们。HarnessManifest Schema同步允许null，当前生产生成器及Schema验证测试核对两字段；旧正负fixture及冻结hash不修改。context v9、新usage-v6七回放包独立发布，不覆盖旧包或绕过源码/请求hash检查。

关键失败先复现：默认循环第六步超过原输入40000被拦截，持久恢复第五步输出长度因原累计4000被缩小。实现后单元测试累计输入70000/输出7000仍可继续；隔离PG重建八次后累计56000/6400仍无消费停止。旧显式40000/4000恢复仍在第四次耗尽输出；迭代、防循环、超时、单步超额及fence相关反例保留。

最终集中结果：37模块**480 passed / 0 skipped**，[实际pytest命令](model-usage-policy/commands.json)、[输出](model-usage-policy/tests.txt)、[JUnit](model-usage-policy/tests.xml)；独立[Harness28/28](model-usage-policy/harness-final.json)、[strict7/7](model-usage-policy/replay-final.json)。最终测试在代码行换行整理后重跑；新回放以最终源码重新导出。初始未提交回放草稿移至忽略的tmp，已提交旧资产完全保留。

`eval.ps1 -Mode validate`与`-Dataset evals/current`各自通过（3商家/6bundle/32案例/16配对/60查询）；新`-LiveUsage`和旧`-LiveBudget`参数各执行validate通过，不发送模型请求。最终14个相关源码/测试/脚本用`ruff check --config agent/pyproject.toml`通过。初次root默认Ruff配置不适用脚本，按项目配置检查后修复一个新增长行及相关测试导入整理/计数标签误报；不修改其他作者文件。

类型检查：`mypy --config-file agent/pyproject.toml agent/src/resolveflow`仍为原16 errors / 9 files / 69 source files，与上批基线相同，无新nullable诊断；不带配置的检查为2个既有错误，不作为更高质量主张。全项目类型门禁尚未通过。

本机旧共享文件在独占锁下转换为只记用量：[状态证据](model-usage-policy/usage-ledger.json)为used96、limit=null、historical_limit96、历史reserved_usd仍0.2855712。没有清零、增加调用或重新估算费用。逐次供应商usage仍在以后实际报告保存；已有评测资产中的live_limits及原v1生成脚本是历史冻结资料，不进入当前拦截逻辑。

未运行：新收费Live、32例完整mock/新RAG效果评测、Java业务全链、服务重启/部署；本次不主张Agent准确率提高。PG测试只用隔离schema，新生产默认下次启动加载，正在运行进程及原已持久run不热改。权限、资金、审批、UNKNOWN、引用约束不变；其他四历史脏文件及草图/日志不夹带。
