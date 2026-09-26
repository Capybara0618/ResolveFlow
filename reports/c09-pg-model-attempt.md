# C09 UNKNOWN模型重试attempt账（2026-09-26）

追加迁移007，建立 `agent_model_attempt`：同一逻辑call_id最多原请求attempt=0和一次重试attempt=1。原预占同时落attempt；`reserve_retry(expected_attempt=0)` 在锁run行并核验fence/owner/lease/状态/deadline后，按原kind再次消费同一10普通+2恢复分区和token预算。请求hash、输入预占与输出上限保持原值；剩余预算不足明确拒绝，不把改变输出上限的请求冒充原hash。相同重试意图并发/重复调用只一次新预占，其余返回 `new_reservation=False`，不授予再次发送许可。已保存结果禁止重试，attempt=1后再重试拒绝。

保存结果须标明当前attempt，且该attempt由当前fence预占；旧attempt迟到或旧worker写入均拒绝。只对成功保存的当前attempt恰一次结算，先前UNKNOWN仍保留完整保守预占。例如第一次预占20输入/1024输出，重试同额，再保存精确10输入/5输出，run账为2次、30输入/1029输出，原attempt仍UNKNOWN；不能因后来成功而假设前次免费。逻辑结果依旧按call_id复用，不存在两份有效结果。

旧记录迁移保留原usage/spend，补attempt0但 `reserved_fence=NULL`，明确原始fence不可重建。未知旧结果不能在当前fence下直接保存，只能走有预算的显式重试；已保存旧结果保留可读。迁移 `ON CONFLICT DO NOTHING`，重跑不覆盖UNKNOWN历史、不复制重试结果到原attempt、不重扣预算。所有迁移核查在测试独立schema中执行，没有清共享数据或删卷。

验证：新增6项真实PG失败测试先RED（缺 `reserve_retry`，6 failed），实现后补迁移幂等例，新增7例；连同预占/结果/store/worker/分区回归 **60 passed**。命令（agent目录）：`./.venv/Scripts/python.exe -m pytest tests/integration/test_recovery_model_attempt.py tests/integration/test_recovery_model_result.py tests/integration/test_recovery_budget_store.py tests/integration/test_run_store.py tests/integration/test_run_worker.py tests/unit/test_recovery_call_budget.py -q -p no:cacheprovider --tb=short`。全量Ruff通过，修改源码单独strict mypy通过；全量strict mypy仍4个既有文件9个no-any-return错误。实际网络发送本步没有执行，只证明PG预占/响应模拟数据的规则。

全量Python：`./.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --tb=short` → **1082 passed / 9 skipped / 1 warning，191.50s**，exit_code=0；diff检查通过。

未运行Java、all-offline、live、H4/CF6；生产worker/SDK尚未使用该存储。下一具体动作：冻结脱敏实际provider请求体并使hash/输出ceiling一致，之后接生产租约/advisory lock、领域快照与SDK重建；未接入前不勾C09，不声称零重复计费。
