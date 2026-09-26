# C08.2 真实Case派发与回调闭环（2026-09-26）

## 本步边界

新增 `scripts/e2e_resident_dispatch.py`：在既有MySQL/PostgreSQL上启动真实Case、Commerce、Python Agent进程，Case将新工单run派发给显式mock模型的常驻Agent，Agent通过其MCP配置尝试读取物流并形成 `MANUAL_REVIEW` 方案，回调由出站投递循环送回Case。脚本只停止自己启动的子进程；它不执行审批或退款。生成的三次原始日志与JSON脚本留在本机 `reports/c08-resident-java/`，不纳入Git提交。

首次真实运行（`20260926-210820`）证明Case已派发且Agent已落 `CALLBACK_PENDING`，但Case收不到回调。Agent日志指出 `post_delivery()` 访问 `CallbackRecord.traceparent` 时 `AttributeError`；此前单测只给投递函数人工Row，而出站集成测试注入了假投递器，因此没经过真实持久记录到HTTP body的组合。新增失败测试使用 `CallbackStore.enqueue_for_run()` 返回的记录调用真实 `post_delivery()`，先稳定复现 `AttributeError`，然后在 `CallbackRecord` 和 `_as_record()` 保留数据库已有的 `traceparent` 字段。

第二次真实运行（`20260926-211129`）Case已接收 `STARTED`/`PROPOSAL`，Agent状态变 `COMPLETED`、Case进 `PENDING_REVIEW`。脚本仍按旧预期断言 `CALLBACK_PENDING` 而报失败；修正为回调被Case接受后的规范状态。第三次运行（`20260926-211305`）全部驱动断言通过：新run `14deced5-1798-5be3-adb5-c40d4a90949a` 的Case绑定 `DISPATCHED`，Case inbox含两条 `ACCEPTED`，Agent `COMPLETED`，Case `PENDING_REVIEW`。结束后独立查PG/MySQL确认Agent出站两条均 `DELIVERED:ACCEPTED`，Case收件箱两条均 `ACCEPTED`。

## 验证与限制

- `agent/.venv/Scripts/python.exe -m pytest tests/integration/test_callback_delivery.py::test_a_persisted_callback_can_be_sent_with_its_original_traceparent -q -p no:cacheprovider --tb=short`：RED为所见 `AttributeError`，修复后通过。
- `pytest tests/integration/test_callback_delivery.py tests/integration/test_delivery_loop.py tests/integration/test_callback_outbox.py -q -p no:cacheprovider --tb=short`（`agent/`）→ **48 passed / 1 warning**。
- `agent/.venv/Scripts/python.exe scripts/e2e_resident_dispatch.py`（根目录）→ 第一次真实失败、第二次脚本预期错误、第三次 **PASSED 14.8秒**；Java JAR先以Maven `-DskipTests -pl case-service,commerce-service -am package` 构建成功。MySQL、PostgreSQL为既有容器，未清库/删卷。RocketMQ容器同时运行但此阶段无审批退款事件，因此不声称MQ链路已覆盖。
- 最终全量 `agent/.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --tb=short`（`agent/`）→ **1055 passed / 9 skipped / 1 warning**，174.04秒；warning为既有Starlette/AnyIO弃用提示。
- `ruff check src tests ../scripts/e2e_resident_dispatch.py` 与 `git diff --check` → 通过；strict mypy仍为4个既有文件9错。

mock脚本固定决策，不证明模型自主性或H1；当前run持久记录没有逐次工具观察/凭证领取的结果，驱动只能证明经常驻worker到方案回调的真实Java/Python边界，不能单凭这个PASS证明MCP读取成功。Java复核退款、live模型、C09恢复/C10 strict及all-offline均未运行。下一具体动作：继续构建有引用的退款方案路径及可核查工具/政策证据，再接Case人工审批和Commerce/模拟provider的真实退款链；避免重跑已有C05功能作为代替。
