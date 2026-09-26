# C08.2 常驻调查工具凭证接线（2026-09-26）

## 问题与改动

常驻入口已能领取并调查run，但部署工厂此前把 `RESOLVEFLOW_TOOL_SERVICE_TOKEN` 直接交给MCP读取，未向Case领取绑定run/case/revision的工具凭证。这样即使Case撤销旧revision，工具也可能继续用部署身份读取。

现在工厂为每个run建立工具执行器和凭证来源。每次读取先调用Case的 `POST /internal/v1/runs/{run_id}/tool-credential`，再把返回的run凭证交给MCP子进程；领取失败传播错误，不用部署身份回退。执行器本身不持有部署身份。API常驻入口在每个run开始时从现有JWT密钥签发短期 `agent-service` 身份，用于领取凭证，避免长期开机后使用过期的启动令牌。保留工厂显式注入身份的脚本/测试入口。

## 验证

- RED：新增工厂凭证测试首次执行在 `assert executor.credential_source is not None` 失败；原工厂确无领取源。
- 聚焦集成：`agent/.venv/Scripts/python.exe -m pytest tests/integration/test_deployment_factory.py tests/integration/test_resident_investigation.py -q -p no:cacheprovider --tb=short`，工作目录 `agent/` → **21 passed**。覆盖凭证请求run/case/revision、失败无回退、HTTP桩先领再读、常驻入口签发部署身份。HTTP上游是测试桩，MCP subprocess与PG政策检索保留真实边界。
- `agent/.venv/Scripts/python.exe -m ruff check src tests` → 通过。`agent/.venv/Scripts/python.exe -m mypy` → 4个既有文件9个 `no-any-return` 错误，新增文件无错误。
- 最终全量Python：`agent/.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --tb=short`，工作目录 `agent/` → **1050 passed / 9 skipped / 1 warning**（171.92秒）；warning为Starlette/AnyIO弃用提示。首次全量命令在调整执行器为完全不持有部署令牌后主动中断，以上为最新源码的完整复跑。
- `git diff --check` → 通过。

未运行Java、Spotless、all-offline、真实Java/Case/Commerce/MQ业务闭环、live模型、C09恢复及C10 strict；这些不能由HTTP桩测试代替。既有未跟踪SQLite快照保留，不纳入提交。

下一具体动作：审查现有e2e脚本的服务/进程副作用，在不终止未知端口占用者的前提下，从已装配常驻入口验证真实Java派发、MCP读取、回调与模拟退款闭环。
