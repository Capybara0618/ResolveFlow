# C10 严格回放验收（2026-09-26）

## 实现与边界

- `export` 在 PostgreSQL **只读事务**中导出显式标为 `SYNTHETIC_REPLAY:` 的已完成 run，不覆写旧目录。包含原输入、manifest（含 AgentScope 2.0.8/源码与锁文件指纹）、逻辑调用顺序、实际 provider 请求体/hash、显式响应与 usage、SDK state、工具名/参数/Observation、预算前后状态、实验 Clock、终局回调。C09 的工具表只保存请求 hash；选定顺序轨迹的工具名与参数由已保存的模型动作还原，并逐一与工具表的持久 hash 核对，不匹配即拒绝导出。`files.json` 为 pack 内容 SHA-256 清单；每个导出有独立 evaluation run ID。导出时不带服务令牌或模型 API key。
- `strict` 用生产 `AgentScopeRunner`、同一权限/预算/上下文/终止逻辑以及 `RunWorker.verified_callback`，模型与工具由记录 adapter 回答。所有调用按顺序及请求 hash 核对，末尾比较回调完整 payload、预算与调用消费量；差异报告首个 model/tool step。缺记录、损坏或不支持版本/类型显式失败，不回源补齐。
- 容器入口 `scripts/replay_strict.ps1`：无网络、只读根文件系统、非 root、无能力、无新权限，pack 只读挂载；镜像只含 Agent 源码/锁及契约 schema，不挂生产凭证、DB/Java/MQ。进程内 Python socket/asyncio 拦截是回归守卫，OS 隔离由 Docker 提供。
- 支持范围限定为完整顺序、外部工具 Observation 和 mock 模型轨迹。同 run 历史迁移、并行/本地工具、live 模型/未知响应不支持。合成标记及操作者 `--synthetic-ack` 是导出门槛，不是自动敏感数据分类器。

## Golden 与反例

五包：`manual_review`（提案，1模型/0工具）、`question`（提问，1/0）、`escalation`（失败，1/0）、`read_then_review`（读取后提案，2/1）、`read_then_question`（读取后提问，2/1）。全部来自真实 PG 持久 run，不是直接拼期望输出。五条规范终局完整匹配。模型调用总计7、工具调用总计2；所有 callback payload 与最终预算逐字段一致。

五包冻结的 `manifest_id` 均为 `9656a76c54ac116cd192cf4fe96efad7383559c93a9559b264ee07b0186fdaa5`；包含 `code_revision`、AgentScope 图版本、状态 schema、提示词、工具 schema、预算、模型模式和策略 pin。包中的实际字段为准；后续源码或锁变化将使这些包显式不兼容，须用新的完整合成 run 再导出，不改旧证据冒充兼容。

反例：缺 `pack.json`、缺必需字段、文件 hash 篡改、缺模型响应、缺工具 Observation、模型请求 hash 改变、manifest/schema 不兼容、live 轨迹不支持均拒绝；首个请求差异定位 `model-0`，缺工具定位 `tool-0`。实际 socket 连接在 Python guard 被拒。容器内使用 psycopg 真实发起向测试 schema 的 SQL `INSERT`，`--network none` 拒绝连接，宿主测试表行数仍为0；这验证业务写不可达，且没有删除数据库或卷。

本轮固定验收分母：完整 5 包（5/5 `MATCH`）、损坏/缺记录/请求差异 7 种（7/7 显式拒绝）、不支持 live 类型 1 种（1/1 拒绝）。这不是对任意历史轨迹的覆盖率；未提供的包没有从这五条分母中省略。

## 验证

- `agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_replay_golden.py agent/tests/integration/test_replay_container_isolation.py agent/tests/integration/test_strict_replay.py agent/tests/integration/test_replay_export.py agent/tests/unit/test_replay_pack.py agent/tests/integration/test_run_worker.py -q`：36 passed，含五个仓库固化 pack 的直接重放。
- 相关源码 `mypy --follow-imports=silent`：8 source files 通过。全量 mypy 的既有9错仍需按既有记录区分。
- 镜像 `docker build --file infra/replay.Dockerfile --tag resolveflow-replay:local .`；五包 `docker run --network none --read-only ... resolveflow-replay:local`：5/5 `MATCH`。
- 全量 Ruff 通过。首轮全量 Agent pytest：1148 passed / 9 skipped / 1 failed / 1 warning（237.64s）；失败为 C09 `before_model_saved-2` 一次时序性终局 `FAILED`，在同期镜像构建负载下发生。单独复跑整个 C09 跨进程文件 26 passed（70.94s）。无并行构建的最终全量复验：**1154 passed / 9 skipped / 1 warning / 230.54s**。9项为既有无 citation 契约样例的 skip，warning 来自 Starlette 已弃用别名。Java/C11/收费 live 非 C10 验证，本轮未据此声明通过。

验收结论仅为：**对选定五条完整合成轨迹实现严格离线回放与回归定位**。不据此主张任意历史 run 可回放、新模型行为一致或反事实评测。
