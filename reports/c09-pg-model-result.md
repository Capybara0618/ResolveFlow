# C09模型结果保存与恰一次usage结算（2026-09-26）

追加迁移006，不修改已执行迁移；`RecoveryBudgetStore.save_result/recorded_result` 保存和读取显式 `ModelReply`（decision、usage、mock/live、model alias），不保存供应商原始报文或隐式推理字段。结果与usage在锁run行并校验状态、owner/fence、lease、deadline后同事务提交，网络仍在事务外。无预占记录拒绝保存；非法负数/布尔token值拒绝且UNKNOWN预占不变。响应有64KiB上限。

已保存结果按稳定call_id直接读取，不需要checkpoint先推进，不再预占/调用模型/结算。相同响应重复或并发保存只有一次新结果；不同响应覆盖同ID拒绝。精确usage按输入和输出实耗结算，估算usage不退回保守预占。实际输出超过请求预占、实际输入超过单步/累计上限时先提交真实消耗及持久停止原因，随后禁止普通或恢复新调用，不因抛异常回滚消耗。读回较早结果和重复保存也带上当前run停止原因，避免恢复遗漏后续调用产生的停止状态；未来SDK适配必须在任何工具/终局动作前检查该字段。

RED：新增5项真实PG测试全部AttributeError失败（缺保存/读取接口）。GREEN后新增invalid usage/input overage例，相关52 passed。复核补“后续超额后读回较早结果”反例，RED 1 failed（stop_reason为None），修复为同时读取run停止原因后相关 **53 passed**（新增结果文件10例+PG预占4例+既有store/worker/分区）。命令（agent目录）：`./.venv/Scripts/python.exe -m pytest tests/integration/test_recovery_model_result.py tests/integration/test_recovery_budget_store.py tests/integration/test_run_store.py tests/integration/test_run_worker.py tests/unit/test_recovery_call_budget.py -q -p no:cacheprovider --tb=short`。全量Ruff通过；修改源码strict mypy通过，全量strict mypy仍为4个既有文件9个no-any-return错误。

第一次全量（停止原因传播修复前）**1074 passed / 9 skipped / 1 warning，190.03s**，不能作为最终修复验证。修复后全量 `./.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --tb=short` → **1075 passed / 9 skipped / 1 warning，190.06s**，exit_code=0；diff检查通过。

限制：本步真实PG只在测试隔离schema中验证结果台账，没有运行生产SDK故障恢复；尚无UNKNOWN重试attempt、实际请求体冻结、生产领取租约/advisory lock、工具结果存储、checkpoint或终局callback fence接入。H4/CF6、Java、all-offline、live未运行，C09不勾。下一小步为UNKNOWN新增显式attempt账及预算预占，复用逻辑call_id但每次真正请求都计入次数/token；然后再接生产运行快照与SDK。
