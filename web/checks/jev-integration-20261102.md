# Jev 客服回答辅助检查

2026-11-02。用户选择先完成可演示的实际接入，再按效果决定简历表达；不以研究规模评测或预设提升比例阻塞。保持现有 AgentScope 主循环、流式回答、Java 权限及退款职责。

## 采用方式

- TypeSafe 官方 `POST https://api.typesafe.ai/v1/systemone`，固定 `jev-1.14.0`；使用现有 httpx，不改依赖锁。
- 三分类 `supported / contradicted / insufficient_evidence`，只作回答与本轮材料一致性辅助检查。
- 模型置信度不等于正确率，更不等于退款授权；不自动拦截或改写买家回答。
- `.env` 只存本机密钥，Git 已忽略；服务不会在 import 时自动读密钥，启动入口显式加载允许的 Jev 配置，进程环境优先。

## 第一步：客户端与配置

文件：`agent/src/resolveflow/support/jev.py`、`agent/tests/unit/test_jev.py`。

实际命令：

```powershell
.\agent\.venv\Scripts\python.exe -m pytest agent/tests/unit/test_jev.py -q
.\agent\.venv\Scripts\python.exe -m ruff check agent/src/resolveflow/support/jev.py agent/tests/unit/test_jev.py
.\agent\.venv\Scripts\python.exe -m mypy --config-file agent/pyproject.toml agent/src/resolveflow/support/jev.py
```

15 项单元通过、Ruff通过；首次先红为模块不存在的收集失败。覆盖精确模型/官方端点、密钥不进配置快照、环境优先级、保留冲突/失败材料、实际 usage、HTTP302/401/402/429/500 不重试、不跟随重定向、不保存敏感错误正文、非法响应与超时不冒充语义结果。

本步尚未接入客服运行，不宣称业务完成或质量提升；本步无付费调用。先前单条官方连通验证不作为质量评测。

## 第二步：客服运行与持久记录

文件：`support/service.py`、`support/jev_audit.py`、追加迁移 `014_support_jev_audit.sql` 和 `tests/integration/test_jev_runtime.py`。

成功回答后最多一次 Jev 请求，不编辑回答、摘要或业务动作；本轮全部已读 observations（包括失败记录）进入检查，不把仅挑出的引用当全部证据。输入过大明确跳过，不裁掉例外后继续检查。配置及源码进入 manifest；独立 `kind=jev` 区分生成模型调用和判断调用，不修改跨服务响应契约。

沿用同一模型次数/输入/输出预算与 deadline，在网络前持久预占，网络不持数据库事务；响应及 usage 经 fence 保存。已完成检查复用；STARTED 且未保存的响应保持 UNKNOWN、不自动重付。HTTP错误/超时保存 ERROR 和估算预占，不假装检查通过；余额不足等模型故障不影响原答案，数据库/fence 错误继续拒绝旧执行者写入。

验证使用独立本机 Docker 容器 `resolveflow-jev-check-20261102` 的 PG55439，没有使用或清理项目业务库/卷。

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55439/agent_db'
.\agent\.venv\Scripts\python.exe -m pytest agent/tests/unit/test_jev.py agent/tests/integration/test_jev_runtime.py agent/tests/integration/test_support_store.py agent/tests/integration/test_support_stream_runtime.py -q
```

第一轮35通过（15客户端+9新集成+11既有恢复/流式）；新增预算耗尽/完整大材料跳过两项后，新集成11通过。Ruff定向通过。首次PG未运行9跳过不作通过；使用隔离PG后9项先红（尚无接线），实现后转绿；首次Ruff三行长度已修复。既有 Starlette/AnyIO 弃用 warning 保留。暂未真实 Jev 小测，也未宣称质量提升。

接口来源：[System One](https://docs.typesafe.ai/api/system-one)、[Choice](https://docs.typesafe.ai/primitives/choice)、[模型](https://docs.typesafe.ai/models)。

定向 mypy `--follow-imports=skip` 检查3个本批源码通过；完整导入检查长时间无结果，停止本轮所属进程，未计为通过。首次定向检查暴露导入跳过后的Any返回，补显式边界cast后通过，不代表全项目类型检查。
