# C08.2 常驻调查 worker（2026-09-26）

## 小步1：线程生命周期

前置 `592ee33` 已推送确认。新增 `runtime/investigation.py::InvestigationLoop`，仅调用既有worker的
`run_once`；不新增Agent决策循环、服务进程、租约或恢复机制。
空队列以可唤醒Event等待，关闭后不再领取下一run；在途工作未结束时超时明确报错且仍显示running，
避免提前关闭数据库池。意外异常停止线程并显示failed，既有RUNNING记录留待C09恢复，不伪造模型失败决定。

工作目录 `agent/`：

- RED：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_investigation_loop.py -q -p no:cacheprovider --tb=short`
  → 缺模块的collection error。
- GREEN：同命令 → **7 passed**（空队列等待、关闭唤醒、在途关闭超时、异常停止、非法interval）。
- `.\.venv\Scripts\python.exe -m ruff check src tests` → 通过。
- `.\.venv\Scripts\python.exe -m mypy` → **9个既有错误，4文件，checked 53**；新增模块无错误。
- `git diff --check` → 通过。

本步尚未接API生命周期。未跑全量Python、Java、all-offline或live，服务装配后再做相关回归。
没有启动遗留后台任务；SQLite快照保留未提交。

## 小步2：服务装配

小步1 `79c7bb7` 已正常推送并远端SHA确认；fetch曾短暂TLS握手失败，但随后push及ls-remote成功。

`api/app.py` 在原FastAPI lifespan装配 `RunWorker` 与调查线程，开关
`RESOLVEFLOW_INVESTIGATION_ENABLED=1`（默认关闭）。开启时验证配置、打开/迁移库、读取已有QUEUED队列，
不等待有人先调用HTTP；禁用时保留原惰性数据库行为。回调线程在配置验证后才启动，
调查关闭由 `asyncio.to_thread` 等待线程退出，再停回调/关provider及自有连接池；外部提供的store不归app关闭。

工厂增加显式 `RESOLVEFLOW_MOCK_SCRIPT` JSON脚本来源，≤64KiB且1–12个决策对象，每run使用独立客户端/深拷贝，
不共享调用计数，不自动重复最后决定。显式传model的旧测试入口保留。live仍由现有工厂提供，未联网调用。
部署与关闭边界已补到 `docs/engineering.md`，不默认生成脚本、选择付费模型或新增服务进程。

实际验证（工作目录 `agent/`）：

- RED：`pytest tests/integration/test_resident_investigation.py -q -p no:cacheprovider --tb=short`
  → **4 failed**，create_app不接受worker配置，证明入口尚未实现。
- GREEN：同命令（现有venv的 `python.exe -m pytest`）→ **4 passed**，包括预存两run由常驻线程处理并各自产生唯一PROPOSAL、关闭线程和自有池。
- 相关控制面/回调/工厂/线程五文件：
  `.\.venv\Scripts\python.exe -m pytest tests/integration/test_resident_investigation.py tests/integration/test_deployment_factory.py tests/integration/test_run_api.py tests/integration/test_delivery_loop.py tests/unit/test_investigation_loop.py -q -p no:cacheprovider --tb=short`
  → **47 passed**（追加六个配置反例之前，42.91秒）。
- 追加畸形/空/非数组/非决策/超大mock脚本、live缺endpoint启动反例。一个超长参数值曾让Windows pytest临时路径过长，
  产生2个setup error；改为短参数ID后重跑。其间Docker基础设施容器意外处于Exited(255)，首次复跑为10 skipped，
  不是通过；仅启动已有 `resolveflow-postgres-1`（保留卷），相关回归重跑 **53 passed**。
- 额外RED：`[{}]`可通过脚本文件的结构检查却不是可执行决策，启动并未拒绝；补 `validate_decision` 预检，
  聚焦 resident/factory → **19 passed**。mock运行时仍由Harness逐步校验，启动预检不替代权限/引用验证。
- Ruff首轮报import排序与7处过长行，已修；最终 `.\.venv\Scripts\python.exe -m ruff check src tests` → **通过**。
- 最终全量 `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=short` → **1048 passed / 9 skipped / 1 warning**，146.86秒，
  运行时PostgreSQL可用；warning为Starlette/AnyIO弃用提示。此前未加动作预检的全量为1047 passed/9 skipped，不作为最终交付结果。
- `.\.venv\Scripts\python.exe -m mypy` → **9个既有 `no-any-return` 错误，4文件，checked 53**，新增代码无错误。
- 根目录 `git diff --check` 与本地Markdown链接检查 → 通过。

未运行Java、Spotless、all-offline、真实跨服务退款闭环、live/H1–H5、C09/C10；测试模型mock、真实PG隔离schema。
意外异常可见于loop.failed和日志；`/health`仍是HTTP存活检查，不声称worker故障探针或自动恢复。
单副本是当前部署边界，暂无C09生产fence/租约/恢复，不勾C08整包或H1–H5。
下一步：先用此装配入口跑真实Java/MCP/PG/MQ的mock业务闭环，再在独立步骤解决现场发现的问题。
