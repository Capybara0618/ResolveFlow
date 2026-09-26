# C09调用预算分区前置（2026-09-26）

新增 `agent/src/resolveflow/runtime/recovery_budget.py` 不可变计数对象。默认总12次，预留2次恢复；普通调用10次后拒绝，恢复只能以 `RECOVERY_TURN` 消费且最多2次。持久形状可往返重建，非法/超额/缺失字段拒绝，不允许隐藏总结调用或总额扩大。此对象只负责调用次数分区，尚未接入worker/PG；不代替既有BudgetGuard的token、deadline、输出预占/结算，更不证明C09恢复。

测试先运行新增失败测试，RED为模块不存在导致1 collection error；实现后聚焦 `test_recovery_call_budget.py test_harness_loop.py test_loop_semantics.py` **57 passed**。全量命令（工作目录agent）`./.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --tb=short` → **1061 passed / 9 skipped / 1 warning，180.17s**；期间用户中断对话，但测试进程继续，接续后获取exit_code=0及完整结果，没有重复发起。Ruff新增源码/测试通过；`mypy --strict src/resolveflow/runtime/recovery_budget.py` **1 source file通过**。未重跑全量mypy（上次既有9错），未运行Java/all-offline/live/H4/CF6。

下一步：新增迁移和最小PG存储，以锁run行/fence/有效状态保护调用预算及稳定call记录；重建时读取冻结分区和原计数，不默认构造新对象清零。随后才接入SDK调用前预占、结果保存、checkpoint与旧worker保护。C09复选框保持未勾。
