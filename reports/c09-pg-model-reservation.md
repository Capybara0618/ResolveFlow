# C09 PG模型调用前预占（2026-09-26）

新增追加迁移 `005_agent_model_reservation.sql` 与 `runtime/recovery_store.py`。存储调用者必须先持有RUNNING run的有效owner/fence/lease和活动deadline；本步不领取run、不延长lease/deadline。所有写入先 `SELECT ... FOR UPDATE` 锁run行，**取得锁后**读取数据库时钟再校验fence/owner/状态/取消/lease/deadline，预占call_id、调用次数分区和 `agent_run.budget_spent` 同事务提交；不在事务内访问模型或工具网络。

冻结manifest、RunBudget及10普通+2恢复分区。重复初始化只接受相同配置且保留原计数；已有未分类spend明确拒绝，不能清零。稳定call_id对应原请求hash、kind和输入预占；不同请求复用同ID拒绝。重复请求只返回原预占，`new_reservation=False`，**不是UNKNOWN重发许可**。新请求使用既有BudgetGuard检查输入/输出token和deadline，实际输出ceiling按剩余额度计算；UNKNOWN保留全部估计预占。普通并发请求最多10笔成功，两笔RECOVERY_TURN仍共享12次总额。

测试：新增集成测试先RED（模块不存在，1 collection error）；实现后真实PG隔离schema四项集成 **4 passed**。连同run store、worker和分区单元回归 **43 passed**；覆盖独立存储实例重建、重复ID不重复扣款、manifest不兼容、旧fence/取消/租约过期/活动deadline过期、并发10+2、UNKNOWN输出预占与耗尽事务回滚。命令（agent目录）：`./.venv/Scripts/python.exe -m pytest tests/integration/test_recovery_budget_store.py tests/integration/test_run_store.py tests/integration/test_run_worker.py tests/unit/test_recovery_call_budget.py -q -p no:cacheprovider --tb=short`。新增文件strict mypy通过，全量 `ruff check src tests` 通过；全量strict mypy为4个既有文件9个no-any-return错误，新代码无错误。首次新增文件mypy发现冗余cast，修正后通过。

全量Python：`./.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --tb=short` → **1065 passed / 9 skipped / 1 warning，178.16s**，exit_code=0。迁移只在测试独立schema运行，不对已有业务数据执行新恢复调度；未清共享数据库或删卷。

限制：尚无生产领取租约/fence、SDK请求体/响应存储、UNKNOWN重试attempt、usage结算、工具结果复用、checkpoint、旧worker终局/回调fence；生产worker没有启用这份存储。H4/CF6、Java、all-offline及live未运行，不勾C09。下一步先为响应已落库/快照未推进窗口增加稳定结果保存与usage恰一次结算测试，再落实同事务fence校验；UNKNOWN重试必须另建attempt并另扣预算，禁止拿本步重复lookup直接发送。
