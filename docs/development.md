# 构建与验证

保持已有依赖锁：Java21/Maven wrapper、Python3.12/uv、Node22/pnpm12.4.1。构建和单元不需要模型密钥。

```powershell
$env:JAVA_HOME = '你的JDK21目录'
.\java\mvnw.cmd -f java/pom.xml -B -ntp test
.\java\mvnw.cmd -f java/pom.xml -B -ntp -DskipTests package
uv run --project agent --frozen pytest agent/tests/unit -q
pnpm --dir web test
pnpm --dir web build
uv run --project agent --frozen python scripts/contracts_freeze.py --check
uv run --project agent --frozen python scripts/contracts_core_freeze.py --check
```

Java测试含Testcontainers真实数据库检查，需要Docker。Agent集成测试用新schema隔离并清理自己的schema：

```powershell
$env:RESOLVEFLOW_AGENT_DB = 'postgresql://agent:agent@127.0.0.1:55432/agent_db'
uv run --project agent --frozen pytest agent/tests/integration -q
```

缺依赖的skip不计通过。脚本模型/本地传输桩只证明状态/协议/恢复，不产生新语义分数。

## 核心API冒烟（不调用模型）

Compose core profile启动三个Java进程、Agent与基础设施，使用迁移自带合成账号验证健康、登录与权限。它与完整商城初始化是不同入口。

```powershell
.\java\mvnw.cmd -f java/pom.xml -B -ntp -DskipTests package
docker compose -f infra/compose.yaml --profile core up --build -d mysql postgres redis agent commerce-service case-service gateway
python scripts/c11_core_smoke.py
docker compose -f infra/compose.yaml --profile core stop
```

默认Gateway8080。先确认端口/卷归属；不要清空已有环境。新验证使用独立Compose项目与显式端口。核心镜像默认关闭调查worker，无需模型密钥。stop保留卷，未授权不执行down -v。

## 测试与CI边界

公开保留业务不变量、Java/前端回归、Agent预算/权限/上下文/恢复、契约和小型夹具。一次性评测执行器及其专用测试留本地；核心坏例迁到agent/tests/fixtures/regressions，不读取本地reports。历史冻结manifest的检查跟随原实验归档，不弱化核心行为断言。

CI安装锁定依赖并执行构建/测试/核心Compose冒烟。verify.ps1/verify.sh保留兼容入口，all-offline包含Docker服务，不是无基础设施。旧契约文档保留字段/行号引用，不按旧任务自动开发。

## 本次整理验证（2026-10-27）

从暂存文件导出的副本验证：Java全模块打包、前端生产构建、245项前端测试、238项夹具迁移回归、21项独立PostgreSQL集成通过；两套契约冻结检查通过，488项Agent集成可收集。实际启动Agent、Commerce、Case、Gateway并通过健康、登录和商家权限检查，前端产物可访问。数据库为独立测试实例，未执行真实模型或MQ退款分发；完整商城初始化及模型效果不在本次验证内。

全量回归超出本次整理所需，用户反馈电脑卡顿后已停止，不能称全量测试或CI通过。已观察到两个Case契约元数据断言失败（路由清单/summary，相关契约本次未改）、一个ProductReviewCacheIntegrationTest缓存命中次数断言失败（期望2、实际1，原因未确认）；全量Ruff中74项位于本次未改文件，新增导入排序问题已修正，mypy未完成。没有删除失败断言或放宽CI门禁。原始日志保留本地tmp/public-clean-*，后续按需单项处理。

日常验证先做改动相关检查；资源密集的Java数据库回归、Python回归和前端构建串行执行，不默认同时启动多套容器或全量重跑。
