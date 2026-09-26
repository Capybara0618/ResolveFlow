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
