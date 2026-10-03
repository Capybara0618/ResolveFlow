# 正式启动入口集中验证（2026-10-03）

用户要求日常命令有正式项目体验，一次启动全部功能。本批新增根目录 `start.ps1`、`stop.ps1`、`status.ps1` 和共享入口 `scripts/project.ps1` / `scripts/project_runtime.py`；复用现有进程归属、固定端口和容器守卫，不重复实现服务启动逻辑。当前使用默认真实 Agent 调查配置，缺密钥拒绝启动，没有静默只读/mock 降级。基础数据缺失或角色未升级时拒绝自动覆盖，基础政策与索引必须精确匹配，所有组件检查完成后才报告成功。

README、当前体验/运行说明、计划与接手规则同步。`demo.ps1` 保留为旧只读、合成验收和显式重建工具；内部容器/卷/运行目录保留原名，继续使用原有数据。本批没有修改业务、权限、Agent模型选择、依赖锁或数据库迁移，也没有处理原未提交的工程说明/verify脚本/Commerce退款测试/草图和历史日志。

## 实际验证

```powershell
& agent/.venv/Scripts/ruff.exe format scripts/project_runtime.py agent/tests/unit/test_project_runtime.py
& agent/.venv/Scripts/ruff.exe check scripts/project_runtime.py agent/tests/unit/test_project_runtime.py
& agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_project_runtime.py agent/tests/unit/test_reviewer_demo_driver.py agent/tests/unit/test_demo_foundation.py -q
.\stop.ps1
.\status.ps1
.\start.ps1 -NoBrowser
.\status.ps1
.\start.ps1
.\start.ps1 -NoBrowser
git diff --check
```

- 最终三个测试文件 **45 passed / 0 skipped**，Ruff通过；新入口覆盖缺密钥不触碰服务、未初始化不重建、冷启动/已有后台都启真实Agent与网页、精确政策版本、只读不算完整、任一组件失败不能报完成/开浏览器、共享端口拒绝、停止失败返回非零、停止状态无数据库查询及错误脱敏。最初43、增加停止状态后44、最终增加完整就绪门禁后45，均通过。
- 四个 PowerShell 文件经 PowerShell 7.6.5 及系统 Windows PowerShell 的 `Language.Parser.ParseFile` 检查通过；共享脚本使用 UTF-8 BOM 保证旧 Windows PowerShell 读取中文。实际生命周期由 PowerShell 7.6.5 执行，没有将语法检查宣称为另一次运行测试。
- `stop` 返回0，所属五应用和隔离依赖容器停止，保留卷；停止后 `status` 九项未就绪且返回1，这是预期失败。冷启动默认构建三个 Java JAR（`-DskipTests`，不是全量Java测试），导入三份同hash政策均跳过、真实本地索引READY、三Java与Agent/网页健康，返回0。
- 启动自动读取已有 Windows 用户密钥，最终所属进程是 `agent-live`。状态检查数据库、namesrv/broker、Gateway、Case、Commerce、真实配置Agent、网页和政策索引，九项通过返回0。无参数 `start.ps1` 复用已有服务并成功调用系统默认浏览器；未额外操作浏览器页面。最终加入全部组件门禁后再次 `start.ps1 -NoBrowser`，九项检查及完整启动通过，五进程PID不变。
- 停止前及最终快照：46业务表逐行hash和计数一致，14账号身份/启用状态、3商家ID一致；原3笔订单/工单和资金记录保留。Agent仍为3 COMPLETED、12次历史mock模型记录、9工具记录、6回调记录，没有新增调查或模型请求。[脱敏机器证据](project-startup/verification.json)。原始hash/进程快照仅存忽略目录 `tmp/project-startup/`，不提交账号哈希、密钥或数据库快照。

## 失败及边界

本批无新增测试失败。首次暂存检查发现共享PowerShell及JSON报告使用CRLF，被仓库判为行末空白，统一为LF后再次检查通过，PowerShell保留BOM。初次只读快照辅助探针误用不存在的 `postgres_rows`，在快照写入及停止前报错；改用现有 `postgres_scalar` 后重采成功，未写业务数据。停止状态的非零退出是预期验证。

没有为验证启动新增收费模型调用或购物退款样本，也没有重新执行Java/网页全套业务测试；沿用上一批已验证业务，此处只验证生命周期。HTTP健康和真实配置不等于模型提供方每次可用或调查质量通过；新申请/补证会调用模型，现有待调查任务也会被消费。新店政策准备、模拟资金及桌面范围不变。当前基础数据已配置；新电脑仍需依赖和显式初始化，普通启动不负责清库。冷启动后所有服务保留运行，可继续体验。
